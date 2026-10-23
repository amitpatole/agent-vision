"""Pixel-grade text legibility where computed-style contrast can't see the background.

A DOM contrast sample is emitted ``confidence == "low"`` when the text sits over a
``background-image`` / gradient / compounded opacity / a ``<canvas>`` — the computed
``background-color`` is not the real backdrop, so the ratio is a confident guess. The classic
[`check_contrast_dom`](contrast.py) hands those samples here rather than guessing.

This check reads the **rendered pixels** under each such sample and grades the text against the
worst-case background patch (see :mod:`._pixel_contrast`). That turns "verify manually" into an
actionable verdict for the exact case that motivated it: a map popup whose metric text is
unreadable over the raster heat tiles. Output is deliberately **banded** (clear-fail / marginal),
not a precise ratio, and carries ``source = cv`` so it reads as a distinct, pixel-derived tier
from exact computed-style contrast.
"""

from __future__ import annotations

import time
from pathlib import Path

from ...logging import get_logger
from ...models.report import Confidence, Issue, IssueKind, IssueSource, Severity
from ...renderers.base import ContrastSample, RenderResult
from ._pixel_contrast import (
    contrast_ratio,
    exact_fg_contrast,
    halo_painted,
    worst_case_contrast,
)

log = get_logger("contrast_pixel")

_FAIL = 3.0   # clearly unreadable
_AA = 4.5     # AA minimum for normal text
_AA_LARGE = 3.0  # AA minimum for large text


def _snippet(text: str) -> str:
    return (text[:40] + "…") if len(text) > 40 else text


# Below this computed ratio, a crop with no measurable ink is graded as unreadable (ERROR).
_NO_INK_FAIL = 3.0
# An effect-repainted sample that passes on computed style FAILs only when measured below this
# (e.g. opacity:.1 or filter:brightness(6) text). Above it nothing is reported, because
# anti-aliasing alone reads #666 at 11px as ~2.8:1.
_EFFECT_FAIL = 2.0


def _no_ink(s: ContrastSample) -> Issue:
    snip = _snippet(s.text)
    return Issue.make(
        IssueKind.CONTRAST, Severity.ERROR,
        f"Unreadable text '{snip}': computed contrast {s.ratio:.2f} and no readable ink in the "
        f"rendered pixels [{s.fg} on {s.bg}]",
        bbox=s.bbox, bbox_precise=True, source=IssueSource.CV, confidence=Confidence.MEDIUM,
        detail={"ratio": s.ratio, "fg": s.fg, "bg": s.bg, "selector": s.selector,
                "wcag": "AA-fail", "large_text": s.large_text, "pixel_ink": False},
    )


def _advisory(s: ContrastSample) -> Issue:
    """Fallback when the pixels can't be measured — keep the honest 'verify manually' signal
    the DOM check used to emit for a non-solid background (never a hard fail)."""
    snip = _snippet(s.text)
    return Issue.make(
        IssueKind.CONTRAST, Severity.WARNING,
        f"Low contrast (ratio {s.ratio:.2f}, needs {'3.0' if s.large_text else '4.5'} for AA) "
        f"on text '{snip}' [{s.fg} on {s.bg}] (background not solid — verify manually)",
        bbox=s.bbox, bbox_precise=True, source=IssueSource.DOM, confidence=Confidence.LOW,
        detail={"ratio": s.ratio, "fg": s.fg, "bg": s.bg, "selector": s.selector,
                "wcag": "AA-fail", "large_text": s.large_text},
    )


def _open(image_path: str | Path | None):
    if not image_path:
        return None
    try:
        from PIL import Image

        return Image.open(image_path).convert("RGB")
    except Exception as e:  # noqa: BLE001 — missing/unreadable image → advisory fallback
        log.debug("pixel contrast: cannot open %s: %s", image_path, e)
        return None


def _crop(img, bbox):
    """Crop the sample's bbox (image px), clamped to the image; None if it's too small."""
    iw, ih = img.size
    x0 = max(0, int(bbox.x))
    y0 = max(0, int(bbox.y))
    x1 = min(iw, int(bbox.x + bbox.width))
    y1 = min(ih, int(bbox.y + bbox.height))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    return img.crop((x0, y0, x1, y1))


