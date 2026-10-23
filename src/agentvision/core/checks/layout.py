"""Layout/structural checks: horizontal overflow, broken images, console/network errors,
and blank renders."""

from __future__ import annotations

from pathlib import Path

from ...models.report import Confidence, Issue, IssueKind, IssueSource, Severity
from ...renderers.base import RenderResult

_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico")


def check_overflow(render: RenderResult) -> list[Issue]:
    if render.overflow_x > 2:
        return [Issue.make(
            IssueKind.OVERFLOW, Severity.ERROR,
            f"Page content overflows horizontally by {render.overflow_x:.0f}px "
            "(causes a horizontal scrollbar).",
            source=IssueSource.DOM, confidence=Confidence.HIGH,
            detail={"overflow_x_px": render.overflow_x},
        )]
    return []


def check_broken_images(render: RenderResult) -> list[Issue]:
    issues: list[Issue] = []
    for el in render.broken_images:
        issues.append(Issue.make(
            IssueKind.BROKEN_IMAGE, Severity.ERROR,
            f"Broken image (failed to load): {el.text or el.selector}",
            bbox=el.bbox, bbox_precise=True, source=IssueSource.DOM,
            confidence=Confidence.HIGH, detail={"src": el.text, "selector": el.selector},
        ))
    seen = {i.detail.get("src") for i in issues}
    for f in render.failed_responses:
        if f.url in seen:
            continue
        is_img = f.url.lower().split("?")[0].endswith(_IMAGE_EXT)
        kind = IssueKind.BROKEN_IMAGE if is_img else IssueKind.OTHER
        sev = Severity.ERROR if is_img else Severity.WARNING
        status = f" (HTTP {f.status})" if f.status else f" ({f.reason})"
        issues.append(Issue.make(
            kind, sev, f"Failed request{status}: {f.url}",
            source=IssueSource.CV, confidence=Confidence.HIGH,
            detail={"url": f.url, "status": f.status, "reason": f.reason},
        ))
    return issues


def check_clipped_text(render: RenderResult) -> list[Issue]:
    """Flag text cut off by a clip boundary — an SVG viewport (high confidence) or a DOM
    container's hard overflow with no ellipsis (advisory). Both DOM-grounded, no LLM."""
    issues: list[Issue] = []
    for el in render.clipped_text:
        if el.kind == "svg_clipped":
            msg = (f"Text clipped by its SVG viewport: {el.text!r} extends ~{el.overflow_px:.0f}px "
                   "beyond the chart bounds and is cut off.")
            sev, conf = Severity.ERROR, Confidence.HIGH
        elif el.kind == "container_clipped":
            msg = (f"Text cut off by a clipping container: {el.text!r} extends "
                   f"~{el.overflow_px:.0f}px past an overflow:hidden box and is partly hidden.")
            sev, conf = Severity.WARNING, Confidence.MEDIUM
        else:
            msg = (f"Text truncated by its container: {el.text!r} overflows its box by "
                   f"~{el.overflow_px:.0f}px under a hard clip (no ellipsis).")
            sev, conf = Severity.WARNING, Confidence.MEDIUM
        issues.append(Issue.make(
            IssueKind.CLIPPED, sev, msg,
            bbox=el.bbox, bbox_precise=True, source=IssueSource.DOM, confidence=conf,
            detail={"text": el.text, "selector": el.selector, "kind": el.kind,
                    "overflow_px": el.overflow_px},
        ))
    return issues


# Painted font size (CSS px): computed font-size x transform scale x zoom, capped by the line
# box. ~8px and below is unreadable; under ~9.5px is hard to read. (Chromium line boxes: 9px
# text -> 10px tall, 12px -> 14px.)
_TINY_ERROR_PX = 8.5
_TINY_WARN_PX = 9.5


def _tiny_issue(text: str, px: float, bbox, selector: str, *, cap_warning: bool = False) -> Issue:
    snip = (text[:40] + "…") if len(text) > 40 else text
    err = px < _TINY_ERROR_PX and not cap_warning
    return Issue.make(
        IssueKind.LAYOUT, Severity.ERROR if err else Severity.WARNING,
        f"Text too small to read: '{snip}' is painted at about {px:.1f}px "
        f"({'unreadable' if err else 'hard to read'}; typos in it also escape OCR).",
        bbox=bbox, bbox_precise=True, source=IssueSource.DOM,
        confidence=Confidence.HIGH if err else Confidence.MEDIUM,
        detail={"font_px": round(px, 1), "selector": selector, "text": text[:80]},
    )


