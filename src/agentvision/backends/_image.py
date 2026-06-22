"""Shared helpers for sending images to vision backends."""

from __future__ import annotations

import base64
import io
from pathlib import Path

from ..imageguard import open_image_safely


def load_image_b64(path: str, max_edge: int | None = None) -> tuple[str, str, tuple[int, int]]:
    """Return (base64_data, media_type, (width, height)).

    When ``max_edge`` is set and the image's longest side exceeds it, the image is
    downscaled before encoding. Oversized/dense screenshots make vision models lazy
    (generic, hallucinated critiques); a model-friendly size keeps the critique specific.
    The returned size is the size actually sent (vision bboxes are advisory regardless).
    """
    p = Path(path)
    media = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif",
    }.get(p.suffix.lower(), "image/png")

    with open_image_safely(p) as im:
        size = im.size
        if max_edge and max(size) > max_edge:
            scale = max_edge / max(size)
            im = im.convert("RGB").resize(
                (max(1, round(size[0] * scale)), max(1, round(size[1] * scale)))
            )
            buf = io.BytesIO()
            im.save(buf, "PNG")
            return base64.b64encode(buf.getvalue()).decode("ascii"), "image/png", im.size

    return base64.b64encode(p.read_bytes()).decode("ascii"), media, size
