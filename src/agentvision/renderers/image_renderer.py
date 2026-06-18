"""Image file -> normalized PNG. No browser needed."""

from __future__ import annotations

from pathlib import Path

from ..config import Settings
from ..errors import RenderError
from ..models.geometry import Viewport
from ..sources import ResolvedSource
from .base import RenderedImage, RenderResult, RenderSpec


class ImageRenderer:
    SUPPORTED = {"image"}

    def __init__(self, settings: Settings):
        self.settings = settings

    def supports(self, kind: str) -> bool:
        return kind in self.SUPPORTED

    async def render(self, spec: RenderSpec, resolved: ResolvedSource, out_dir: Path) -> RenderResult:
        from PIL import Image

        if resolved.path is None:
            raise RenderError("Image source must be a file path.")
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            with Image.open(resolved.path) as im:
                im = im.convert("RGB")
                img_path = out_dir / "image.png"
                im.save(img_path, "PNG")
                w, h = im.size
        except Exception as e:  # noqa: BLE001
            raise RenderError(f"Could not open image: {e}") from e
        return RenderResult(
            images=[RenderedImage(
                path=str(img_path), viewport=Viewport(width=w, height=h), width=w, height=h,
            )],
            source_type="image",
        )
