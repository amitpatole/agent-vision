"""The Report contract (vision).

Built on the shared :mod:`agentsensory` contract: the neutral vocabulary, conformance, intent and
handoff live there; this module adds the *vision* specialisation — the closed ``IssueKind`` /
``IssueSource`` enums and the ``Issue`` / ``Report`` subclasses that re-declare ``kind``/``source``
as those enums (so every ``i.kind.value`` and ``schema_adapters`` enum reflection keeps working).

Kept strict-schema-safe (no free-form dicts — ``detail`` is a JSON string; closed enums; no
recursive models) so the same model can be emitted to Anthropic/OpenAI/Gemini via per-provider
schema adapters.
"""

from __future__ import annotations

from enum import Enum

# Re-export the shared vocabulary so existing ``from .report import X`` imports keep resolving.
from agentsensory import (
    ClaimResult,
    ClaimStatus,
    Confidence,
    Conformance,
    Importance,
    IssueBase,
    ReportBase,
    Severity,
    Verdict,
    verdict_from_issues,
)
from pydantic import Field

from .geometry import Viewport

__all__ = [
    "Severity", "IssueKind", "Importance", "ClaimStatus", "Confidence", "IssueSource",
    "Verdict", "Issue", "ClaimResult", "Conformance", "Report", "verdict_from_issues",
]


class IssueKind(str, Enum):
    LAYOUT = "layout"
    OVERFLOW = "overflow"
    CLIPPED = "clipped"
    CONTRAST = "contrast"
    MISSING_ELEMENT = "missing_element"
    BROKEN_IMAGE = "broken_image"
    OVERLAP = "overlap"
    BLANK = "blank"
    ERROR_TEXT = "error_text"
    TYPO = "typo"
    INTENT_MISMATCH = "intent_mismatch"
    OTHER = "other"


class IssueSource(str, Enum):
    VISION = "vision"  # from the vision LLM (advisory bbox)
    OCR = "ocr"  # from OCR word boxes (precise bbox)
    CV = "cv"  # from classic computer vision
    DOM = "dom"  # from DOM geometry / computed style (precise bbox)


class Issue(IssueBase):
    """A vision issue: ``kind``/``source`` narrowed to the closed vision enums."""

    kind: IssueKind
    source: IssueSource = IssueSource.VISION


class Report(ReportBase):
    """A vision report: shared fields + the render-specific surface."""

    # Narrow the shared list[IssueBase] to the vision Issue. mypy flags the invariant-list
    # override; it is safe here (Issue <: IssueBase, and pydantic validates on assignment).
    issues: list[Issue] = Field(default_factory=list)  # type: ignore[assignment]
    conformance: Conformance | None = Field(
        default=None,
        description="Per-requirement grading vs the intended product, when a brief is given.",
    )
    capabilities: list[IssueKind] = Field(
        default_factory=list,
        description="Which IssueKinds the producing backend is able to emit.",
    )
    viewport: Viewport = Field(default_factory=Viewport)
    device_scale: float = 1.0
    image_path: str | None = Field(
        default=None, description="Server-relative artifact id/path; adapters project it."
    )
