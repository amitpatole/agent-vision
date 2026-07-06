"""End-to-end motion grading — a real video through analyze/check, no browser, no egress.

Generates a tiny test clip with ffmpeg at test time (nothing heavy committed). Skipped
when ffmpeg is absent; the GIF path is covered without ffmpeg in the unit suite.
"""

import subprocess

import pytest
from PIL import Image

from agentvision.config import load_settings
from agentvision.core.analyze import analyze, check
from agentvision.renderers.motion import find_ffmpeg

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not available")


def _make_clip(path, *, moving=True, seconds=2, size="128x96"):
    src = f"testsrc=duration={seconds}:size={size}:rate=12" if moving else \
          f"color=c=gray:duration={seconds}:size={size}:rate=12"
    subprocess.run(
        [find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", src,
         "-pix_fmt", "yuv420p", "-y", str(path)],
        check=True, timeout=60,
    )


async def test_mp4_gets_a_real_verdict_not_blank(tmp_path):
    """Acceptance: no misroute to Playwright, frames >= 6, moving = true."""
    clip = tmp_path / "clip.mp4"
    _make_clip(clip, moving=True)
    rep = await check(str(clip), settings=load_settings())
    assert rep.backend == "watch"          # temporal path, not the browser
    assert not [i for i in rep.issues if i.kind.value == "blank"]
    temporal = rep.issues[0].detail["temporal"]
    assert temporal["frames"] >= 6
    assert temporal["moving"] is True


async def test_static_video_fails_dead_export_check(tmp_path):
    """Acceptance: an all-identical-frames video FAILs the deterministic motion check."""
    clip = tmp_path / "static.mp4"
    _make_clip(clip, moving=False)
    rep = await check(str(clip), settings=load_settings())
    assert rep.verdict.value == "fail"
    assert any(i.detail.get("temporal") == "no_motion" for i in rep.issues)


async def test_analyze_routes_motion_to_temporal(tmp_path):
    """analyze() on a motion file auto-films-trips it (local backend -> no vision pass)."""
    clip = tmp_path / "clip.mp4"
    _make_clip(clip, moving=True)
    rep = await analyze(str(clip), settings=load_settings(vision_backend="local"))
    assert rep.backend.startswith("watch")
    assert rep.issues[0].detail["temporal"]["moving"] is True


async def test_animated_gif_end_to_end_grades_the_animation(tmp_path):
    """The handover's GIF case, through the public check() API (no ffmpeg needed)."""
    frames = []
    for i in range(6):
        im = Image.new("RGB", (80, 60), "white")
        for x in range(i * 10, i * 10 + 8):
            for y in range(10, 18):
                im.putpixel((x, y), (0, 120, 0))
        frames.append(im)
    gif = tmp_path / "anim.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=100, loop=0)
    rep = await check(str(gif), settings=load_settings())
    assert rep.backend == "watch"
    assert rep.issues[0].detail["temporal"]["moving"] is True
    assert rep.verdict.value != "fail"


async def test_motion_local_path_no_egress(tmp_path, monkeypatch):
    """--backend local on motion: any socket connect() is a failure (no-egress contract)."""
    import socket

    def _no_connect(*a, **k):
        raise AssertionError("network egress attempted during local motion grading")

    clip = tmp_path / "clip.mp4"
    _make_clip(clip, moving=True)  # created BEFORE the network is sealed
    monkeypatch.setattr(socket.socket, "connect", _no_connect)
    rep = await check(str(clip), settings=load_settings())
    assert rep.issues[0].detail["temporal"]["frames"] >= 6
