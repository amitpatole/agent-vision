"""Full-coverage vision: tile a large artifact at full resolution so nothing is lost.

A vision model is sent a *downscaled* whole image (to stay model-friendly and avoid the
"lazy on a huge dense image" failure). That overview is great for layout but loses fine
detail — small text, a chart's data, a thumbnail. This module cuts the **full-resolution**
render into a bounded set of content tiles so the model can also read every region at native
detail.

It is deliberately **pixel-based and source-agnostic**: it works on the rendered screenshot
alone, with no dependency on the DOM. So it covers anything the eyes can render — HTML, a
flat image, a PDF page, a `<canvas>`/WebGL surface, an `<iframe>` — uniformly.
"""

from __future__ import annotations

import math
from pathlib import Path


def plan_coverage_tiles(
    image_path: str, *, max_edge: int, max_tiles: int, blank_std: float = 6.0
) -> list[str]:
    """Crop ``image_path`` into up to ``max_tiles`` full-res content tiles.

    Returns crop paths (written next to the image). Empty when the image already fits in
    ``max_edge`` (the whole image is already full detail) or tiling is disabled. Near-uniform
    (blank) tiles are skipped; when there are more content tiles than ``max_tiles`` the most
    content-rich are kept (and emitted in reading order).
    """
    if max_tiles <= 0:
        return []
    try:
        import numpy as np

        from ..imageguard import open_image_safely
    except Exception:  # noqa: BLE001
        return []
    try:
        im = open_image_safely(image_path).convert("RGB")
    except Exception:  # noqa: BLE001
        return []

    w, h = im.size
    if max(w, h) <= max_edge:
        return []  # already full detail at a model-friendly size

    cols = math.ceil(w / max_edge)
    rows = math.ceil(h / max_edge)
    tw = math.ceil(w / cols)
    th = math.ceil(h / rows)
    arr = np.asarray(im)

    scored: list[tuple[float, tuple[int, int, int, int]]] = []
    for r in range(rows):
        for c in range(cols):
            x0, y0 = c * tw, r * th
            x1, y1 = min(w, x0 + tw), min(h, y0 + th)
            if x1 - x0 < 32 or y1 - y0 < 32:
                continue
            std = float(arr[y0:y1, x0:x1].std())
            if std < blank_std:
                continue  # near-uniform => blank, not worth a tile
            scored.append((std, (x0, y0, x1, y1)))

    scored.sort(key=lambda t: t[0], reverse=True)          # most content first
    chosen = scored[:max_tiles]
    chosen.sort(key=lambda t: (t[1][1], t[1][0]))          # then reading order

    base = Path(image_path).parent
    out: list[str] = []
    for i, (_, box) in enumerate(chosen):
        p = base / f"tile_{i}.png"
        try:
            im.crop(box).save(p)
            out.append(str(p))
        except Exception:  # noqa: BLE001
            continue
    return out
