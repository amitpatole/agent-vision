"""MotionRenderer — GIF sampling (no ffmpeg needed), guards, and the dead-export check."""

import pytest
from PIL import Image

from agentvision.config import load_settings
from agentvision.core.temporal import compute_temporal_checks
from agentvision.errors import RenderError
from agentvision.renderers.base import RenderSpec
from agentvision.renderers.motion import MotionRenderer
from agentvision.sources import ResolvedSource


def _animated_gif(path, n_frames=4, size=(60, 40), move=True):
    frames = []
    for i in range(n_frames):
        im = Image.new("RGB", size, "white")
        if move:
            box = (i * 10, 5, i * 10 + 8, 13)
            for x in range(box[0], min(box[2], size[0])):
                for y in range(box[1], box[3]):
                    im.putpixel((x, y), (200, 0, 0))
        else:
            # One corner pixel varies so PIL doesn't collapse identical frames into one;
            # a single changed pixel stays far below the motion epsilon (dead export).
            im.putpixel((size[0] - 1, size[1] - 1), (i * 40 % 255, 0, 0))
        frames.append(im)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=120, loop=0)


def _spec():
    return RenderSpec(source="x", source_type="motion")


async def test_gif_sampled_into_frames(tmp_path):
    gif = tmp_path / "anim.gif"
    _animated_gif(gif, n_frames=8)
    r = MotionRenderer(load_settings())
    frames = await r.render_sequence(_spec(), ResolvedSource(kind="motion", path=gif),
                                     tmp_path / "out", frames=4)
    assert len(frames) == 4
    assert [f.index for f in frames] == [0, 1, 2, 3]
    assert frames[0].t_ms == 0
    assert all(frames[i].t_ms < frames[i + 1].t_ms for i in range(len(frames) - 1))
    assert all(f.width == 60 and f.height == 40 for f in frames)


async def test_gif_animation_is_detected_as_moving(tmp_path):
    """The handover's core failure: motion must be sampled, not flattened to frame 0."""
    gif = tmp_path / "anim.gif"
    _animated_gif(gif, n_frames=6, move=True)
    r = MotionRenderer(load_settings())
    frames = await r.render_sequence(_spec(), ResolvedSource(kind="motion", path=gif),
                                     tmp_path / "out", frames=6)
    issues, signals = compute_temporal_checks(frames, expect_motion=True)
    assert signals["moving"] is True
    assert not [i for i in issues if i.detail.get("temporal") == "no_motion"]


async def test_dead_export_fails_deterministically(tmp_path):
    """An 'animated' GIF whose frames are identical is a dead export -> ERROR."""
    gif = tmp_path / "dead.gif"
    _animated_gif(gif, n_frames=5, move=False)
    r = MotionRenderer(load_settings())
    frames = await r.render_sequence(_spec(), ResolvedSource(kind="motion", path=gif),
                                     tmp_path / "out", frames=5)
    issues, signals = compute_temporal_checks(frames, expect_motion=True)
    assert signals["moving"] is False
    dead = [i for i in issues if i.detail.get("temporal") == "no_motion"]
    assert dead and dead[0].severity.value == "error"


async def test_static_page_watch_is_not_a_dead_export(tmp_path):
    """expect_motion=False (a watched page): static frames stay legitimate."""
    gif = tmp_path / "dead.gif"
    _animated_gif(gif, n_frames=3, move=False)
    r = MotionRenderer(load_settings())
    frames = await r.render_sequence(_spec(), ResolvedSource(kind="motion", path=gif),
                                     tmp_path / "out", frames=3)
    issues, _ = compute_temporal_checks(frames, expect_motion=False)
    assert not [i for i in issues if i.detail.get("temporal") == "no_motion"]


async def test_clean_loop_signal(tmp_path):
    """First ≈ last frame -> loops_cleanly=True (signal only, never a failure)."""
    frames_im = []
    for i in (0, 1, 0):  # A-B-A: returns to the first frame
        im = Image.new("RGB", (60, 40), "white")
        if i:
            for x in range(20):
                for y in range(20):
                    im.putpixel((x, y), (0, 0, 200))
        frames_im.append(im)
    gif = tmp_path / "loop.gif"
    frames_im[0].save(gif, save_all=True, append_images=frames_im[1:], duration=100, loop=0)
    r = MotionRenderer(load_settings())
    frames = await r.render_sequence(_spec(), ResolvedSource(kind="motion", path=gif),
                                     tmp_path / "out", frames=3)
    _, signals = compute_temporal_checks(frames, expect_motion=True)
    assert signals["moving"] is True
    assert signals["loops_cleanly"] is True


async def test_gate_fails_closed_when_disabled(tmp_path):
    """allow_motion_render=False (the REST posture) refuses with a clear error."""
    gif = tmp_path / "anim.gif"
    _animated_gif(gif)
    r = MotionRenderer(load_settings(allow_motion_render=False))
    with pytest.raises(RenderError, match="allow_motion_render"):
        await r.render_sequence(_spec(), ResolvedSource(kind="motion", path=gif),
                                tmp_path / "out", frames=3)


async def test_byte_cap_enforced(tmp_path):
    gif = tmp_path / "anim.gif"
    _animated_gif(gif)
    r = MotionRenderer(load_settings(max_document_bytes=10))
    with pytest.raises(RenderError, match="byte cap"):
        await r.render_sequence(_spec(), ResolvedSource(kind="motion", path=gif),
                                tmp_path / "out", frames=3)


async def test_truncated_gif_fails_cleanly(tmp_path):
    """A corrupt/truncated GIF surfaces a RenderError (CLI exit 3), not a raw traceback."""
    gif = tmp_path / "anim.gif"
    _animated_gif(gif, n_frames=6)
    data = bytearray(gif.read_bytes())
    gif.write_bytes(data[: len(data) // 2])  # cut it in half mid-stream
    r = MotionRenderer(load_settings())
    with pytest.raises(RenderError):
        await r.render_sequence(_spec(), ResolvedSource(kind="motion", path=gif),
                                tmp_path / "out", frames=4)


async def test_missing_ffmpeg_is_actionable(tmp_path, monkeypatch):
    """Video without ffmpeg fails closed with install guidance, not a stack trace."""
    import agentvision.renderers.motion as motion_mod

    monkeypatch.setattr(motion_mod, "find_ffmpeg", lambda: None)
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"\x00" * 64)
    r = MotionRenderer(load_settings())
    from agentvision.errors import MissingDependencyError

    with pytest.raises(MissingDependencyError, match="ffmpeg"):
        await r.render_sequence(_spec(), ResolvedSource(kind="motion", path=mp4),
                                tmp_path / "out", frames=3)
