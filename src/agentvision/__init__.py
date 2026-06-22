"""AgentVision — Eyes for AI Agents.

A machine-graded visual feedback loop that coding agents consume to self-correct before
claiming a visual task done: render -> perceive -> report -> (fix) -> re-render -> diff.

The top-level import is dependency-light. Heavy entry points (which pull in Playlist/CV/
LLM SDKs) are exposed lazily via ``__getattr__`` so ``import agentvision`` always works,
even on a bare server.
"""

from __future__ import annotations

from .config import Settings, load_settings
from .errors import (
    AgentVisionError,
    BackendAuthError,
    BackendError,
    ConfigError,
    MissingDependencyError,
    RenderError,
    RenderTimeout,
    UnsafeSourceError,
)
from .models import (
    BBox,
    Brief,
    ClaimResult,
    ClaimStatus,
    Confidence,
    Conformance,
    DiffResult,
    Handoff,
    Importance,
    IntentClaim,
    Issue,
    IssueKind,
    IssueSource,
    NextAction,
    Report,
    Severity,
    Verdict,
    Viewport,
)

__version__ = "0.8.0"

__all__ = [
    "__version__",
    "Settings", "load_settings",
    "AgentVisionError", "MissingDependencyError", "RenderError", "RenderTimeout",
    "UnsafeSourceError", "BackendError", "BackendAuthError", "ConfigError",
    "BBox", "Viewport", "Issue", "IssueKind", "IssueSource", "Severity", "Confidence",
    "Verdict", "Report", "DiffResult",
    "Brief", "IntentClaim", "Importance", "ClaimStatus", "ClaimResult", "Conformance",
    "Handoff", "NextAction",
    # lazy:
    "render", "analyze", "diff", "check", "watch", "LoopSession", "GenerativeLoopSession",
]


def __getattr__(name: str):
    # Lazy high-level API — imported on demand to keep the base import light.
    if name in {"render", "analyze", "diff", "check", "watch"}:
        from . import core

        return getattr(core, name)
    if name == "LoopSession":
        from .core.loop import LoopSession

        return LoopSession
    if name == "GenerativeLoopSession":
        from .core.generate import GenerativeLoopSession

        return GenerativeLoopSession
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
