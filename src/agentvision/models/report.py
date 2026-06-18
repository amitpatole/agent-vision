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
    OTHER = "other"


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


class Report(BaseModel):
    verdict: Verdict
    summary: str
    issues: list[Issue] = Field(default_factory=list)
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