# Measured ink below this while the declared colour should read: the text is not visibly painted.
_NOT_PAINTED = 1.3


def _covered(s: ContrastSample, painted: float | None, declared: float | None) -> Issue:
    """Text whose colour should read here, but whose ink is missing or dimmed in the pixels:
    an overlay covers it. An overlap condition (WARNING), consistent with the overlap check —
    cookie banners, paywall fades and modals cover text by design. Quoted requirements are
    still graded on legible OCR, so covered text never satisfies one."""
    snip = _snippet(s.text)
    seen = f"~{painted:.2f}:1" if painted is not None else "no ink"
    want = f" (its colour should read at ~{declared:.1f}:1 here)" if declared else ""
    return Issue.make(
        IssueKind.OVERLAP, Severity.WARNING,
        f"Text '{snip}' is covered or dimmed by an overlay: the rendered pixels show {seen}"
        f"{want}.",
        bbox=s.bbox, bbox_precise=True, source=IssueSource.CV, confidence=Confidence.MEDIUM,
        detail={"measured_ratio": None if painted is None else round(painted, 2),
                "declared_ratio": None if declared is None else round(declared, 2),
                "selector": s.selector, "method": "painted-vs-declared"},
    )


def _mean(crop) -> tuple:
    import numpy as np

    return tuple(np.asarray(crop).reshape(-1, 3).astype(float).mean(0))


def _plain_fail(s: ContrastSample, ratio: float) -> Issue:
    snip = _snippet(s.text)
    return Issue.make(
        IssueKind.CONTRAST, Severity.ERROR,
        f"Low contrast over the real backdrop: '{snip}' is {s.fg} and measures ~{ratio:.1f}:1 "
        "against the pixels behind it (the computed background was not the painted one).",
        bbox=s.bbox, bbox_precise=True, source=IssueSource.CV, confidence=Confidence.MEDIUM,
        detail={"measured_ratio": round(ratio, 2), "declared_ratio": s.ratio, "fg": s.fg,
                "selector": s.selector, "method": "dom-fg-vs-pixel-bg"},
    )


def _line_ratio(s: ContrastSample, m: tuple) -> float:
    """One line's ratio. For plain colours the painted fg is known exactly, so it is also graded
    against the REAL backdrop pixels; otherwise other dark ink in the crop (a bold child word,
    an underline) is what gets measured. Effects make the DOM colour meaningless: pixels only."""
    ratio_m, _f, _ink, bg_px = m
    if s.paint_effects or s.fg_rgba is None:
        return ratio_m
    r0, g0, b0, a0 = s.fg_rgba
    fg = (r0 * a0 + bg_px[0] * (1 - a0), g0 * a0 + bg_px[1] * (1 - a0),
          b0 * a0 + bg_px[2] * (1 - a0))
    return min(ratio_m, contrast_ratio(fg, bg_px))


def check_contrast_pixel(render: RenderResult, image_path: str | Path | None) -> list[Issue]:
    """Grade every low-confidence DOM contrast sample against the real pixels.

    A low-confidence sample is one whose backdrop (or paint) the computed style can't know:
    an image or gradient behind it, opacity, a filter or blend, a stroke or shadow. Each is
    graded line by line on its own glyph boxes. The pass is bounded (samples, crops, time);
    running out is an ERROR, never a silent partial grade.
    """
    # Text under a fixed/sticky overlay is the overlap check's business: the capture shows the
    # overlay there, not the text.
    lows = [s for s in render.contrast_samples if s.confidence == "low" and not s.inactive]
    if not lows:
        return []
    img = _open(image_path)
    if img is None:
        return [_advisory(s) for s in lows if not s.passes_aa]

    issues: list[Issue] = []
    iw, ih = img.size
    # Only samples with a line in the capture cost anything or can be judged; out-of-frame
    # ones (the rest of a long article) are skipped up front and never count toward the caps.
    lows = [s for s in lows if _any_in_frame(s, iw, ih)]
    t0 = time.monotonic()
    crops_used = 0
    for n_done, s in enumerate(lows):
        if (n_done >= _MAX_SAMPLES or crops_used >= _MAX_CROPS
                or time.monotonic() - t0 > _BUDGET_S):
            issues.append(_budget_exceeded(len(lows) - n_done))
            break
        verdict = _grade_sample(img, iw, ih, s)
        crops_used += min(len(s.glyph_rects) or 1, 40)
        if verdict is not None:
            issues.append(verdict)
    return issues


