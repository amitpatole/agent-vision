"""Renderer hardening regression tests (security batch 4).

Pins: viewport/device_scale are clamped (memory bound), the OS sandbox is on by default,
and watch() clamps caller-supplied frames/interval.
"""

import sys

from agentvision import load_settings
from agentvision.models.geometry import Viewport
from agentvision.renderers.playwright_renderer import PlaywrightRenderer


def test_clamp_viewport_and_scale():
    r = PlaywrightRenderer(load_settings())
    w, h, s = r._clamp(Viewport(width=50000, height=999999), 99.0)
    assert w == 8000 and h == 8000 and s == 4.0  # capped
    assert r._clamp(Viewport(width=1280, height=800), 2.0) == (1280, 800, 2.0)  # untouched


def test_sandbox_on_by_default():
    assert load_settings().chromium_sandbox is True


def test_no_sandbox_flag_only_when_disabled():
    # default args never contain --no-sandbox
    from agentvision.renderers.playwright_renderer import _LAUNCH_ARGS
    assert "--no-sandbox" not in _LAUNCH_ARGS


async def test_watch_clamps_frames_and_interval(monkeypatch):
    wm = sys.modules["agentvision.core.watch"]  # the module (not the re-exported function)
    rec = {}

    class FakeRenderer:
        async def render_sequence(self, spec, resolved, out_dir, *, frames, interval_ms):
            rec["frames"] = frames
            rec["interval"] = interval_ms
            return []

    monkeypatch.setattr(wm, "get_renderer", lambda kind, settings: FakeRenderer())
    await wm.watch("<html><body>x</body></html>", frames=100_000, interval_ms=10**9)
    assert rec["frames"] <= load_settings().watch_max_frames
    assert rec["interval"] <= load_settings().watch_max_interval_ms


async def test_render_clamps_giant_viewport(tmp_path):
    from agentvision.core import render

    res = await render("<html><body><h1>hi</h1></body></html>", settings=load_settings(),
                       viewports=[Viewport(width=20000, height=20000)], full_page=False)
    assert res.primary is not None
    assert res.primary.width <= 8000 and res.primary.height <= 8000
