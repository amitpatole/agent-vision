"""Full-coverage tiling — pixel-based, source-agnostic full-res coverage of large artifacts."""

import numpy as np
from PIL import Image

from agentvision.core.tiling import plan_coverage_tiles


def _noise(path, w, h):
    arr = (np.random.default_rng(0).integers(0, 256, (h, w, 3))).astype("uint8")
    Image.fromarray(arr).save(path)


def test_small_image_not_tiled(tmp_path):
    p = tmp_path / "small.png"
    _noise(p, 800, 600)
    assert plan_coverage_tiles(str(p), max_edge=2000, max_tiles=6) == []


def test_large_image_tiled_full_res(tmp_path):
    p = tmp_path / "tall.png"
    _noise(p, 1000, 4000)  # max edge 4000 > 800 -> tiled
    tiles = plan_coverage_tiles(str(p), max_edge=800, max_tiles=6)
    assert tiles, "expected coverage tiles for an oversized image"
    for t in tiles:
        w, h = Image.open(t).size
        assert w <= 800 and h <= 800  # each tile is full-res and model-friendly


def test_tile_cap_respected(tmp_path):
    p = tmp_path / "huge.png"
    _noise(p, 2000, 6000)
    tiles = plan_coverage_tiles(str(p), max_edge=500, max_tiles=4)
    assert len(tiles) == 4


def test_blank_image_yields_no_tiles(tmp_path):
    p = tmp_path / "blank.png"
    Image.new("RGB", (1000, 4000), "white").save(p)  # uniform -> no content tiles
    assert plan_coverage_tiles(str(p), max_edge=800, max_tiles=6) == []


def test_disabled_when_max_tiles_zero(tmp_path):
    p = tmp_path / "x.png"
    _noise(p, 3000, 3000)
    assert plan_coverage_tiles(str(p), max_edge=1000, max_tiles=0) == []
