"""Untrusted-image safety — byte + pixel caps applied BEFORE any decode.

A decompression bomb is a tiny file (a few KB) whose header declares enormous dimensions
(e.g. 64000x64000); `Image.convert()`/`resize()`/`numpy.asarray()` then try to allocate
multiple gigabytes → OOM/DoS. A byte cap alone can't stop it (the file is small) — the pixel
cap is the real defense, checked from the header before any pixel buffer is allocated.

`open_image_safely` is the one entry point every decode site uses. It also lowers PIL's own
`Image.MAX_IMAGE_PIXELS` so any path that slips by still raises `DecompressionBombError`.
"""

from __future__ import annotations

from pathlib import Path

from .errors import UnsafeSourceError

# A small file can still decode huge; both caps matter. ~64M px ≈ 256 MB worst-case buffer —
# bounded, while still allowing legitimate tall full-page screenshots (~1280×50000).
MAX_IMAGE_BYTES = 25_000_000
MAX_IMAGE_PIXELS = 64_000_000


def _arm_pil_bomb_guard() -> None:
    from PIL import Image

    if Image.MAX_IMAGE_PIXELS is None or Image.MAX_IMAGE_PIXELS > MAX_IMAGE_PIXELS:
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


def open_image_safely(path: str | Path):
    """Open an image with byte + pixel caps enforced before any decode. Returns a PIL Image
    (lazy — caller does `.convert()`/`.load()`). Raises ``UnsafeSourceError`` if the file is
    too large or its declared dimensions exceed the decompression-bomb cap."""
    from PIL import Image

    _arm_pil_bomb_guard()
    p = Path(path)
    try:
        nbytes = p.stat().st_size
    except OSError as e:
        raise UnsafeSourceError(f"Cannot stat image: {e}") from e
    if nbytes > MAX_IMAGE_BYTES:
        raise UnsafeSourceError(
            f"Image is {nbytes} bytes, over the {MAX_IMAGE_BYTES}-byte cap (DoS protection)."
        )
    try:
        im = Image.open(p)  # header only; does not decode pixels
        width, height = im.size
    except UnsafeSourceError:
        raise
    except Exception as e:  # noqa: BLE001  (PIL raises many types incl. DecompressionBombError)
        raise UnsafeSourceError(f"Could not open image: {e}") from e
    if width * height > MAX_IMAGE_PIXELS:
        raise UnsafeSourceError(
            f"Image dimensions {width}x{height} exceed the {MAX_IMAGE_PIXELS}-pixel cap "
            "(decompression-bomb protection)."
        )
    return im