def _halo_dependent(s: ContrastSample) -> Issue:
    snip = _snippet(s.text)
    return Issue.make(
        IssueKind.CONTRAST, Severity.WARNING,
        f"Text '{snip}' is only legible thanks to its text-shadow halo; the fill itself is below "
        "the AA bar against the backdrop. Verify it reads clearly, or give it a scrim.",
        bbox=s.bbox, bbox_precise=True, source=IssueSource.CV, confidence=Confidence.MEDIUM,
        detail={"selector": s.selector, "method": "halo-dependent"},
    )


def _overlay_paints(img, r, rgba, iw: int, ih: int, fg_rgba=None) -> bool:
    """The pixels confirm an overlay of colour ``rgba`` (alpha-composited over whatever is
    behind it) covers >= 60% of the line, and the text's own composited colour is essentially
    absent there. Geometry (that the overlay paints at those points) is proven in the page."""
    import numpy as np

    x0, y0 = max(0, int(r.x)), max(0, int(r.y))
    x1, y1 = min(iw, int(r.x + r.width)), min(ih, int(r.y + r.height))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return False
    px = np.asarray(img.crop((x0, y0, x1, y1))).reshape(-1, 3).astype(float)
    c, a = np.array(rgba[:3]), float(rgba[3])
    if a >= 0.98:
        is_cover = np.sqrt(((px - c) ** 2).sum(-1)) < 24
    else:
        # p = a*c + (1-a)*q for some backdrop q in [0, 255]: solve for q and check its range.
        q = (px - a * c) / (1.0 - a)
        is_cover = ((q >= -20) & (q <= 275)).all(-1)
    if float(is_cover.mean()) < 0.6:
        return False
    if fg_rgba is not None:
        # The text, if it were visible here, would paint as its colour composited over the
        # local backdrop; covered text leaves (almost) none of that.
        med = np.median(px, 0)
        fa = float(fg_rgba[3])
        text_px = np.array(fg_rgba[:3]) * fa + med * (1 - fa)
        if float(np.sqrt(((text_px - med) ** 2).sum())) >= 30:
            if float((np.sqrt(((px - text_px) ** 2).sum(-1)) < 30).mean()) >= 0.02:
                return False
    return True


