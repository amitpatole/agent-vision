"""Renderer protocol and shared render data types."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator

from ..models.geometry import BBox, Viewport
from ..models.interaction import Interaction
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
    # --- Authenticated rendering (get past a login wall) ---
    storage_state_path: str | None = None  # Playwright storage_state JSON (cookies+localStorage)
    auth_header_env: str | None = None      # env var NAME → Authorization header (same-origin only)
    http_credentials_env: str | None = None  # env var NAME → "user:pass" for HTTP Basic (scoped)
    # --- Pre-capture interaction (reach state that only appears after click/hover/zoom) ---
    interactions: list[Interaction] = Field(default_factory=list)
    allow_mutations: bool = False  # if False, non-GET requests are blocked while steps run
    step_timeout_ms: int = 8000  # per-step ceiling (clamped by the renderer)

    @model_validator(mode="after")
    def _one_viewport_with_interactions(self) -> RenderSpec:
        # Interactions replay against a single page; a click_at fraction or a revealed popup
        # would land differently per viewport, and the renderer takes canonical signals from
        # viewport[0]. So interactions require exactly one viewport (fail loud, don't guess).
        if self.interactions and len(self.viewports) > 1:
            raise ValueError("interactions require a single viewport (got "
                             f"{len(self.viewports)}); run one viewport at a time")
        return self


class InteractionStep(BaseModel):
    """The recorded outcome of one executed interaction step (log-safe, no secret values)."""

    index: int
    type: str
    selector: str = ""
    ok: bool = True
    detail: str = ""  # resolved coords, or the failure reason
    elapsed_ms: int = 0
    blocked_mutations: int = 0  # non-GET requests aborted while this step ran


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
    kind: str = "clipped"  # svg_clipped | truncated | container_clipped
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
    paint_effects: bool = False  # filter/blend/stroke/text-clip: computed colours unreliable
    visible_frac: float = 1.0  # painted text left after document bounds + clipping ancestors
    glyph_bbox: BBox | None = None  # union of the element's own text-glyph rects (image px)
    glyph_rects: list[BBox] = Field(default_factory=list)  # each own-text line box (image px)
    fg_rgba: tuple[float, float, float, float] | None = None  # painted fg colour + alpha
    inactive: bool = False  # text of a disabled control (WCAG 1.4.3 exempt)
    halo: bool = False  # opaque contrasting text-shadow halo (legible over photos)
    shadow_only: bool = False  # only effect is a text-shadow: the fill colour is exact
    in_overlay: bool = False  # the text belongs to a fixed/sticky overlay itself
    covered_lines: list[int] = Field(default_factory=list)  # glyph_rects indices an overlay sits on
    cover_colors: list[tuple[float, float, float, float]] = Field(default_factory=list)  # per covered line
    line_words: list[list[str]] = Field(default_factory=list)  # words on each glyph_rects line
    min_line_h: float = 0.0  # smallest rendered line height, CSS px (0 = unknown)
    eff_font_px: float = 0.0  # painted font size: computed size x transform scale x zoom
    in_ruby: bool = False  # ruby annotation (rt/rp) over a real base: small by design
    sup_sub: bool = False  # superscript/subscript text (footnote markers)
    block_key: int = 0  # nearest block container id (pools fragments on either axis)
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
    overlaps: list[ElementBox] = Field(
        default_factory=list,
        description="Text covered by a positioned element (bbox = the covered region; "
                    "text = the covered text; selector = the occluding element).",
    )
    error_text: list[ElementBox] = Field(
        default_factory=list,
        description="Visible error copy on the page (e.g. 'Error 403', 'Playback failed').",
    )
    vocab_text: str = Field(
        default="", description="Full visible text of sampled elements (spelling severity)."
    )
    form_fields: list[dict] = Field(
        default_factory=list,
        description="Visible form fields' value/placeholder text with its painted font size.",
    )
    extraction_error: str | None = Field(
        default=None,
        description="Why the DOM grading extractor failed, if it did (the DOM checks did not run).",
    )
    extraction_truncated: bool = Field(
        default=False,
        description="The extractor hit its time budget; some elements were not checked.",
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
    interaction_log: list[InteractionStep] = Field(
        default_factory=list,
        description="Outcome of each pre-capture interaction step (what state was reached).",
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
