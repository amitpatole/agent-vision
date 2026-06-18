"""OCR backends."""

from .base import OcrBackend, OcrResult, OcrWord


def get_ocr_backend():
    from .tesseract import TesseractOcr

    return TesseractOcr()


__all__ = ["OcrBackend", "OcrResult", "OcrWord", "get_ocr_backend"]