def check_text_size(render: RenderResult) -> list[Issue]:
    """Visible text painted too small to read. Tiny text also escapes OCR (so typos in it go
    unseen), so it is reported on its own rather than silently passing. Ruby annotations
    (pinyin, furigana) are small by design and skipped; disabled controls are NOT exempt
    (WCAG exempts their contrast, not their size)."""
    issues: list[Issue] = []
    fragments: dict[int, list] = {}
    markers: dict[int, list] = {}
    for s in render.contrast_samples:
        if len(issues) >= 20:
            break
        px = s.eff_font_px or (s.min_line_h / 1.15 if s.min_line_h else 0.0)
        if px <= 0 or px >= _TINY_WARN_PX or s.visible_frac < 0.5 or s.in_ruby:
            continue
        nchars = len("".join(s.text.split()))
        if s.sup_sub and nchars <= 4:
            # A footnote/reference marker: small by design. Pooled per block, so a sentence
            # chunked into markers is still text (> 3 markers or >= 8 chars -> graded fully).
            markers.setdefault(s.block_key, []).append((s, px))
            continue
        if nchars < 3:
            # Pool short fragments of one text block (on either axis): text split into 2-char
            # spans is still text.
            fragments.setdefault(s.block_key or int(s.bbox.y // 12), []).append((s, px))
            continue
        issues.append(_tiny_issue(s.text, px, s.bbox, s.selector))
    for group in markers.values():
        if len(issues) >= 20:
            break
        chars = sum(len("".join(s.text.split())) for s, _ in group)
        many = len(group) > 3 or chars >= 8
        s0, px0 = min(group, key=lambda g: g[1])
        text = " ".join(s.text for s, _ in group) if many else s0.text
        issues.append(_tiny_issue(text, px0, s0.bbox, s0.selector, cap_warning=not many))
    for group in fragments.values():
        if len(issues) >= 20:
            break
        chars = sum(len("".join(s.text.split())) for s, _ in group)
        if chars >= 6:
            s0, px0 = min(group, key=lambda g: g[1])
            joined = "".join(s.text for s, _ in group)
            issues.append(_tiny_issue(joined, px0, s0.bbox, s0.selector))
    for f in render.form_fields:
        if len(issues) >= 20:
            break
        px = float(f.get("eff_font_px") or 0)
        if 0 < px < _TINY_WARN_PX:
            issues.append(_tiny_issue(f["text"], px, f["bbox"], f.get("selector", "")))
    return issues


def check_overlap(render: RenderResult) -> list[Issue]:
    """Text covered by a positioned element (hit-test confirmed in the DOM). Advisory: a
    deliberate overlay over text exists, but over a headline it is usually a defect."""
    return [
        Issue.make(
            IssueKind.OVERLAP, Severity.WARNING,
            f"Text {o.text!r} is covered by {o.selector or 'a positioned element'} "
            f"({o.bbox.width:.0f}x{o.bbox.height:.0f}px overlap).",
            bbox=o.bbox, bbox_precise=True, source=IssueSource.DOM,
            confidence=Confidence.MEDIUM,
            detail={"text": o.text, "occluder": o.selector, "tag": o.tag},
        )
        for o in render.overlaps
    ]


def check_error_text(render: RenderResult) -> list[Issue]:
    """Visible error copy rendered to the user (a playback error, 'Something went wrong',
    a raw '[object Object]'). Narrow patterns; warning severity."""
    return [
        Issue.make(
            IssueKind.ERROR_TEXT, Severity.WARNING,
            f"Visible error message on the page: {e.text!r}",
            bbox=e.bbox, bbox_precise=True, source=IssueSource.DOM,
            confidence=Confidence.MEDIUM, detail={"text": e.text, "selector": e.selector},
        )
        for e in render.error_text
    ]


def check_console(render: RenderResult) -> list[Issue]:
    issues: list[Issue] = []
    for c in render.console_errors:
        sev = Severity.ERROR if c.kind == "pageerror" else Severity.WARNING
        issues.append(Issue.make(
            IssueKind.ERROR_TEXT, sev,
            f"JavaScript {c.kind}: {c.text[:160]}",
            source=IssueSource.CV, confidence=Confidence.HIGH,
            detail={"kind": c.kind},
        ))
    return issues


def check_blank(image_path: str) -> list[Issue]:
    """Detect an effectively-blank render (near-uniform pixels)."""
    import numpy as np
    from PIL import Image

    try:
        with Image.open(image_path) as im:
            arr = np.asarray(im.convert("RGB"), dtype="float32")
    except Exception:  # noqa: BLE001
        return []
    if arr.size == 0:
        return [Issue.make(IssueKind.BLANK, Severity.CRITICAL, "Render produced no pixels.",
                           source=IssueSource.CV, confidence=Confidence.HIGH)]
    std = float(arr.std())
    if std < 2.0:
        return [Issue.make(
            IssueKind.BLANK, Severity.CRITICAL,
            f"Render appears blank/uniform (pixel std={std:.2f}). "
            "Likely a failed render or empty page.",
            source=IssueSource.CV, confidence=Confidence.HIGH,
            detail={"pixel_std": std},
        )]
    return []


def check_extraction(render: RenderResult) -> list[Issue]:
    """The DOM grading pass itself failed or was cut short. Never let that read as clean.

    Both are ERRORs: a failed extraction skipped every DOM check, and a truncated one (time
    budget or element cap hit) left some elements unchecked. Gate mode passes WARN, so a
    page that can force truncation must not be able to turn its own defects into a warning.
    """
    issues: list[Issue] = []
    if render.extraction_error:
        issues.append(Issue.make(
            IssueKind.OTHER, Severity.ERROR,
            "DOM checks could not run, so contrast, overflow, clipping, overlap, broken-image "
            f"and error-text results are missing: {render.extraction_error}",
            source=IssueSource.DOM, confidence=Confidence.HIGH,
            detail={"extraction_error": render.extraction_error},
        ))
    if render.extraction_truncated:
        issues.append(Issue.make(
            IssueKind.OTHER, Severity.ERROR,
            "DOM checks hit their limit on this page (time budget or element cap), so some "
            "elements were not checked. Raise dom_budget_ms / dom_max_elements if the page is "
            "legitimately this large.",
            source=IssueSource.DOM, confidence=Confidence.HIGH,
            detail={"extraction_truncated": True},
        ))
    return issues


def run_structural_checks(render: RenderResult, image_path: str | Path | None) -> list[Issue]:
    issues: list[Issue] = []
    issues += check_extraction(render)
    issues += check_overflow(render)
    issues += check_broken_images(render)
    issues += check_clipped_text(render)
    issues += check_overlap(render)
    issues += check_text_size(render)
    issues += check_error_text(render)
    issues += check_console(render)
    if image_path:
        issues += check_blank(str(image_path))
    return issues
