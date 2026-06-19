"""Core engine: the reusable logic all adapters wrap."""

from .analyze import analyze, check
from .baseline import regress, set_baseline
from .capture import contact_sheet
from .diff import compute_diff
from .generate import GenerationStep, GenerativeLoopSession
from .render import render
from .watch import watch

# Public alias: agentvision.diff(baseline, candidate)
diff = compute_diff

__all__ = [
    "render", "analyze", "check", "diff", "compute_diff",
    "contact_sheet", "set_baseline", "regress", "watch",
    "GenerativeLoopSession", "GenerationStep",
]
