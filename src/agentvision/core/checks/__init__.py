"""Classic checks (no LLM): contrast, overflow, broken images, console, blank.

These produce coordinate-grounded :class:`Issue`s that both stand alone (``agentvision
check``) and ground the vision backend (fed as ``dom_hints``).
"""

from __future__ import annotations

from pathlib import Path

from ...models.report import Issue
from ...ocr.base import OcrResult
from ...renderers.base import RenderResult
from .contrast import check_contrast_dom
from .layout import (
    check_blank,
    check_broken_images,
    check_clipped_text,
    check_console,
    check_overflow,
    run_structural_checks,
)
from .spelling import check_spelling_from_ocr

# IssueKinds the classic-checks layer (and thus the local backend) can emit.
CLASSIC_CAPABILITIES = [
    "contrast", "overflow", "clipped", "broken_image", "error_text", "typo", "blank", "other",
]


def run_all_checks(
    render: RenderResult, image_path: str | Path | None, ocr: OcrResult | None = None
) -> list[Issue]:
    issues: list[Issue] = []
    issues += check_contrast_dom(render)
    issues += run_structural_checks(render, image_path)
    if ocr is not None:
        issues += check_spelling_from_ocr(ocr)
    return issues


__all__ = [
    "run_all_checks", "run_structural_checks", "check_contrast_dom",
    "check_overflow", "check_broken_images", "check_clipped_text", "check_console",
    "check_blank", "check_spelling_from_ocr", "CLASSIC_CAPABILITIES",
]
