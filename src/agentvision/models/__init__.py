"""AgentVision data models (pure Pydantic)."""

from .diff import DiffRegion, DiffResult
from .geometry import BBox, Size, Viewport
from .report import (
    Confidence,
    Issue,
    IssueKind,
    IssueSource,
    Report,
    Severity,
    Verdict,
)

__all__ = [
    "BBox", "Size", "Viewport",
    "Confidence", "Issue", "IssueKind", "IssueSource", "Report", "Severity", "Verdict",
    "DiffRegion", "DiffResult",
]
