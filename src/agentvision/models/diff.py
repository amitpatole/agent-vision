"""Visual diff result model. Pure Pydantic."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .geometry import BBox


class DiffRegion(BaseModel):
    bbox: BBox
    change_ratio: float = Field(ge=0, le=1, description="Fraction of this region that changed.")


class DiffResult(BaseModel):
    ssim: float = Field(description="Structural similarity, 0..1 (1 == identical).")
    changed_ratio: float = Field(ge=0, le=1, description="Fraction of pixels that changed.")
    regions: list[DiffRegion] = Field(default_factory=list)
    diff_image_path: str | None = None
    narrative: str = ""
    baseline_path: str | None = None
    candidate_path: str | None = None

    @property
    def identical(self) -> bool:
        return self.ssim >= 0.999 and self.changed_ratio <= 0.0005
