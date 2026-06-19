"""Vision backend protocol + the analysis request.

The ``VisionBackend`` abstraction is the architectural proof of provider-independence:
the same :class:`~agentvision.models.report.Report` contract is produced by Anthropic,
OpenAI, Gemini, or the offline Local backend, selectable by config/env.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from ..models.geometry import Viewport
from ..models.report import Issue, Report


class AnalysisRequest(BaseModel):
    image_path: str
    viewport: Viewport = Field(default_factory=Viewport)
    device_scale: float = 1.0
    instructions: str | None = Field(
        default=None, description="Task-specific guidance, e.g. 'verify the login form renders'."
    )
    expected: str | None = Field(default=None, description="What the agent intended to produce.")
    ocr_text: str | None = None
    dom_hints: list[Issue] = Field(
        default_factory=list,
        description="Grounded DOM/CV findings the LLM should confirm/expand, not re-derive.",
    )
    claims: list[str] = Field(
        default_factory=list,
        description="Numbered requirements (the intended product) to grade the render against.",
    )
    reference_image_path: str | None = Field(
        default=None, description="A target/mockup image the render should match."
    )
    extra_images: list[str] = Field(
        default_factory=list,
        description="Additional context images (e.g. full-res crops of chart/canvas regions).",
    )


@runtime_checkable
class VisionBackend(Protocol):
    name: str

    def available(self) -> bool: ...

    async def analyze(self, req: AnalysisRequest) -> Report: ...

    async def complete_text(self, system: str, user: str) -> str:
        """Text-only completion (no image) — for checklist extraction + prompt refinement.

        Backends that cannot do this (e.g. the offline ``local`` backend) return ``""``.
        """
        ...
