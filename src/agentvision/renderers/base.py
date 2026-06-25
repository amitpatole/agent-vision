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
    settle_ms: int = 0  # quiet wait after load before extract/capture
    freeze: bool = False  # pause CSS animations + rAF (canvas/WebGL) before capture


class ElementBox(BaseModel):
    """A DOM element's geometry, already normalized to IMAGE pixels."""

    tag: str
    bbox: BBox
    text: str = ""
    selector: str = ""


class ClippedText(BaseModel):
    """Text cut off by a clip boundary — an SVG viewport or a DOM container's hard overflow.

    ``kind`` is ``svg_clipped`` (a ``<text>`` extending beyond its SVG viewport, which clips by
    default) or ``truncated`` (a DOM element whose content overflows its box under
    ``overflow:hidden/clip`` with no ellipsis). Geometry is in IMAGE pixels.
    """

    bbox: BBox
    text: str = ""
    selector: str = ""
    tag: str = ""
    kind: str = "clipped"  # svg_clipped | truncated
    overflow_px: float = 0.0  # how far the content exceeds the clip boundary (image px)


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


class MediaState(BaseModel):
    """Deterministic `<video>`/`<audio>` state at one instant — the trustworthy streaming
    signal (read from the media element, not inferred from pixels)."""

    selector: str = ""
    current_time: float = 0.0
    duration: float = 0.0
    paused: bool = True
    ended: bool = False
    ready_state: int = 0  # 0=HAVE_NOTHING … 4=HAVE_ENOUGH_DATA
    video_width: int = 0
    video_height: int = 0
    buffered_end: float = 0.0
    captions: int = 0  # number of text tracks
    active_captions: int = 0  # text tracks showing


class Frame(BaseModel):
    """One sampled frame in a temporal capture."""

    index: int
    t_ms: int
    image_path: str
    width: int = 0
    height: int = 0
    media: list[MediaState] = Field(default_factory=list)


class RenderResult(BaseModel):
    images: list[RenderedImage] = Field(default_factory=list)
    dom_boxes: list[ElementBox] = Field(default_factory=list)
    contrast_samples: list[ContrastSample] = Field(default_factory=list)
    console_errors: list[ConsoleError] = Field(default_factory=list)
    failed_responses: list[FailedResponse] = Field(default_factory=list)
    broken_images: list[ElementBox] = Field(default_factory=list)
    clipped_text: list[ClippedText] = Field(
        default_factory=list,
        description="Text cut off by an SVG viewport or a DOM hard-overflow boundary.",
    )
    overflow_x: float = Field(default=0.0, description="Horizontal layout overflow in image px.")
    visual_tags: list[str] = Field(
        default_factory=list,
        description="Sizable non-text visual elements present (canvas/svg/img/video).",
    )
    visual_elements: list[ElementBox] = Field(
        default_factory=list,
        description="Sizable visual elements with image-px geometry (for full-res crops).",
    )
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
