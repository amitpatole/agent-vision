"""Geometry primitives. Pure Pydantic — no numpy/cv2 at import time.

``BBox`` is the shared pixel-grounding primitive (lives in :mod:`agentsense` so the ears can
ignore it and the brain can read it uniformly); ``Size``/``Viewport`` are render-specific and
stay here.
"""

from __future__ import annotations

from agentsense import BBox
from pydantic import BaseModel

__all__ = ["BBox", "Size", "Viewport"]


class Size(BaseModel):
    width: int
    height: int


class Viewport(BaseModel):
    width: int = 1280
    height: int = 800

    def label(self) -> str:
        return f"{self.width}x{self.height}"
