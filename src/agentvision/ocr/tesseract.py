"""Tesseract OCR backend (pytesseract). Returns text + precise word boxes."""

from __future__ import annotations

import shutil

from ..errors import MissingDependencyError
from ..models.geometry import BBox
from .base import OcrResult, OcrWord


class TesseractOcr:
    def available(self) -> bool:
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            return False
        return shutil.which("tesseract") is not None

    def run(self, image_path: str) -> OcrResult:
        try:
            import pytesseract
            from PIL import Image
        except ImportError as e:
            raise MissingDependencyError(
                "OCR", pip_extra="ocr",
                system="apt-get install tesseract-ocr tesseract-ocr-eng  /  "
                       "dnf install tesseract tesseract-langpack-eng",
            ) from e
        if shutil.which("tesseract") is None:
            raise MissingDependencyError(
                "OCR", system="apt-get install tesseract-ocr tesseract-ocr-eng",
            )
        with Image.open(image_path) as im:
            data = pytesseract.image_to_data(
                im.convert("RGB"), output_type=pytesseract.Output.DICT
            )
        words: list[OcrWord] = []
        texts: list[str] = []
        n = len(data["text"])
        for i in range(n):
            txt = (data["text"][i] or "").strip()
            try:
                conf = float(data["conf"][i])
            except (ValueError, TypeError):
                conf = -1.0
            if not txt or conf < 0:
                continue
            words.append(OcrWord(
                text=txt,
                bbox=BBox(x=float(data["left"][i]), y=float(data["top"][i]),
                          width=float(data["width"][i]), height=float(data["height"][i])),
                confidence=conf / 100.0,
            ))
            texts.append(txt)
        return OcrResult(text=" ".join(texts), words=words)


def get_ocr_backend() -> TesseractOcr:
    return TesseractOcr()
