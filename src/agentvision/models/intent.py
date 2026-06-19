"""The *intent* contract — what the agent set out to build (the thought).

A :class:`Brief` is the input side of conformance; :class:`~agentvision.models.report.
Conformance` is the graded output. A brief can come from three sources (all combinable):

* free-text **brief** the eyes turn into a checklist of visual claims (``backend.complete_text``);
* an **explicit checklist** the caller writes (deterministic, works with the no-key path);
* a **reference image** the render should match (structural diff + optional vision compare).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .report import Importance

# "must: ...", "should - ...", "(nice) ..." → importance prefix parsing.
# Bracketed forms make the trailing delimiter optional; bare forms require ":" / "-".
_PREFIX = re.compile(
    r"^\s*(?:"
    r"[\(\[]\s*(must|should|nice)\s*[\)\]]\s*[:\-–]?\s*"
    r"|"
    r"(must|should|nice)\s*[:\-–]\s*"
    r")",
    re.IGNORECASE,
)


class IntentClaim(BaseModel):
    """A single checkable visual requirement extracted from the intent."""

    text: str
    importance: Importance = Importance.MUST

    @classmethod
    def parse(cls, raw: str, *, default: Importance = Importance.MUST) -> IntentClaim:
        """Parse ``"must: the title reads AgentVision"`` → claim + importance."""
        m = _PREFIX.match(raw)
        if m:
            word = (m.group(1) or m.group(2)).lower()
            return cls(text=raw[m.end():].strip(), importance=Importance(word))
        return cls(text=raw.strip(), importance=default)


class Brief(BaseModel):
    """The intended product — *the thought* the render is graded against."""

    text: str | None = Field(default=None, description="Free-text description of the goal.")
    claims: list[IntentClaim] = Field(default_factory=list)
    reference_image: str | None = Field(
        default=None, description="Path to a target/mockup image the render should match."
    )

    def is_empty(self) -> bool:
        return not self.text and not self.claims and not self.reference_image

    @classmethod
    def from_inputs(
        cls,
        *,
        text: str | None = None,
        expect: list[str] | None = None,
        reference_image: str | None = None,
    ) -> Brief:
        """Build a brief from CLI/REST-style inputs (``--brief`` + repeated ``--expect``)."""
        claims = [IntentClaim.parse(e) for e in (expect or []) if e and e.strip()]
        return cls(text=text, claims=claims, reference_image=reference_image)
