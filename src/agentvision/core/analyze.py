"""Analysis orchestration: render -> grounded checks -> (OCR) -> vision backend -> Report.

Also exposes ``check`` (the classic, no-LLM path).
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from ..backends.base import AnalysisRequest
from ..backends.registry import select_backend
from ..config import Settings, load_settings
from ..errors import UnsafeSourceError
from ..logging import get_logger
from ..models.geometry import Viewport
from ..models.intent import Brief
from ..models.report import (
    Confidence,
    Conformance,
    Issue,
    IssueKind,
    IssueSource,
    Report,
    Severity,
    Verdict,
    verdict_from_issues,
)
from ..renderers.base import RenderResult
from .checks import CLASSIC_CAPABILITIES, run_all_checks
from .intent import (
    _VISUAL_KW,
    build_conformance,
    check_claims_ocr,
    derive_claims,
    gate_verdict,
    ocr_violation_issues,
    suppress_contradicted_vision,
)
from .render import render

log = get_logger("analyze")


def assert_screen_egress_allowed(source_type: str, vision, settings: Settings) -> None:
    """Fail closed before a live desktop capture is sent to a NON-local vision backend.

    The OS screenshot portal authorizes *capturing* the screen; it does not authorize shipping
    those pixels to a third-party cloud model. That second egress requires an explicit opt-in
    (``allow_screen_capture_egress`` / CLI ``--allow-egress`` / MCP ``allow_egress=True``). The
    ``local`` backend never egresses and is always allowed. Called at the single choke point
    right before ``vision.analyze`` so no dispatch branch (analyze or watch) can bypass it.
    """
    if source_type != "desktop":
        return
    if getattr(vision, "name", "local") == "local":
        return
    if settings.allow_screen_capture_egress:
        log.warning(
            "sending a live desktop screen capture to the '%s' vision backend — the captured "
            "pixels are leaving this machine (egress opt-in is enabled).",
            getattr(vision, "name", "?"),
        )
        return
    raise UnsafeSourceError(
        f"Refusing to send a live desktop screen capture to the non-local '"
        f"{getattr(vision, 'name', '?')}' vision backend: the captured pixels would leave this "
        "machine. Use --backend local for an offline (no-egress) grade, or pass --allow-egress "
        "(MCP allow_egress=True / allow_screen_capture_egress=True) to consent to the upload."
    )


def _is_motion(source: str, source_type: str, settings: Settings) -> bool:
    """True when the source resolves to local motion media (video / animated GIF)."""
    if source_type not in {"auto", "motion", "file"}:
        return False  # explicit non-motion type is an override (e.g. grade a GIF as a still)
    try:
        from ..sources import resolve_source

        return resolve_source(source, source_type, settings=settings).kind == "motion"
    except Exception:  # noqa: BLE001  # let the normal render path raise the real error
        return False


def _is_desktop(source: str, source_type: str, settings: Settings) -> bool:
    """True when the source resolves to a live desktop screen capture."""
    try:
        from ..sources import resolve_source

        return resolve_source(source, source_type, settings=settings).kind == "desktop"
    except Exception:  # noqa: BLE001  # gate/other errors surface on the real render path
        return False


def _wants_visual_judgment(brief: Brief | None, claims) -> bool:
    """True when the intent mentions a visual element (chart/canvas/image/…)."""
    text = " ".join([(brief.text if brief else "") or ""] + [c.text for c in claims]).lower()
    return any(kw in text for kw in _VISUAL_KW)


def _visual_crop_paths(image_path: str, elements, *, max_crops: int) -> list[str]:
    """Save full-res crops of the largest visual elements; return their paths."""
    from ..imageguard import open_image_safely

    try:
        im = open_image_safely(image_path).convert("RGB")
    except Exception:  # noqa: BLE001
        return []
    w, h = im.size
    base = Path(image_path).parent
    out: list[str] = []
    for i, e in enumerate(sorted(elements, key=lambda e: e.bbox.width * e.bbox.height,
                                 reverse=True)):
        if len(out) >= max_crops:
            break
        x0, y0 = max(0, int(e.bbox.x)), max(0, int(e.bbox.y))
        x1 = min(w, int(e.bbox.x + e.bbox.width))
        y1 = min(h, int(e.bbox.y + e.bbox.height))
        if x1 - x0 < 32 or y1 - y0 < 32:  # too small / off-screen (e.g. below a viewport shot)
            continue
        p = base / f"vcrop_{i}.png"
        try:
            im.crop((x0, y0, x1, y1)).save(p)
            out.append(str(p))
        except Exception:  # noqa: BLE001
            continue
    return out


_CPU_SLOTS: threading.BoundedSemaphore | None = None
_CPU_SLOTS_LOCK = threading.Lock()


def _cpu_slot(n: int) -> threading.BoundedSemaphore:
    global _CPU_SLOTS
    with _CPU_SLOTS_LOCK:
        if _CPU_SLOTS is None:
            _CPU_SLOTS = threading.BoundedSemaphore(max(1, n))
        return _CPU_SLOTS


async def _in_worker(settings: Settings, fn, *args, **kwargs):
    """Run a CPU-bound grading stage in a worker thread under a process-wide slot.

    The slot is taken and released INSIDE the thread, so when a request is cancelled (the
    REST deadline fires) its abandoned work keeps holding the slot until it really finishes:
    cancelled requests can't stack up OCR/pixel work beyond ``max_concurrent_renders``.
    """
    slots = _cpu_slot(settings.max_concurrent_renders)

    def _run():
        with slots:
            return fn(*args, **kwargs)

    return await asyncio.to_thread(_run)


def _legible_ocr_text(render_result: RenderResult, ocr_words: list) -> str:
    """Page OCR words that are actually visible: each word's own pixels must show ink at
    >= 2:1. Tesseract binarizes internally, so it reads text a human cannot see (254 on 255
    under a 99%-opaque cover); such words must not satisfy a requirement."""
    primary = render_result.primary
    if not ocr_words or primary is None:
        return ""
    from PIL import Image

    from .checks._pixel_contrast import worst_case_contrast

    try:
        img = Image.open(primary.path).convert("RGB")
    except Exception:  # noqa: BLE001 — no pixels, no legible text (fail closed)
        return ""
    iw, ih = img.size
    keep: list[str] = []
    for w in ocr_words:
        b = w.bbox
        x0, y0 = max(0, int(b.x) - 2), max(0, int(b.y) - 2)
        x1, y1 = min(iw, int(b.x + b.width) + 2), min(ih, int(b.y + b.height) + 2)
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        wc = worst_case_contrast(img.crop((x0, y0, x1, y1)))
        if wc is not None and wc[0] >= _LEGIBLE:
            keep.append(w.text)
    return " ".join(keep)


# A reader can see it at all (not a WCAG bar — contrast defects are graded separately).
_LEGIBLE = 2.0


def _claim_ocr_text(render_result: RenderResult, ocr_words: list,
                    claims: list | None = None, notes: list | None = None) -> str | None:
    """Ground truth for quoted requirements: text OCR reads in the captured pixels.

    DOM text alone never counts: a page can keep a required string in its DOM while painting
    it invisible, covered (even by a cover carrying other text) or off-screen. But page-level
    Tesseract misses light-on-dark labels (a white "Subscribe" on a blue button). So for each
    quoted string the page OCR missed, the DOM elements that claim to hold it are re-read
    *at their own glyph box*: the crop is Otsu-binarized with ink forced dark, upscaled, and
    OCR'd. The string counts only if OCR reads it there — a cover reads as the cover's text.
    """
    from .intent import _QUOTED, _norm

    try:
        from ..ocr import get_ocr_backend

        if not get_ocr_backend().available():
            return None  # OCR can't run here: quoted claims stay ungraded, not violated
    except Exception:  # noqa: BLE001
        return None
    ocr_text = _legible_ocr_text(render_result, ocr_words)
    have = _norm(ocr_text or "")
    extra: list[str] = []
    from .intent import contains_phrase

    wanted = [q for c in (claims or []) for q in _QUOTED.findall(c.text)
              if _norm(q) and not contains_phrase(have, _norm(q))]
    primary = render_result.primary
    if wanted and primary is not None:
        try:
            extra, exhausted = _corroborate_at_glyphs(render_result, primary.path, wanted)
            if exhausted and notes is not None:
                notes.append(Issue.make(
                    IssueKind.OTHER, Severity.ERROR,
                    "Text-requirement checks hit their time/size limit on this page, so some "
                    "quoted requirements could not be confirmed in the pixels.",
                    source=IssueSource.OCR, confidence=Confidence.HIGH,
                    detail={"claim_corroboration_truncated": True},
                ))
        except Exception as e:  # noqa: BLE001 — no corroboration = not satisfied (fail closed)
            log.warning("glyph OCR corroboration failed: %s", e)
    return " ".join(t for t in [ocr_text or "", *extra] if t)


# Bounds for glyph-crop OCR corroboration (an attacker page must not pin the grader's CPU).
_CORROB_BUDGET_S = 12.0
_CORROB_MAX_PIXELS = 4_000_000   # summed over every crop OCR'd (after upscaling)
_CORROB_OCR_TIMEOUT_S = 5.0


def _corroborate_at_glyphs(render_result: RenderResult, image_path: str,
                           wanted: list[str]) -> tuple[list[str], bool]:
    """Returns (phrases read at their glyph boxes, whether the budget ran out)."""
    import time as _time

    import numpy as np
    from PIL import Image

    from ..ocr import get_ocr_backend
    from .checks._pixel_contrast import (
        _luma,
        _otsu_threshold,
        halo_painted,
        worst_case_contrast,
    )
    from .intent import _norm, contains_phrase

    ocr = get_ocr_backend()
    if not ocr.available():
        return [], False
    img = Image.open(image_path).convert("RGB")
    t0 = _time.monotonic()
    pixels = 0
    iw, ih = img.size
    out_dir = Path(image_path).parent
    found: list[str] = []
    for qi, q in enumerate(wanted[:10]):
        nq = _norm(q)
        cands = [c for c in render_result.contrast_samples
                 if c.glyph_bbox is not None and contains_phrase(_norm(c.text), nq)][:5]
        for ci, c in enumerate(cands):
            g = c.glyph_bbox
            assert g is not None
            x0, y0 = max(0, int(g.x) - 6), max(0, int(g.y) - 6)
            x1, y1 = min(iw, int(g.x + g.width) + 6), min(ih, int(g.y + g.height) + 6)
            # Mostly in frame, readable size, bounded area (OCR cost).
            if (x1 - x0) < 0.5 * g.width or (y1 - y0) < 0.5 * g.height or y1 - y0 < 8:
                continue
            if (x1 - x0) * (y1 - y0) > 4_000_000:
                continue
            area = (x1 - x0) * (y1 - y0) * (9 if (y1 - y0) < 60 else 1)
            if (_time.monotonic() - t0 > _CORROB_BUDGET_S
                    or pixels + area > _CORROB_MAX_PIXELS):
                return found, True
            pixels += area
            crop = img.crop((x0, y0, x1, y1))
            # Legibility FIRST: binarization makes even 1-luma-level text crisp, so OCR reading
            # it proves nothing. The ink ACTUALLY painted must measure >= 2:1 (not the declared
            # colour: under a 99% cover black-on-white still "computes" as 21:1). A halo
            # counts only if it is visibly painted around the glyphs.
            if c.halo and c.fg_rgba is not None:
                need = 3.0 if c.large_text else 4.5
                if not all(halo_painted(img, r, c.fg_rgba[:3], need)
                           for r in (c.glyph_rects or [g])):
                    continue
            else:
                wc = worst_case_contrast(crop)
                if wc is None or wc[0] < _LEGIBLE:
                    continue
            lum = _luma(np.asarray(crop).reshape(-1, 3).astype(float))
            bw = (lum > _otsu_threshold(lum)).reshape(crop.size[1], crop.size[0])
            scale = 3 if crop.size[1] < 60 else 1
            size = (crop.size[0] * scale, crop.size[1] * scale)
            # Three readings: ink-dark binarization, its inverse, and plain grayscale (outlined
            # or haloed glyphs binarize badly).
            readings = [bw if bw.mean() >= 0.5 else ~bw, ~bw if bw.mean() >= 0.5 else bw]
            imgs = [Image.fromarray((r * 255).astype("uint8")) for r in readings]
            imgs.append(crop.convert("L"))
            if c.fg_rgba is not None:
                # Known-colour mask: pixels near the text's own fill colour are ink. Isolates
                # white glyphs from a dark halo, which plain binarization merges.
                px = np.asarray(crop).astype(float)
                d = np.sqrt(((px - np.array(c.fg_rgba[:3])) ** 2).sum(-1))
                imgs.append(Image.fromarray(np.where(d < 60, 0, 255).astype("uint8")))
            for k, im in enumerate(imgs):
                if _time.monotonic() - t0 > _CORROB_BUDGET_S:
                    return found, True
                path = out_dir / f"claim_{qi}_{ci}_{k}.png"
                im.resize(size, Image.Resampling.LANCZOS).save(path)
                try:
                    try:
                        text = ocr.run(str(path), timeout_s=_CORROB_OCR_TIMEOUT_S).text
                    except TypeError:  # an OCR backend without per-call timeouts
                        text = ocr.run(str(path)).text
                except Exception:  # noqa: BLE001 — a timed-out reading is just "not read"
                    text = ""
                finally:
                    path.unlink(missing_ok=True)
                if contains_phrase(_norm(text), nq):
                    found.append(q)
                    break
            if q in found:
                break
    return found, False


def _explain_dom_only(results: dict, render_result: RenderResult) -> None:
    """A required text that is in the DOM but not in the pixels stays VIOLATED; say why."""
    from .intent import _QUOTED, _norm

    dom = _norm(" ".join(b.text for b in render_result.dom_boxes if b.text))
    for res in results.values():
        if res.status.value != "violated":
            continue
        if any(_norm(q) and _norm(q) in dom for q in _QUOTED.findall(res.text)):
            res.evidence += (" — it exists in the page DOM but is not visible in the captured "
                             "image (hidden, covered, unreadable, or outside the capture: use "
                             "--full-page for text below the fold)")


async def _render_and_ground(
    source: str, settings: Settings, *, source_type: str, viewport: Viewport | None,
    full_page: bool | None, wait_for: str | None, use_ocr: bool, out_dir: Path | None,
) -> tuple[RenderResult, list[Issue], str | None, list]:
    vps = [viewport] if viewport else None
    render_result = await render(
        source, settings=settings, source_type=source_type, viewports=vps,
        full_page=full_page, wait_for=wait_for, out_dir=out_dir,
    )
    primary = render_result.primary
    image_path = primary.path if primary else None

    ocr_result = None
    ocr_failure: str | None = None
    if use_ocr and image_path:
        ocr = None
        try:
            from ..ocr import get_ocr_backend

            ocr = get_ocr_backend()
            if ocr.available():
                # CPU-bound stages run in a worker thread so a slow page never blocks the
                # event loop (REST/MCP serve other requests meanwhile).
                ocr_result = await _in_worker(settings, ocr.run, image_path)
        except Exception as e:  # noqa: BLE001
            # OCR is installed but failed (timeout, corrupt raster, ...). Fail closed: the text
            # checks it powers did not run, so the report must not read as a clean PASS.
            if ocr is not None:
                ocr_failure = f"{type(e).__name__}: {e}"[:200]
            log.warning("OCR failed: %s", e)

    grounded = await _in_worker(
        settings, run_all_checks, render_result, image_path, ocr_result,
        extra_words=settings.spell_vocabulary(), spell_variants=settings.spell_variants,
    )
    if ocr_failure:
        grounded.append(Issue.make(
            IssueKind.OTHER, Severity.ERROR,
            "OCR failed, so text checks (typos, text requirements, canvas-text contrast) did "
            f"not run: {ocr_failure}",
            source=IssueSource.OCR, confidence=Confidence.HIGH,
            detail={"ocr_failure": ocr_failure},
        ))

    # Offline, deterministic PPTX slide inspection (unreadable contrast / off-slide / overlap)
    # using the OOXML geometry + the rendered per-slide pixels. No LLM, no egress.
    if render_result.source_type == "office":
        try:
            import os
            import re as _re

            from ..sources import resolve_source
            from .checks.slides import check_pptx

            resolved = resolve_source(source, source_type, settings=settings)
            if resolved.path and str(resolved.path).lower().endswith(".pptx"):
                pages = [im.path for im in render_result.images
                         if _re.search(r"page_\d+\.\w+$", os.path.basename(im.path))]
                if not pages:  # single slide (no composite prepended)
                    pages = [im.path for im in render_result.images]
                grounded += check_pptx(resolved.path, sorted(pages), settings)
        except Exception as e:  # noqa: BLE001
            log.debug("pptx inspection skipped: %s", e)

    ocr_text = ocr_result.text or None if ocr_result else None
    return render_result, grounded, ocr_text, (list(ocr_result.words) if ocr_result else [])


async def analyze(
    source: str,
    *,
    settings: Settings | None = None,
    backend: str | None = None,
    instructions: str | None = None,
    expected: str | None = None,
    brief: Brief | None = None,
    use_ocr: bool = True,
    source_type: str = "auto",
    viewport: Viewport | None = None,
    full_page: bool | None = None,
    wait_for: str | None = None,
    out_dir: Path | None = None,
) -> Report:
    """Full visual analysis: structural grounding + vision-backend critique.

    When ``brief`` is given, the render is also graded for **intent conformance** — does it
    match what the agent set out to build — and the verdict is gated on it.

    Motion sources (a video file or an animated GIF) are automatically routed to the
    temporal grader (``watch``) — sampled over time, never flattened to a single frame or
    mis-rendered by the browser.
    """
    settings = settings or load_settings()
    # A live desktop capture is confidential by nature — never let the screenshot (or its
    # crops/tiles) persist to the shared on-disk cache. Force ephemeral at the CORE, so the
    # library path is protected too, not just the CLI/MCP adapters. Re-enters ephemeral=True.
    if not settings.ephemeral and _is_desktop(source, source_type, settings):
        from ..workspace import ephemeral_cache

        with ephemeral_cache(settings) as eph:
            return await analyze(
                source, settings=eph, backend=backend, instructions=instructions,
                expected=expected, brief=brief, use_ocr=use_ocr, source_type=source_type,
                viewport=viewport, full_page=full_page, wait_for=wait_for, out_dir=out_dir,
            )
    if _is_motion(source, source_type, settings):
        from .watch import watch

        return await watch(source, settings=settings, backend=backend, brief=brief,
                           instructions=instructions, use_vision=True,
                           source_type=source_type, out_dir=out_dir)
    grade_intent = brief is not None and not brief.is_empty()
    render_result, grounded, ocr_text, ocr_words = await _render_and_ground(
        source, settings, source_type=source_type, viewport=viewport,
        full_page=full_page, wait_for=wait_for,
        use_ocr=use_ocr or grade_intent, out_dir=out_dir,
    )
    primary = render_result.primary
    if primary is None:
        return Report(verdict=Verdict.FAIL, summary="Render produced no image.",
                      backend="none", capabilities=[])

    vision, fallback_warning = select_backend(settings, backend)
    # Fail closed on desktop→cloud egress (see assert_screen_egress_allowed). The OS portal
    # authorizes the capture; shipping the frame to a third-party model is a separate consent.
    assert_screen_egress_allowed(render_result.source_type, vision, settings)
    # Pre-derive claims so the vision call can grade against the numbered checklist.
    claims = await derive_claims(brief, backend=vision) if grade_intent else []

    # Give the eyes full detail, never just a downscaled blur:
    #  (1) focused FULL-RES crops of named visual regions when grading visual intent, and
    #  (2) source-agnostic FULL-RES coverage tiles of any large artifact (pixel-based — works
    #      for HTML, a flat image, a PDF page, a canvas, an iframe). Bounded by max_vision_tiles.
    extra_images: list[str] = []
    is_vision = getattr(vision, "name", "local") != "local"
    if (is_vision and grade_intent and settings.crop_visual_claims
            and render_result.visual_elements and _wants_visual_judgment(brief, claims)):
        extra_images += _visual_crop_paths(
            primary.path, render_result.visual_elements, max_crops=settings.max_visual_crops
        )
    if is_vision and settings.vision_full_coverage:
        budget = settings.max_vision_tiles - len(extra_images)
        if budget > 0:
            from .tiling import plan_coverage_tiles

            extra_images += plan_coverage_tiles(
                primary.path, max_edge=settings.vision_max_edge_px, max_tiles=budget
            )
    extra_images = extra_images[: settings.max_vision_tiles]

    req = AnalysisRequest(
        image_path=primary.path, viewport=primary.viewport,
        device_scale=settings.device_scale, instructions=instructions,
        expected=expected, ocr_text=ocr_text, dom_hints=grounded,
        claims=[c.text for c in claims], extra_images=extra_images,
        reference_image_path=(brief.reference_image if grade_intent else None),
    )
    report = await vision.analyze(req)

    # Ground truth from OCR of the painted pixels — overrules contradicted vision claims and
    # grades text requirements deterministically.
    claim_notes: list[Issue] = []
    haystack = await _in_worker(
        settings, _claim_ocr_text, render_result, ocr_words, claims if grade_intent else None,
        claim_notes)

    # Never let an advisory vision "missing"/intent claim survive when DOM/OCR proves the
    # element is present (text in DOM/OCR, or a named visual whose DOM tag exists).
    kept, dropped = suppress_contradicted_vision(
        report.issues, haystack, render_result.visual_tags
    )
    if dropped:
        report.issues = kept
        report.verdict = verdict_from_issues(report.issues)
        # Never overrule silently: the model's summary may still describe what was dropped.
        report.summary = (
            f"{report.summary} ({len(dropped)} vision finding(s) overruled: DOM/OCR shows "
            "the element is present.)"
        )
    if claim_notes:  # corroboration ran out of budget: never a silent partial grade
        report.issues.extend(claim_notes)
        report.verdict = verdict_from_issues(report.issues)

    if fallback_warning:
        # Mark as a synthetic fallback notice so downstream consumers (e.g. a brain's sense
        # adapter) can keep it for provenance but exclude it from gating.
        report.issues.insert(0, Issue.make(
            IssueKind.OTHER, Severity.WARNING, fallback_warning,
            source=IssueSource.CV, confidence=Confidence.LOW, detail={"fallback": True},
        ))
        if report.verdict == Verdict.PASS:
            report.verdict = Verdict.WARN

    if grade_intent:
        ocr_results = check_claims_ocr(claims, haystack)
        _explain_dom_only(ocr_results, render_result)
        report.issues.extend(ocr_violation_issues(ocr_results))
        semantic_graded = getattr(vision, "name", "local") != "local"
        conformance = build_conformance(
            claims, report.issues, ocr_results, semantic_graded=semantic_graded
        )
        report.conformance = conformance
        report.verdict = gate_verdict(report.verdict, conformance)
        if conformance.claims:
            report.summary = (
                f"{report.summary} Intent match: {conformance.satisfied}/"
                f"{conformance.total} requirement(s) satisfied."
            )
    return report


async def check(
    source: str,
    *,
    settings: Settings | None = None,
    brief: Brief | None = None,
    source_type: str = "auto",
    viewport: Viewport | None = None,
    full_page: bool | None = None,
    wait_for: str | None = None,
    use_ocr: bool = True,
    out_dir: Path | None = None,
) -> Report:
    """Classic checks only — no LLM, no API key, no egress (incl. OCR spell-check).

    With a ``brief``, also grades **text** requirements deterministically via OCR; non-text
    requirements are reported ``uncertain`` (the offline path cannot judge visual intent).

    Motion sources route to the temporal grader with the vision pass off (deterministic
    motion/black/dead-export signals only — still no LLM, no egress).
    """
    settings = settings or load_settings()
    # Desktop capture is confidential even on the offline path (no egress, but the screenshot
    # still hits disk) — force ephemeral at the core so `check("desktop:")` never persists it.
    if not settings.ephemeral and _is_desktop(source, source_type, settings):
        from ..workspace import ephemeral_cache

        with ephemeral_cache(settings) as eph:
            return await check(
                source, settings=eph, brief=brief, source_type=source_type, viewport=viewport,
                full_page=full_page, wait_for=wait_for, use_ocr=use_ocr, out_dir=out_dir,
            )
    if _is_motion(source, source_type, settings):
        from .watch import watch

        return await watch(source, settings=settings, brief=brief, use_vision=False,
                           source_type=source_type, out_dir=out_dir)
    grade_intent = brief is not None and not brief.is_empty()
    render_result, grounded, ocr_text, ocr_words = await _render_and_ground(
        source, settings, source_type=source_type, viewport=viewport,
        full_page=full_page, wait_for=wait_for,
        use_ocr=use_ocr or grade_intent, out_dir=out_dir,
    )
    primary = render_result.primary
    issues = list(grounded)
    conformance: Conformance | None = None
    if grade_intent:
        from ..backends.local_backend import LocalBackend

        # Offline path: LocalBackend.complete_text() == "" → only explicit claims are used.
        claims = await derive_claims(brief, backend=LocalBackend())
        # Same ground truth as analyze(): OCR of the pixels, corroborated at glyph boxes.
        claim_notes_c: list[Issue] = []
        ocr_results = check_claims_ocr(
            claims, await _in_worker(
                settings, _claim_ocr_text, render_result, ocr_words, claims, claim_notes_c))
        issues.extend(claim_notes_c)
        _explain_dom_only(ocr_results, render_result)
        issues.extend(ocr_violation_issues(ocr_results))
        conformance = build_conformance(
            claims, issues, ocr_results, semantic_graded=False
        )

    verdict = verdict_from_issues(issues)
    if conformance is not None:
        verdict = gate_verdict(verdict, conformance)
    summary = (f"Structural checks found {len(issues)} issue(s)." if issues
               else "Structural checks passed (no DOM/CV defects detected).")
    if conformance and conformance.claims:
        summary += (f" Intent match (text-only, offline): {conformance.satisfied}/"
                    f"{conformance.total} requirement(s) satisfied.")
    return Report(
        verdict=verdict,
        summary=summary,
        issues=issues,
        conformance=conformance,
        capabilities=CLASSIC_CAPABILITIES,  # type: ignore[arg-type]
        backend="checks",
        viewport=primary.viewport if primary else Viewport(),
        device_scale=settings.device_scale,
        image_path=primary.path if primary else None,
    )
