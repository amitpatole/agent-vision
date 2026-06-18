"""OCR abstraction."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from ..models.geometry import BBox


class OcrWord(BaseModel):
    text: str
    bbox: BBox
    confidence: float = 0.0


class OcrResult(BaseModel):
    text: str = ""
    words: list[OcrWord] = Field(default_factory=list)


@runtime_checkable
class OcrBackend(Protocol):
    def available(self) -> bool: ...

    def run(self, image_path: str) -> OcrResult: ...
