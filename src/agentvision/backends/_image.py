"""Shared helpers for sending images to vision backends."""

from __future__ import annotations

import base64
from pathlib import Path


def load_image_b64(path: str) -> tuple[str, str, tuple[int, int]]:
    """Return (base64_data, media_type, (width, height))."""
    from PIL import Image

    p = Path(path)
    data = p.read_bytes()
    media = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif",
    }.get(p.suffix.lower(), "image/png")
    with Image.open(p) as im:
        size = im.size
    return base64.b64encode(data).decode("ascii"), media, size
