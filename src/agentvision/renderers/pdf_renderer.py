"""PDF -> PNG renderer (pdf2image + poppler). Renders the first page by default."""

from __future__ import annotations

from pathlib import Path

from ..config import Settings
from ..errors import MissingDependencyError, RenderError
from ..models.geometry import Viewport
from ..sources import ResolvedSource
from .base import RenderedImage, RenderResult, RenderSpec


class PdfRenderer:
    SUPPORTED = {"pdf"}

    def __init__(self, settings: Settings):
        self.settings = settings

    def supports(self, kind: str) -> bool:
        return kind in self.SUPPORTED

    async def render(self, spec: RenderSpec, resolved: ResolvedSource, out_dir: Path) -> RenderResult:
        try:
            from pdf2image import convert_from_path  # type: ignore
        except ImportError as e:
            raise MissingDependencyError(
                "PDF rendering", pip_extra="render",
                system="apt-get install poppler-utils  /  dnf install poppler-utils",
            ) from e
        if resolved.path is None:
            raise RenderError("PDF source must be a file path.")
        out_dir.mkdir(parents=True, exist_ok=True)
        # Cap source bytes before handing untrusted input to poppler (DoS / CVE-surface bound).
        from ..imageguard import MAX_IMAGE_BYTES

        try:
            nbytes = resolved.path.stat().st_size
        except OSError as e:
            raise RenderError(f"Cannot stat PDF: {e}") from e
        if nbytes > MAX_IMAGE_BYTES:
            raise RenderError(f"PDF is {nbytes} bytes, over the {MAX_IMAGE_BYTES}-byte cap.")
        # First page only, width-capped raster, hard subprocess timeout (bounds a
        # giant-MediaBox / malformed PDF rasterizing to a huge bitmap or hanging poppler).
        src = str(resolved.path)
        try:
            try:
                pages = convert_from_path(
                    src, dpi=120, first_page=1, last_page=1, size=(2000, None), timeout=60
                )
            except TypeError:  # older pdf2image without timeout support
                pages = convert_from_path(
                    src, dpi=120, first_page=1, last_page=1, size=(2000, None)
                )
        except Exception as e:  # noqa: BLE001
            raise RenderError(
                f"PDF conversion failed: {e}. Is poppler-utils installed?"
            ) from e
        if not pages:
            raise RenderError("PDF produced no pages.")
        img = pages[0]
        img_path = out_dir / "pdf_page1.png"
        img.save(img_path, "PNG")
        return RenderResult(
            images=[RenderedImage(
                path=str(img_path), viewport=Viewport(width=img.width, height=img.height),
                width=img.width, height=img.height,
            )],
            source_type="pdf",
        )
