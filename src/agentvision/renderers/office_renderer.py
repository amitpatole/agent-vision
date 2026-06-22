"""Office / OpenDocument renderer — convert to PDF (LibreOffice), then rasterize.

`docx/pptx/xlsx/odt/odp/ods/…` → PDF (see :mod:`agentvision.office`) → the same multi-page
PDF rasterizer used for native PDFs. Gated by ``settings.allow_office_render`` (off on the
untrusted REST service).
"""

from __future__ import annotations

from pathlib import Path

from ..config import Settings
from ..errors import RenderError
from ..office import convert_to_pdf
from ..sources import ResolvedSource
from .base import RenderResult, RenderSpec
from .pdf_renderer import build_document_result, rasterize_pdf


class OfficeRenderer:
    SUPPORTED = {"office"}

    def __init__(self, settings: Settings):
        self.settings = settings

    def supports(self, kind: str) -> bool:
        return kind in self.SUPPORTED

    async def render(self, spec: RenderSpec, resolved: ResolvedSource, out_dir: Path) -> RenderResult:
        if resolved.path is None:
            raise RenderError("Office source must be a file path.")
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf = await convert_to_pdf(resolved.path, out_dir, self.settings)
        pages = rasterize_pdf(pdf, self.settings)
        return build_document_result(pages, "office", out_dir)