def _grade_sample(img, iw: int, ih: int, s: ContrastSample) -> Issue | None:
    # Grade the GLYPHS line by line, not the element box: a wide/tall container must not push
    # in-frame text out of grading, and a child's ink, an underline or an icon elsewhere in
    # the element must not stand in for this text's own ink.
    rects = s.glyph_rects or [s.glyph_bbox or s.bbox]
    # A line a painted fixed/sticky overlay sits on top of (hit-test confirmed in the page:
    # cookie banner, sticky bar) shows the overlay, not the text: left to the overlap check.
    if s.covered_lines and s.glyph_rects and not s.in_overlay:
        # Confirm each "covered" line in the pixels: the overlay's own colour must dominate
        # the line box. Hit-testable things that paint nothing (a transparent child, a mask,
        # a transparent border) leave the page's pixels, so those lines are graded normally.
        colors = dict(zip(s.covered_lines, s.cover_colors, strict=False))
        skip = {k for k in s.covered_lines
                if k < len(s.glyph_rects) and k in colors
                and _overlay_paints(img, s.glyph_rects[k], colors[k], iw, ih, s.fg_rgba)}
        covered = [r for k, r in enumerate(s.glyph_rects) if k in skip]
        rects = [r for k, r in enumerate(s.glyph_rects) if k not in skip]
        # Never a silent skip: grade the covered lines too, and if they would fail, report
        # an overlap WARNING (a real banner covers text; a fake "overlay" can't hide a defect).
        if covered:
            hidden = _grade_sample(img, iw, ih, s.model_copy(
                update={"glyph_rects": covered, "covered_lines": []}))
            if hidden is not None and hidden.severity in (Severity.ERROR, Severity.CRITICAL):
                if not rects:
                    return _covered(s, None, None)
                rest = _grade_sample(img, iw, ih, s.model_copy(
                    update={"glyph_rects": rects, "covered_lines": []}))
                return rest if rest is not None else _covered(s, None, None)
        if not rects:
            return None
    effect_only = s.passes_aa and s.paint_effects
    # Plain colours passing on computed style: only the backdrop is unknown, so grade the exact
    # painted colour against the real pixels (no anti-aliasing noise).
    fg_rgba = s.fg_rgba
    plain_pass = s.passes_aa and not s.paint_effects and fg_rgba is not None
    if effect_only and s.visible_frac < 0.5:
        return None  # clipped away on purpose (an off-screen carousel slide): nothing shown
    measured: list[tuple[float, float, tuple, tuple]] = []
    crops: list = []
    blank_crops: list = []
    tiny: list = []
    for r in rects:
        fw = (min(iw, r.x + r.width) - max(0.0, r.x)) / max(1.0, r.width)
        fh = (min(ih, r.y + r.height) - max(0.0, r.y)) / max(1.0, r.height)
        # Less than half of the line inside the capture (a slice at the fold): out of frame.
        if fw < 0.5 or fh < 0.5:
            continue
        crop = _crop(img, r)
        if crop is None:
            tiny.append(r)  # in frame but too small to measure on its own
            continue
        crops.append(crop)
        got = worst_case_contrast(crop)
        if got is not None:
            measured.append(got)
        else:
            blank_crops.append(crop)

    # A halo is never a free pass: text that only reads thanks to a text-shadow halo is graded
    # as if the halo weren't there, and a would-be ERROR becomes a WARNING asking for a human
    # check when the halo is visibly painted (a fake or faint halo changes nothing).
    in_frame_rects = [r for r in rects
                      if (min(iw, r.x + r.width) - max(0.0, r.x)) >= 0.5 * max(1.0, r.width)
                      and (min(ih, r.y + r.height) - max(0.0, r.y)) >= 0.5 * max(1.0, r.height)]
    if s.halo and fg_rgba is not None and in_frame_rects and all(
            halo_painted(img, r, fg_rgba[:3], _AA_LARGE if s.large_text else _AA)
            for r in in_frame_rects):
        plain = _grade_sample(img, iw, ih, s.model_copy(update={"halo": False}))
        if plain is not None and plain.severity in (Severity.ERROR, Severity.CRITICAL):
            return _halo_dependent(s)
        return plain

    if not crops:
        if not tiny:
            # Off the captured viewport: nothing to judge.
            return None if (effect_only or plain_pass) else _advisory(s)
        # Tiny glyphs: judge the text colour against the LOCAL pixels around them, not an
        # assumed white page (light "||" on a dark gradient is visible).
        if fg_rgba is not None and not s.paint_effects:
            # Backdrop from pixels INSIDE each tiny glyph box only (a dark frame around the
            # text must not stand in for its backdrop). Every tiny line must clear the bar.
            locals_ = [_local_mean(img, r, iw, ih, pad=0) for r in tiny]
            if locals_ and all(m is not None and contrast_ratio(_over(fg_rgba, m), m) >= _FAIL
                               for m in locals_):
                return None
        if effect_only or plain_pass:
            return None
        return _no_ink(s) if s.ratio < _NO_INK_FAIL else _advisory(s)

    # Some (or all) in-frame lines show no ink: each blank line is evidence on its own.
    if blank_crops:
        if fg_rgba is not None and not s.paint_effects:
            if any(contrast_ratio(_over(fg_rgba, _mean(c)), _mean(c)) < 1.5 for c in blank_crops):
                return _no_ink(s)
            if not measured:
                # No ink anywhere, yet the text colour differs from what is there: something
                # covers it. Covered text is an overlap condition (cookie banners, paywall
                # fades, modals do this by design), reported as a WARNING. Sparse glyphs
                # ("--", "||") are left alone.
                if len("".join(s.text.split())) >= 4:
                    return _covered(s, None, None)
                return None
        elif s.ratio < _NO_INK_FAIL or s.paint_effects:
            return _no_ink(s)
        elif not measured:
            return _advisory(s)

    if plain_pass and fg_rgba is not None:
        exact = [e for e in (exact_fg_contrast(c, fg_rgba[:3], fg_rgba[3]) for c in crops)
                 if e is not None]
        if not exact:
            return None
        ratio = min(exact)
        if ratio < _FAIL:
            return _plain_fail(s, ratio)
        # Declared readable against the real backdrop, yet the ink actually in the pixels is
        # ~invisible: covered or not painted as declared (a near-opaque overlay).
        painted = min(m[0] for m in measured) if measured else 0.0
        if painted < _NOT_PAINTED:
            return _covered(s, painted, ratio)
        return None

    if (s.halo or s.shadow_only) and fg_rgba is not None:
        # Only a text-shadow repaints this text, so its fill colour is exact. Any halo was not
        # visibly painted (checked above): grade the fill against the real backdrop, so a
        # backdrop texture or stripe can't stand in as "ink".
        ratio = min(min(m[0], contrast_ratio(_over(fg_rgba, m[3]), m[3])) for m in measured)
    else:
        ratio = min(_line_ratio(s, m) for m in measured)
    need = _AA_LARGE if s.large_text else _AA
    if ratio >= need:
        # Measured readable over the worst patch — the computed-style guess was a false alarm.
        return None
    if effect_only and ratio >= _EFFECT_FAIL:
        # Anti-aliased small text measures well below its true ratio (#666 at 11px reads
        # ~2.8:1), so an effect sample that passes on computed style is flagged only when the
        # paint truly destroyed it (opacity:.1, brightness(6) measure ~1.0-1.5).
        return None
    fail = ratio < _FAIL
    snip = _snippet(s.text)
    return Issue.make(
        IssueKind.CONTRAST,
        Severity.ERROR if fail else Severity.WARNING,
        f"Unreadable text over a non-solid background — measured worst-case contrast "
        f"~{ratio:.1f}:1 (WCAG AA needs {need:.1f}) on '{snip}'. Give the element an opaque "
        f"background or a text halo/outline so it's legible over the varying backdrop.",
        bbox=s.bbox, bbox_precise=True, source=IssueSource.CV,
        confidence=Confidence.MEDIUM if fail else Confidence.LOW,
        detail={"measured_ratio": round(ratio, 2), "declared_ratio": s.ratio, "fg": s.fg,
                "selector": s.selector, "method": "pixel-worst-case",
                "large_text": s.large_text, "wcag": "1.4.3"},
    )


