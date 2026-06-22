"""Visual diff: SSIM + annotated overlay + a 'what changed' narrative.

Used both for `agentvision diff`/`regress` and inside the loop (candidate vs previous
iteration). Note: SSIM is a *visual-change* signal only — loop progress/stuck is decided
by issue-set stability, not by this number.
"""

from __future__ import annotations

from pathlib import Path

from ..models.diff import DiffRegion, DiffResult
from ..models.geometry import BBox


def _load_gray_and_rgb(path: str):
    import numpy as np
    from PIL import Image

    from ..imageguard import open_image_safely

    with open_image_safely(path) as im:  # byte + pixel caps (visual_diff takes attacker paths)
        rgb = np.asarray(im.convert("RGB"))
    gray = np.asarray(Image.fromarray(rgb).convert("L"), dtype="float64")
    return gray, rgb


def compute_diff(
    baseline_path: str | Path,
    candidate_path: str | Path,
    out_path: str | Path | None = None,
) -> DiffResult:
    from PIL import Image, ImageDraw
    from skimage.metrics import structural_similarity

    baseline_path, candidate_path = str(baseline_path), str(candidate_path)
    base_gray, _ = _load_gray_and_rgb(baseline_path)
    cand_gray, cand_rgb = _load_gray_and_rgb(candidate_path)

    resized = False
    if base_gray.shape != cand_gray.shape:
        h = min(base_gray.shape[0], cand_gray.shape[0])
        w = min(base_gray.shape[1], cand_gray.shape[1])
        base_gray = base_gray[:h, :w]
        cand_gray = cand_gray[:h, :w]
        cand_rgb = cand_rgb[:h, :w]
        resized = True

    score, ssim_map = structural_similarity(base_gray, cand_gray, full=True, data_range=255)
    changed_mask = (1.0 - ssim_map) > 0.35
    changed_ratio = float(changed_mask.mean())

    regions = _regions_from_mask(changed_mask)

    diff_image_path = None
    if out_path is not None and regions:
        annotated = Image.fromarray(cand_rgb.astype("uint8")).convert("RGB")
        draw = ImageDraw.Draw(annotated)
        for reg in regions:
            b = reg.bbox
            draw.rectangle([b.x, b.y, b.x2, b.y2], outline=(255, 0, 0), width=3)
        annotated.save(str(out_path), "PNG")
        diff_image_path = str(out_path)

    narrative = _narrative(score, changed_ratio, regions, resized)

    return DiffResult(
        ssim=round(float(score), 4),
        changed_ratio=round(changed_ratio, 5),
        regions=regions,
        diff_image_path=diff_image_path,
        narrative=narrative,
        baseline_path=baseline_path,
        candidate_path=candidate_path,
    )


def _regions_from_mask(mask, max_regions: int = 12) -> list[DiffRegion]:
    from skimage.measure import label, regionprops

    if not mask.any():
        return []
    labeled = label(mask)
    props = regionprops(labeled)
    props.sort(key=lambda p: p.area, reverse=True)
    out: list[DiffRegion] = []
    for p in props[:max_regions]:
        if p.area < 25:
            continue
        minr, minc, maxr, maxc = p.bbox
        area = (maxr - minr) * (maxc - minc)
        filled = float(p.area) / area if area else 0.0
        out.append(DiffRegion(
            bbox=BBox(x=float(minc), y=float(minr), width=float(maxc - minc),
                      height=float(maxr - minr)),
            change_ratio=round(filled, 3),
        ))
    return out


def _narrative(ssim: float, changed_ratio: float, regions: list[DiffRegion], resized: bool) -> str:
    if ssim >= 0.999 and not regions:
        base = "No visible change (images are structurally identical)."
    elif ssim >= 0.98:
        base = f"Minor visual change (SSIM {ssim:.3f}); {len(regions)} region(s) differ."
    elif ssim >= 0.85:
        base = f"Moderate visual change (SSIM {ssim:.3f}); {len(regions)} region(s) differ."
    else:
        base = (f"Major visual change (SSIM {ssim:.3f}, {changed_ratio*100:.1f}% of pixels); "
                f"{len(regions)} region(s) differ.")
    if regions:
        largest = max(regions, key=lambda r: r.bbox.width * r.bbox.height)
        base += (f" Largest changed region ~({largest.bbox.x:.0f},{largest.bbox.y:.0f}) "
                 f"{largest.bbox.width:.0f}x{largest.bbox.height:.0f}px.")
    if resized:
        base += " (Images had different dimensions; compared on the overlapping area.)"
    return base
