"""Renderers: turn a source into image(s) + trustworthy signals."""

from .base import (
    ConsoleError,
    ContrastSample,
    ElementBox,
    FailedResponse,
    RenderedImage,
    Renderer,
    RenderResult,
    RenderSpec,
)


def get_renderer(kind: str, settings):
    """Return a renderer instance for a resolved source kind."""
    from .image_renderer import ImageRenderer
    from .pdf_renderer import PdfRenderer
    from .playwright_renderer import PlaywrightRenderer

    for cls in (PlaywrightRenderer, PdfRenderer, ImageRenderer):
        r = cls(settings)
        if r.supports(kind):
            return r
    raise ValueError(f"No renderer supports source kind {kind!r}")


__all__ = [
    "Renderer", "RenderSpec", "RenderResult", "RenderedImage", "ElementBox",
    "ContrastSample", "ConsoleError", "FailedResponse", "get_renderer",
]
