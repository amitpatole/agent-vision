"""PDF → PNG renderer (pdf2image + poppler).

Renders up to ``settings.document_max_pages`` pages. A multi-page document is also stacked
into a single vertical composite (kept under the decompression-bomb pixel cap) which becomes
the ``primary`` image, so the analyze pipeline's tiling sees every page with no changes; the
individual page images follow in ``images``.
"""

from __future__ import annotations

from pathlib import Path

from ..config import Settings
from ..errors import MissingDependencyError, RenderError
from ..imageguard import MAX_IMAGE_PIXELS
from ..models.geometry import Viewport
from ..sources import ResolvedSource
from .base import RenderedImage, RenderResult, RenderSpec

_PAGE_GAP = 8  # px separator between stacked pages in the composite


def rasterize_pdf(pdf_path: Path, settings: Settings) -> list:
    """Rasterize up to ``document_max_pages`` pages of a PDF to PIL images (width-capped)."""
    try:
        from pdf2image import convert_from_path  # type: ignore
    except ImportError as e:
        raise MissingDependencyError(
            "PDF rendering", pip_extra="render",
            system="apt-get install poppler-utils  /  dnf install poppler-utils",
        ) from e
    # Cap source bytes before handing untrusted input to poppler (DoS / CVE-surface bound).
    try:
        nbytes = pdf_path.stat().st_size
    except OSError as e:
        raise RenderError(f"Cannot stat PDF: {e}") from e
    if nbytes > settings.max_document_bytes:
        raise RenderError(f"PDF is {nbytes} bytes, over the {settings.max_document_bytes}-byte cap.")
    last = max(1, settings.document_max_pages)
    dpi = settings.document_raster_dpi
    size = (settings.document_max_page_px, None)
    src = str(pdf_path)
    try:
        try:
            pages = convert_from_path(
                src, dpi=dpi, first_page=1, last_page=last, size=size,
                timeout=int(settings.document_convert_timeout_s),
            )
        except TypeError:  # older pdf2image without timeout support
            pages = convert_from_path(src, dpi=dpi, first_page=1, last_page=last, size=size)
    except Exception as e:  # noqa: BLE001
        raise RenderError(f"PDF conversion failed: {e}. Is poppler-utils installed?") from e
    if not pages:
        raise RenderError("PDF produced no pages.")
    return pages


def build_document_result(pages: list, source_type: str, out_dir: Path) -> RenderResult:
    """Save per-page PNGs and (for >1 page) prepend a stacked composite as the primary."""
    out_dir.mkdir(parents=True, exist_ok=True)
    page_images: list[RenderedImage] = []
    for i, pg in enumerate(pages, start=1):
        p = out_dir / f"page_{i:03d}.png"
        pg.save(p, "PNG")
        page_images.append(RenderedImage(
            path=str(p), viewport=Viewport(width=pg.width, height=pg.height),
            width=pg.width, height=pg.height,
        ))
    if len(page_images) == 1:
        return RenderResult(images=page_images, source_type=source_type)
    composite = _stack_pages(pages, out_dir)
    return RenderResult(images=[composite, *page_images], source_type=source_type)


def _stack_pages(pages: list, out_dir: Path) -> RenderedImage:
    """Vertically stack pages into one composite image, scaled to fit the pixel cap."""
    from PIL import Image

    rgb = [p.convert("RGB") for p in pages]
    target_w = max(p.width for p in rgb)
    total_h = sum(p.height for p in rgb) + _PAGE_GAP * (len(rgb) - 1)
    # Keep the composite under the decompression-bomb cap so open_image_safely() accepts it.
    scale = 1.0
    if target_w * total_h > MAX_IMAGE_PIXELS:
        scale = (MAX_IMAGE_PIXELS / (target_w * total_h)) ** 0.5
    canvas_w = max(1, int(target_w * scale))
    canvas_h = max(1, int(total_h * scale))
    canvas = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
    y = 0
    for p in rgb:
        w = max(1, int(p.width * scale))
        h = max(1, int(p.height * scale))
        tile = p.resize((w, h)) if scale != 1.0 else p
        canvas.paste(tile, ((canvas_w - w) // 2, y))
        y += h + max(1, int(_PAGE_GAP * scale))
    out = out_dir / "document.png"
    canvas.save(out, "PNG")
    return RenderedImage(path=str(out), viewport=Viewport(width=canvas_w, height=canvas_h),
                         width=canvas_w, height=canvas_h)


class PdfRenderer:
    SUPPORTED = {"pdf"}

    def __init__(self, settings: Settings):
        self.settings = settings

    def supports(self, kind: str) -> bool:
        return kind in self.SUPPORTED

    async def render(self, spec: RenderSpec, resolved: ResolvedSource, out_dir: Path) -> RenderResult:
        if resolved.path is None:
            raise RenderError("PDF source must be a file path.")
        pages = rasterize_pdf(resolved.path, self.settings)
        return build_document_result(pages, "pdf", out_dir)
