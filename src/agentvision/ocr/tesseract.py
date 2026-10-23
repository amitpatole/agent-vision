"""Tesseract OCR backend (pytesseract). Returns text + precise word boxes."""

from __future__ import annotations

import os
import shutil

from ..errors import MissingDependencyError
from ..imageguard import open_image_safely
from ..models.geometry import BBox
from .base import OcrResult, OcrWord

# Hard cap on the tesseract subprocess so an attacker image can't pin a CPU forever.
_OCR_TIMEOUT_S = 30
# Tesseract 4's OpenMP threading oversubscribes the CPU when several OCR runs (or other work)
# share a host: one page measured 6.1 s with default threads vs 0.26 s single-threaded at load
# ~12 on 4 cores, which pushed real pages past the timeout. Single-thread by default; an
# operator's explicit OMP_THREAD_LIMIT wins.
_OMP_DEFAULT = "1"
# Set once at import (not per call): OCR now runs in worker threads, and setenv racing a
# getenv in another thread is not safe in C.
os.environ.setdefault("OMP_THREAD_LIMIT", _OMP_DEFAULT)


class TesseractOcr:
    def available(self) -> bool:
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            return False
        return shutil.which("tesseract") is not None

    def run(self, image_path: str, *, timeout_s: float | None = None) -> OcrResult:
        try:
            import pytesseract
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
        with open_image_safely(image_path) as im:  # byte + pixel caps before decode
            data = pytesseract.image_to_data(
                im.convert("RGB"), output_type=pytesseract.Output.DICT,
                timeout=min(_OCR_TIMEOUT_S, timeout_s) if timeout_s else _OCR_TIMEOUT_S,
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
