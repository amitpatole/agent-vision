"""Renderer protocol and shared render data types."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from ..models.geometry import BBox, Viewport
from ..sources import ResolvedSource


class RenderSpec(BaseModel):
    source: str
    source_type: str = "auto"
    viewports: list[Viewport] = Field(default_factory=lambda: [Viewport()])
    full_page: bool = False
    wait_for: str | None = None  # selector, or 'load'|'domcontentloaded'|'networkidle'
    device_scale: float = 1.0


class ElementBox(BaseModel):
    """A DOM element's geometry, already normalized to IMAGE pixels."""

    tag: str
    bbox: BBox
    text: str = ""
    selector: str = ""


class ContrastSample(BaseModel):
    """A computed-style WCAG contrast measurement, in IMAGE pixels."""

    bbox: BBox
    ratio: float
    fg: str
    bg: str
    font_px: float
    large_text: bool
    passes_aa: bool
    passes_aaa: bool
    confidence: str = "high"  # 'high' over solid bg; 'low' over image/gradient/opacity
    text: str = ""
    selector: str = ""


class ConsoleError(BaseModel):
    text: str
    kind: str = "console"  # console | pageerror


class FailedResponse(BaseModel):
    url: str
    status: int | None = None
    reason: str = ""


class RenderedImage(BaseModel):
    path: str
    viewport: Viewport
    width: int
    height: int


class RenderResult(BaseModel):
    images: list[RenderedImage] = Field(default_factory=list)
    dom_boxes: list[ElementBox] = Field(default_factory=list)
    contrast_samples: list[ContrastSample] = Field(default_factory=list)
    console_errors: list[ConsoleError] = Field(default_factory=list)
    failed_responses: list[FailedResponse] = Field(default_factory=list)
    broken_images: list[ElementBox] = Field(default_factory=list)
    overflow_x: float = Field(default=0.0, description="Horizontal layout overflow in image px.")
    source_type: str = "html"

    @property
    def primary(self) -> RenderedImage | None:
        return self.images[0] if self.images else None


@runtime_checkable
class Renderer(Protocol):
    def supports(self, kind: str) -> bool: ...

    async def render(
        self, spec: RenderSpec, resolved: ResolvedSource, out_dir: Path
    ) -> RenderResult: ...
