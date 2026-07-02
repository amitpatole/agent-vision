"""Legibility of text painted *into* a ``<canvas>`` — the case with no DOM node at all.

Phase 2 ([`check_contrast_pixel`](contrast_pixel.py)) grades a DOM element sitting *over* a
canvas. But a chart/map library often paints its labels **directly onto the canvas bitmap**
(axis ticks, legend entries, a metric baked into a heat tile) — there is no DOM element, so no
computed-style sample is ever emitted and the text is invisible to every DOM check. OCR is the
only handle on it.

This check reads OCR words that fall **inside a canvas region** and are **not backed by any DOM
text** (so they must be painted-in), measures their real pixel contrast (worst-case sampling),
and flags the clearly-unreadable ones. Grounding is honest and lower-actionability by design:
there is no selector to hand the agent — the fix lives at the chart/colormap layer — so these
are emitted at **warning** severity with **low** confidence (the OCR localisation is the
uncertain part), never a hard fail, and OCR word-confidence is recorded as *evidence only*, not
a verdict input.
"""

from __future__ import annotations

from pathlib import Path

from ...logging import get_logger
from ...models.geometry import BBox
from ...models.report import Confidence, Issue, IssueKind, IssueSource, Severity
from ...ocr.base import OcrResult, OcrWord
from ...renderers.base import RenderResult
from ._pixel_contrast import crop_bbox, worst_case_contrast

log = get_logger("contrast_ocr")

_FAIL = 3.0          # only flag clearly-unreadable painted text (conservative — OCR is noisy)
_MIN_OCR_CONF = 0.5  # ignore low-confidence OCR (likely mis-detected texture, not text)
_MIN_LEN = 2         # ignore single-glyph noise
_MAX_ISSUES = 5      # cap output so a busy canvas can't flood the report


def _overlaps(a: BBox, b: BBox) -> bool:
    ix = min(a.x + a.width, b.x + b.width) - max(a.x, b.x)
    iy = min(a.y + a.height, b.y + b.height) - max(a.y, b.y)
    return ix > 0 and iy > 0


def _center_inside(word: BBox, region: BBox) -> bool:
    cx, cy = word.x + word.width / 2, word.y + word.height / 2
    return (region.x <= cx <= region.x + region.width
            and region.y <= cy <= region.y + region.height)


def _is_painted_in(word: OcrWord, canvases: list[BBox], dom_boxes) -> bool:
    """True when the word sits inside a canvas region and no DOM text box covers it."""
    if not any(_center_inside(word.bbox, c) for c in canvases):
        return False
    return not any(getattr(b, "text", "") and _overlaps(word.bbox, b.bbox) for b in dom_boxes)


def check_contrast_ocr(
    render: RenderResult, image_path: str | Path | None, ocr: OcrResult | None
) -> list[Issue]:
    """Flag unreadable text painted into a ``<canvas>`` (no DOM handle) via OCR + pixels."""
    if ocr is None or not ocr.words or not image_path:
        return []
    canvases = [e.bbox for e in render.visual_elements if e.tag == "canvas"]
    if not canvases:
        return []
    candidates = [
        w for w in ocr.words
        if w.confidence >= _MIN_OCR_CONF and len(w.text.strip()) >= _MIN_LEN
        and _is_painted_in(w, canvases, render.dom_boxes)
    ]
    if not candidates:
        return []
    try:
        from PIL import Image

        img = Image.open(image_path).convert("RGB")
    except Exception as e:  # noqa: BLE001 — no image → nothing to measure
        log.debug("ocr contrast: cannot open %s: %s", image_path, e)
        return []

    graded: list[tuple[float, OcrWord]] = []
    for w in candidates:
        crop = crop_bbox(img, w.bbox)
        res = worst_case_contrast(crop) if crop is not None else None
        if res is not None and res[0] < _FAIL:
            graded.append((res[0], w))
    graded.sort(key=lambda t: t[0])  # worst first
    issues: list[Issue] = []
    for ratio, w in graded[:_MAX_ISSUES]:
        snip = (w.text[:40] + "…") if len(w.text) > 40 else w.text
        issues.append(Issue.make(
            IssueKind.CONTRAST, Severity.WARNING,
            f"Text painted into a <canvas> is hard to read — measured worst-case contrast "
            f"~{ratio:.1f}:1 on '{snip}'. There's no DOM element to restyle; fix it at the "
            f"chart/colormap layer (higher-contrast palette, a label background, or a halo).",
            bbox=w.bbox, bbox_precise=True, source=IssueSource.OCR, confidence=Confidence.LOW,
            detail={"measured_ratio": round(ratio, 2), "ocr_confidence": round(w.confidence, 2),
                    "method": "ocr+pixel-worst-case", "no_dom_handle": True, "wcag": "1.4.3"},
        ))
    return issues
