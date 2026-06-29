"""Analysis orchestration: render -> grounded checks -> (OCR) -> vision backend -> Report.

Also exposes ``check`` (the classic, no-LLM path).
"""

from __future__ import annotations

from pathlib import Path

from ..backends.base import AnalysisRequest
from ..backends.registry import select_backend
from ..config import Settings, load_settings
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


async def _render_and_ground(
    source: str, settings: Settings, *, source_type: str, viewport: Viewport | None,
    full_page: bool | None, wait_for: str | None, use_ocr: bool, out_dir: Path | None,
) -> tuple[RenderResult, list[Issue], str | None]:
    vps = [viewport] if viewport else None
    render_result = await render(
        source, settings=settings, source_type=source_type, viewports=vps,
        full_page=full_page, wait_for=wait_for, out_dir=out_dir,
    )
    primary = render_result.primary
    image_path = primary.path if primary else None

    ocr_result = None
    if use_ocr and image_path:
        try:
            from ..ocr import get_ocr_backend

            ocr = get_ocr_backend()
            if ocr.available():
                ocr_result = ocr.run(image_path)
        except Exception as e:  # noqa: BLE001
            log.debug("OCR skipped: %s", e)

    grounded = run_all_checks(render_result, image_path, ocr_result)

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
    return render_result, grounded, ocr_text


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
    """
    settings = settings or load_settings()
    grade_intent = brief is not None and not brief.is_empty()
    render_result, grounded, ocr_text = await _render_and_ground(
        source, settings, source_type=source_type, viewport=viewport,
        full_page=full_page, wait_for=wait_for,
        use_ocr=use_ocr or grade_intent, out_dir=out_dir,
    )
    primary = render_result.primary
    if primary is None:
        return Report(verdict=Verdict.FAIL, summary="Render produced no image.",
                      backend="none", capabilities=[])

    vision, fallback_warning = select_backend(settings, backend)
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

    # Ground truth from DOM + OCR — overrules contradicted vision claims and grades text
    # requirements deterministically.
    dom_text = " ".join(b.text for b in render_result.dom_boxes if getattr(b, "text", ""))
    haystack = " ".join(t for t in (ocr_text, dom_text) if t)

    # Never let an advisory vision "missing"/intent claim survive when DOM/OCR proves the
    # element is present (text in DOM/OCR, or a named visual whose DOM tag exists).
    kept, dropped = suppress_contradicted_vision(
        report.issues, haystack, render_result.visual_tags
    )
    if dropped:
        report.issues = kept
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
    """
    settings = settings or load_settings()
    grade_intent = brief is not None and not brief.is_empty()
    render_result, grounded, ocr_text = await _render_and_ground(
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
        ocr_results = check_claims_ocr(claims, ocr_text)
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