# Bounded work for the pixel pass (an attacker-shaped page must not stall grading).
_MAX_SAMPLES = 1500
_MAX_CROPS = 4000
_BUDGET_S = 15.0


def _any_in_frame(s: ContrastSample, iw: int, ih: int) -> bool:
    for r in s.glyph_rects or [s.glyph_bbox or s.bbox]:
        if r.x < iw and r.y < ih and r.x + r.width > 0 and r.y + r.height > 0:
            return True
    return False


def _budget_exceeded(skipped: int) -> Issue:
    return Issue.make(
        IssueKind.OTHER, Severity.ERROR,
        f"Pixel contrast checks hit their limit on this page; {skipped} text element(s) were "
        "not graded against the rendered pixels.",
        source=IssueSource.CV, confidence=Confidence.HIGH,
        detail={"pixel_contrast_truncated": True, "skipped": skipped},
    )


def _over(fg_rgba, bg) -> tuple:
    r0, g0, b0, a0 = fg_rgba
    return (r0 * a0 + bg[0] * (1 - a0), g0 * a0 + bg[1] * (1 - a0), b0 * a0 + bg[2] * (1 - a0))


def _local_mean(img, r, iw: int, ih: int, pad: int = 6):
    x0, y0 = max(0, int(r.x) - pad), max(0, int(r.y) - pad)
    x1, y1 = min(iw, int(r.x + r.width) + pad), min(ih, int(r.y + r.height) + pad)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return _mean(img.crop((x0, y0, x1, y1)))
