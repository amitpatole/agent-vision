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

from pathlib import Path

from ...logging import get_logger
from ...models.report import Confidence, Issue, IssueKind, IssueSource, Severity
from ...renderers.base import ContrastSample, RenderResult
from ._pixel_contrast import worst_case_contrast

log = get_logger("contrast_pixel")

_FAIL = 3.0   # clearly unreadable
_AA = 4.5     # AA minimum for normal text
_AA_LARGE = 3.0  # AA minimum for large text


def _snippet(text: str) -> str:
    return (text[:40] + "…") if len(text) > 40 else text


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


def check_contrast_pixel(render: RenderResult, image_path: str | Path | None) -> list[Issue]:
    """Grade every failing low-confidence DOM contrast sample against the real pixels."""
    lows = [s for s in render.contrast_samples
            if s.confidence == "low" and not s.passes_aa]
    if not lows:
        return []
    img = _open(image_path)
    if img is None:
        return [_advisory(s) for s in lows]

    issues: list[Issue] = []
    for s in lows:
        crop = _crop(img, s.bbox)
        res = worst_case_contrast(crop) if crop is not None else None
        if res is None:
            issues.append(_advisory(s))  # couldn't read text pixels — stay honest
            continue
        ratio, _frac, _ink, _bg = res
        need = _AA_LARGE if s.large_text else _AA
        if ratio >= need:
            # Measured readable over the worst patch — the computed-style guess was a false
            # alarm (e.g. light text that actually sits over a dark region). Drop it.
            continue
        fail = ratio < _FAIL
        snip = _snippet(s.text)
        issues.append(Issue.make(
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
        ))
    return issues
