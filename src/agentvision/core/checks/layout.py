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


def run_structural_checks(render: RenderResult, image_path: str | Path | None) -> list[Issue]:
    issues: list[Issue] = []
    issues += check_overflow(render)
    issues += check_broken_images(render)
    issues += check_console(render)
    if image_path:
        issues += check_blank(str(image_path))
    return issues
