"""The eyes → brain handoff — AgentVision's *afferent* signal.

Anatomy analogy: the eyes don't decide anything. The retina perceives, the optic nerve
carries the signal to the brain, the brain decides, a motor signal moves the hand, and then
the eyes look again. AgentVision is that afferent pathway for an agent: it perceives the
rendered artifact and hands a structured signal back to *the brain* — whatever does the
reasoning, planning, or memory.

A :class:`~agentvision.models.report.Report` is the full sensory detail. A :class:`Handoff`
is the distilled signal a brain acts on directly: a verdict, a prioritized to-do, the open
questions perception couldn't resolve, and the single recommended next action. It is the
natural unit to feed an agent loop — or to persist into any memory/brain system — without
that system needing to understand AgentVision's internals.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from .report import (
    ClaimStatus,
    Confidence,
    IssueKind,
    Report,
    Severity,
    Verdict,
)

_SEV_RANK = {Severity.CRITICAL: 3, Severity.ERROR: 2, Severity.WARNING: 1, Severity.INFO: 0}


class NextAction(str, Enum):
    """What the brain should do with this signal."""

    DONE = "done"        # perception passed — safe to claim the task complete
    REVISE = "revise"    # real defects / unmet requirements — act on `todo`, then look again
    REVIEW = "review"    # uncertain or minor — needs judgment before continuing


class Handoff(BaseModel):
    """The afferent signal: what the eyes saw, shaped for the brain to act on."""

    perceived: Verdict = Field(description="What perception concluded (pass/warn/fail).")
    next_action: NextAction
    matches_intent: bool | None = Field(
        default=None, description="True/False when a brief was graded; None when no intent given."
    )
    summary: str = ""
    todo: list[str] = Field(
        default_factory=list,
        description="Prioritized, actionable items the brain should resolve (defects + unmet musts).",
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="What perception could NOT decide — the brain should verify these.",
    )
    artifact: str | None = None
    backend: str = "unknown"
    model: str | None = None
    schema_version: str = "1.0"

    @classmethod
    def from_report(cls, report: Report) -> Handoff:
        """Distill a full Report into the actionable signal."""
        conf = report.conformance

        # Defects (non-intent issues) ranked by severity, errors/criticals only in the to-do.
        defects = sorted(
            (i for i in report.issues
             if i.kind != IssueKind.INTENT_MISMATCH
             and i.severity in (Severity.ERROR, Severity.CRITICAL)),
            key=lambda i: _SEV_RANK[i.severity], reverse=True,
        )
        todo = [f"[{i.kind.value}] {i.message}" for i in defects]

        # Unmet requirements (intent), musts before shoulds. Conformance is authoritative.
        if conf:
            unmet = [c for c in conf.claims if c.status == ClaimStatus.VIOLATED]
            unmet.sort(key=lambda c: 0 if c.importance.value == "must" else 1)
            todo += [f"[intent/{c.importance.value}] {c.text}" for c in unmet]

        # Open questions: what perception flagged but couldn't confirm.
        open_q = [f"Verify: {c.text}" for c in (conf.claims if conf else [])
                  if c.status == ClaimStatus.UNCERTAIN]
        open_q += [f"Uncertain: {i.message}" for i in report.issues
                   if i.confidence == Confidence.LOW
                   and i.severity in (Severity.ERROR, Severity.CRITICAL)]

        if report.verdict == Verdict.PASS:
            action = NextAction.DONE
        elif report.verdict == Verdict.FAIL:
            action = NextAction.REVISE
        else:
            action = NextAction.REVIEW

        return cls(
            perceived=report.verdict,
            next_action=action,
            matches_intent=(conf.matches_intent() if conf else None),
            summary=report.summary,
            todo=todo,
            open_questions=open_q,
            artifact=report.image_path,
            backend=report.backend,
            model=report.model,
        )
