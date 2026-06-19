"""The Report contract.

This is the internal data model every adapter and backend depends on. It is kept strict-
schema-safe (no free-form dicts — ``detail`` is a JSON string; closed enums; no recursive
models) so the same model can be emitted to Anthropic/OpenAI/Gemini via per-provider
schema adapters.
"""

from __future__ import annotations

import json
from enum import Enum

from pydantic import BaseModel, Field

from .geometry import BBox, Viewport


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


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


class Importance(str, Enum):
    """How much a requirement matters to conformance.

    ``must`` violations fail the verdict; ``should`` warns; ``nice`` never escalates.
    """

    MUST = "must"
    SHOULD = "should"
    NICE = "nice"


class ClaimStatus(str, Enum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNCERTAIN = "uncertain"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IssueSource(str, Enum):
    VISION = "vision"  # from the vision LLM (advisory bbox)
    OCR = "ocr"  # from OCR word boxes (precise bbox)
    CV = "cv"  # from classic computer vision
    DOM = "dom"  # from DOM geometry / computed style (precise bbox)


class Verdict(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class Issue(BaseModel):
    kind: IssueKind
    severity: Severity
    message: str = Field(description="Human-readable, agent-actionable description.")
    bbox: BBox | None = Field(default=None, description="Location in IMAGE pixels, if known.")
    bbox_precise: bool = Field(
        default=False,
        description="True only for DOM/OCR/CV-grounded boxes. Vision-model boxes are advisory.",
    )
    confidence: Confidence = Confidence.MEDIUM
    source: IssueSource = IssueSource.VISION
    detail_json: str = Field(default="{}", description="Extra structured detail as a JSON string.")

    @property
    def detail(self) -> dict:
        try:
            return json.loads(self.detail_json)
        except (json.JSONDecodeError, TypeError):
            return {}

    @classmethod
    def make(cls, kind: IssueKind, severity: Severity, message: str, *,
             bbox: BBox | None = None, bbox_precise: bool = False,
             confidence: Confidence = Confidence.MEDIUM,
             source: IssueSource = IssueSource.VISION, detail: dict | None = None) -> Issue:
        return cls(
            kind=kind, severity=severity, message=message, bbox=bbox,
            bbox_precise=bbox_precise, confidence=confidence, source=source,
            detail_json=json.dumps(detail or {}),
        )


class ClaimResult(BaseModel):
    """One requirement (a piece of *the thought*) graded against the render."""

    text: str = Field(description="The requirement, as a checkable visual claim.")
    importance: Importance = Importance.MUST
    status: ClaimStatus = ClaimStatus.UNCERTAIN
    confidence: Confidence = Confidence.MEDIUM
    evidence: str = Field(default="", description="Why we judged it satisfied/violated.")
    source: IssueSource = IssueSource.VISION


class Conformance(BaseModel):
    """How well the render matches the intended product (the brief / checklist)."""

    claims: list[ClaimResult] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.claims)

    @property
    def satisfied(self) -> int:
        return sum(1 for c in self.claims if c.status == ClaimStatus.SATISFIED)

    @property
    def violated(self) -> list[ClaimResult]:
        return [c for c in self.claims if c.status == ClaimStatus.VIOLATED]

    @property
    def score(self) -> float:
        """Fraction of claims satisfied (0..1); 1.0 when there are no claims."""
        return 1.0 if not self.claims else self.satisfied / self.total

    def matches_intent(self) -> bool:
        """True only when no ``must`` requirement is violated or left uncertain."""
        return not any(
            c.importance == Importance.MUST and c.status != ClaimStatus.SATISFIED
            for c in self.claims
        )


class Report(BaseModel):
    verdict: Verdict
    summary: str
    issues: list[Issue] = Field(default_factory=list)
    conformance: Conformance | None = Field(
        default=None,
        description="Per-requirement grading vs the intended product, when a brief is given.",
    )
    capabilities: list[IssueKind] = Field(
        default_factory=list,
        description="Which IssueKinds the producing backend is able to emit.",
    )
    backend: str = "unknown"
    model: str | None = None
    viewport: Viewport = Field(default_factory=Viewport)
    device_scale: float = 1.0
    image_path: str | None = Field(
        default=None, description="Server-relative artifact id/path; adapters project it."
    )
    elapsed_ms: int = 0
    schema_version: str = "1.0"

    def is_ok(self) -> bool:
        return self.verdict == Verdict.PASS

    def to_handoff(self):
        """Distill this Report into a :class:`~agentvision.models.handoff.Handoff`.

        The afferent signal an agent's reasoning/memory layer ("the brain") acts on.
        """
        from .handoff import Handoff

        return Handoff.from_report(self)

    def issue_signature(self) -> frozenset[tuple[str, str]]:
        """Identity of the issue *set* — used for loop progress/stuck detection.

        Deliberately ignores bbox/severity drift; two iterations are "the same" if they
        flag the same (kind, message) pairs.
        """
        return frozenset((i.kind.value, i.message.strip().lower()) for i in self.issues)


def verdict_from_issues(issues: list[Issue]) -> Verdict:
    """Derive an overall verdict from issue severities.

    CRITICAL/ERROR -> FAIL; WARNING -> WARN; otherwise PASS. Low-confidence issues never
    escalate past WARN on their own.
    """
    has_fail = False
    has_warn = False
    for i in issues:
        if i.severity in (Severity.CRITICAL, Severity.ERROR):
            if i.confidence == Confidence.LOW:
                has_warn = True
            else:
                has_fail = True
        elif i.severity == Severity.WARNING:
            has_warn = True
    if has_fail:
        return Verdict.FAIL
    if has_warn:
        return Verdict.WARN
    return Verdict.PASS
