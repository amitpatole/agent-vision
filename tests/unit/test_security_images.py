"""Untrusted-image safety regression tests (security batch 2).

Pins: a decompression bomb (tiny file, huge declared dimensions) and an over-cap file are
rejected BEFORE any pixel buffer is allocated, while a normal image opens fine.
"""

import struct
import zlib

import pytest
from PIL import Image

from agentvision.errors import UnsafeSourceError
from agentvision.imageguard import MAX_IMAGE_PIXELS, open_image_safely


def _make_bomb_png(path, w=64000, h=64000):
    """A handful of bytes whose PNG IHDR declares w×h — a classic decompression bomb."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_body = struct.pack(">II", w, h) + bytes([8, 2, 0, 0, 0])  # 8-bit RGB
    ihdr = b"IHDR" + ihdr_body
    out = sig + struct.pack(">I", len(ihdr_body)) + ihdr + struct.pack(">I", zlib.crc32(ihdr) & 0xFFFFFFFF)
    idat_body = zlib.compress(b"\x00")
    idat = b"IDAT" + idat_body
    out += struct.pack(">I", len(idat_body)) + idat + struct.pack(">I", zlib.crc32(idat) & 0xFFFFFFFF)
    out += struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF)
    path.write_bytes(out)
    return len(out)


def test_decompression_bomb_rejected_before_decode(tmp_path):
    p = tmp_path / "bomb.png"
    nbytes = _make_bomb_png(p)
    assert nbytes < 1000  # a few-KB file claiming 64000x64000 = ~4 billion pixels
    with pytest.raises(UnsafeSourceError):
        open_image_safely(p)


def test_over_byte_cap_rejected(tmp_path):
    p = tmp_path / "huge.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 26_000_000)
    with pytest.raises(UnsafeSourceError):
        open_image_safely(p)


def test_normal_image_opens(tmp_path):
    p = tmp_path / "ok.png"
    Image.new("RGB", (120, 90), "white").save(p)
    with open_image_safely(p) as im:
        assert im.size == (120, 90)


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
def test_pixel_cap_boundary(tmp_path):
    # just over the cap is rejected; the cap is the real bomb defense
    p = tmp_path / "edge.png"
    over = MAX_IMAGE_PIXELS + 1
    _make_bomb_png(p, w=over, h=1)
    with pytest.raises(UnsafeSourceError):
        open_image_safely(p)


async def test_image_renderer_rejects_bomb(tmp_path):
    from agentvision import load_settings
    from agentvision.core import render

    p = tmp_path / "bomb.png"
    _make_bomb_png(p)
    with pytest.raises(UnsafeSourceError):
        await render(str(p), settings=load_settings(), source_type="image")
