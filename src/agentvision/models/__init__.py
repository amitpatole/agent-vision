"""AgentVision data models (pure Pydantic)."""

from .diff import DiffRegion, DiffResult
from .geometry import BBox, Size, Viewport
from .handoff import Handoff, NextAction
from .intent import Brief, IntentClaim
from .report import (
    ClaimResult,
    ClaimStatus,
    Confidence,
    Conformance,
    Importance,
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
    "Importance", "ClaimStatus", "ClaimResult", "Conformance",
    "Brief", "IntentClaim",
    "Handoff", "NextAction",
    "DiffRegion", "DiffResult",
]
