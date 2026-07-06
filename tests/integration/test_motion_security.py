"""Security regressions for local motion decode (ffmpeg on untrusted bytes).

The exploit: ffmpeg picks its demuxer from file CONTENT, not extension. A file named
`evil.mp4` that actually holds an HLS/m3u8 playlist or an ffconcat script can make ffmpeg
dereference *other* URLs (SSRF) or local files (LFI). We close it two ways — a
`file`-only protocol whitelist and a demuxer allowlist — and pin both here.
"""

import subprocess

import pytest

from agentvision.config import load_settings
from agentvision.errors import RenderError
from agentvision.renderers.base import RenderSpec
from agentvision.renderers.motion import MotionRenderer, find_ffmpeg
from agentvision.sources import ResolvedSource

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not available")


async def test_m3u8_playlist_disguised_as_mp4_is_refused(tmp_path):
    """A .mp4 that is really an HLS playlist pointing at a remote URL must not be decoded."""
    evil = tmp_path / "evil.mp4"
    evil.write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:10,\n"
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/\n#EXT-X-ENDLIST\n"
    )
    r = MotionRenderer(load_settings())
    with pytest.raises(RenderError):  # refused at probe (bad demuxer / no video stream)
        await r.render_sequence(RenderSpec(source="x", source_type="motion"),
                                ResolvedSource(kind="motion", path=evil),
                                tmp_path / "out", frames=3)


async def test_ffconcat_lfi_disguised_as_mp4_is_refused(tmp_path):
    """An ffconcat script naming /etc/passwd must not cause ffmpeg to open it."""
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")
    evil = tmp_path / "evil.mp4"
    evil.write_text(f"ffconcat version 1.0\nfile '{secret}'\n")
    r = MotionRenderer(load_settings())
    with pytest.raises(RenderError):
        await r.render_sequence(RenderSpec(source="x", source_type="motion"),
                                ResolvedSource(kind="motion", path=evil),
                                tmp_path / "out", frames=3)


async def test_overall_time_budget_bounds_extraction(tmp_path):
    """A per-frame timeout alone lets stalls accumulate; the overall budget caps total work.

    We set render_timeout_s to 0 so the first extraction's remaining-budget check trips —
    proving the sequence is bounded by a wall-clock deadline, not just per-invocation.
    """
    clip = tmp_path / "ok.mp4"
    subprocess.run(
        [find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc=duration=2:size=96x64:rate=10", "-pix_fmt", "yuv420p", "-y", str(clip)],
        check=True, timeout=60,
    )
    r = MotionRenderer(load_settings(render_timeout_s=0.0))
    with pytest.raises(RenderError, match="overall"):
        await r.render_sequence(RenderSpec(source="x", source_type="motion"),
                                ResolvedSource(kind="motion", path=clip),
                                tmp_path / "out", frames=6)


async def test_legit_video_still_decodes(tmp_path):
    """The guards don't break a real clip (allowlist includes mp4/mov/webm/…)."""
    clip = tmp_path / "ok.mp4"
    subprocess.run(
        [find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc=duration=1:size=96x64:rate=10", "-pix_fmt", "yuv420p", "-y", str(clip)],
        check=True, timeout=60,
    )
    r = MotionRenderer(load_settings())
    frames = await r.render_sequence(RenderSpec(source="x", source_type="motion"),
                                     ResolvedSource(kind="motion", path=clip),
                                     tmp_path / "out", frames=4)
    assert len(frames) == 4
