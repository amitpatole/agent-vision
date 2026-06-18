"""Geometry primitives. Pure Pydantic — no numpy/cv2 at import time."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Size(BaseModel):
    width: int
    height: int


class Viewport(BaseModel):
    width: int = 1280
    height: int = 800

    def label(self) -> str:
        return f"{self.width}x{self.height}"


class BBox(BaseModel):
    """An axis-aligned box. Always in IMAGE pixels once it reaches a Report."""

    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(ge=0)
    height: float = Field(ge=0)

    @property
    def x2(self) -> float:
        return self.x + self.width

    @property
    def y2(self) -> float:
        return self.y + self.height

    def scaled(self, factor: float) -> BBox:
        return BBox(x=self.x * factor, y=self.y * factor,
                    width=self.width * factor, height=self.height * factor)

    def translated(self, dx: float, dy: float) -> BBox:
        return BBox(x=self.x + dx, y=self.y + dy, width=self.width, height=self.height)
