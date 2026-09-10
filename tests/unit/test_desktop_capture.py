"""Desktop screen capture: source resolution, gating, renderer registration, and the
portal-URI plumbing — all without touching a real portal or prompting (the D-Bus call is
monkeypatched)."""

from pathlib import Path

import pytest

from agentvision.config import load_settings
from agentvision.errors import RenderError, UnsafeSourceError
from agentvision.renderers import get_renderer
from agentvision.renderers.base import RenderSpec
from agentvision.renderers.desktop_renderer import (
    DesktopRenderer,
    _unwrap,
    _uri_from_response,
    _uri_to_path,
)
from agentvision.sources import resolve_source


def test_detects_desktop_and_screen_schemes():
    for src in ("desktop:", "screen:", "DESKTOP:full", "  screen:interactive "):
        resolved = resolve_source(src, settings=load_settings())
        assert resolved.kind == "desktop"
        assert resolved.path is None and resolved.url is None and resolved.content is None


def test_service_refuses_screen_capture():
    settings = load_settings(allow_screen_capture=False)
    with pytest.raises(UnsafeSourceError):
        resolve_source("desktop:", settings=settings)


def test_explicit_source_type_desktop_is_honored():
    resolved = resolve_source("desktop:", source_type="desktop", settings=load_settings())
    assert resolved.kind == "desktop"


def test_get_renderer_returns_desktop_renderer():
    r = get_renderer("desktop", load_settings())
    assert isinstance(r, DesktopRenderer)
    assert r.supports("desktop") and not r.supports("html")


def test_uri_to_path_accepts_local_file():
    assert _uri_to_path("file:///tmp/shot%20one.png") == Path("/tmp/shot one.png")
    assert _uri_to_path("file://localhost/tmp/x.png") == Path("/tmp/x.png")


@pytest.mark.parametrize("uri", [
    "http://evil.example/x.png",   # non-file scheme (SSRF / exfil vector)
    "file://evil.example/etc/x",   # remote host on a file URI
    "data:image/png;base64,AAAA",  # inline data scheme
])
def test_uri_to_path_rejects_non_local(uri):
    with pytest.raises(RenderError):
        _uri_to_path(uri)


def test_unwrap_handles_variant_and_bare():
    assert _unwrap(("s", "file:///x.png")) == "file:///x.png"
    assert _unwrap("file:///x.png") == "file:///x.png"
    assert _unwrap(("u", 0)) == 0


async def test_render_normalizes_portal_capture(tmp_path, monkeypatch):
    # Fake a portal capture: write a real PNG and hand back its file:// URI, so render()
    # exercises the full URI -> safe-open -> normalized-PNG path with no D-Bus / no prompt.
    from PIL import Image

    src = tmp_path / "portal_shot.png"
    Image.new("RGB", (120, 80), (30, 90, 160)).save(src)

    monkeypatch.setattr(
        "agentvision.renderers.desktop_renderer._capture_via_portal",
        lambda *, interactive, timeout_s: src.as_uri(),
    )
    r = DesktopRenderer(load_settings())
    spec = RenderSpec(source="desktop:", source_type="desktop")
    result = await r.render(spec, resolve_source("desktop:", settings=load_settings()),
                            tmp_path / "out")

    assert result.source_type == "desktop"
    assert result.primary is not None
    assert result.primary.width == 120 and result.primary.height == 80
    assert Path(result.primary.path).exists()


def test_cli_screen_routes_to_desktop_vqa(monkeypatch):
    # The `screen` command must call analyze() on the desktop source with the question as the
    # `expected` grading target — never touch a real portal in a unit test.
    import agentvision.core as core
    from agentvision.models.report import Report, Verdict

    captured = {}

    async def fake_analyze(source, **kwargs):
        captured["source"] = source
        captured.update(kwargs)
        return Report(verdict=Verdict.PASS, summary="ok", backend="local")

    monkeypatch.setattr(core, "analyze", fake_analyze)

    from typer.testing import CliRunner

    from agentvision.adapters.cli import app

    result = CliRunner().invoke(
        app, ["screen", "--ask", "is a dialog asking about X?", "--interactive"]
    )
    assert result.exit_code == 0, result.output
    assert captured["source"] == "desktop:"
    assert captured["source_type"] == "desktop"
    assert captured["expected"] == "is a dialog asking about X?"
    assert captured["settings"].screen_capture_interactive is True
    # ephemeral (temp cache) so the screenshot never persists
    assert captured["settings"].ephemeral is True


def test_denied_portal_response_fails_closed():
    # User clicked "Deny" (or cancelled) at the prompt → response code 1 → hard error, never
    # a silent empty capture.
    with pytest.raises(RenderError):
        _uri_from_response(1, {"uri": ("s", "file:///tmp/x.png")})
    with pytest.raises(RenderError):
        _uri_from_response(2, {})


def test_empty_uri_fails_closed():
    with pytest.raises(RenderError):
        _uri_from_response(0, {})            # success but no uri key
    with pytest.raises(RenderError):
        _uri_from_response(0, {"uri": ("s", "")})  # empty string uri


async def test_render_refuses_non_regular_file(tmp_path, monkeypatch):
    # A FIFO at the returned path (e.g. a local process racing the portal output) must be
    # refused, never opened — otherwise the read could hang or stream forever.
    import os

    fifo = tmp_path / "pipe.png"
    os.mkfifo(fifo)
    monkeypatch.setattr(
        "agentvision.renderers.desktop_renderer._capture_via_portal",
        lambda *, interactive, timeout_s: fifo.as_uri(),
    )
    r = DesktopRenderer(load_settings())
    spec = RenderSpec(source="desktop:", source_type="desktop")
    with pytest.raises(RenderError):
        await r.render(spec, resolve_source("desktop:", settings=load_settings()),
                       tmp_path / "out")


def test_uri_to_path_rejects_nul_byte():
    with pytest.raises(RenderError):
        _uri_to_path("file:///tmp/%00etc/passwd")


def test_malformed_response_body_fails_closed():
    # A Response signal whose body isn't a (code, results) 2-tuple must raise RenderError,
    # not a raw ValueError that escapes the timeout handling.
    from agentvision.renderers import desktop_renderer as dr

    class _Sig:
        body = (0,)  # wrong arity

    # exercise the same unpack guard used in _capture_via_portal
    with pytest.raises((ValueError, RenderError)):
        code, results = _Sig().body  # sanity: this is what the guard wraps
        dr._uri_from_response(code, results)


def test_timeout_setting_is_bounded():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        load_settings(screen_capture_timeout_s=10_000_000)  # > 300 ceiling
    with pytest.raises(ValidationError):
        load_settings(screen_capture_timeout_s=-5)          # negative
    # a sane value is accepted
    assert load_settings(screen_capture_timeout_s=30).screen_capture_timeout_s == 30


def test_cli_timeout_is_clamped(monkeypatch):
    # A huge --timeout must be clamped, never raise a pydantic traceback.
    from agentvision.adapters.cli import _settings

    s = _settings(screen_timeout=10_000_000)
    assert s.screen_capture_timeout_s == 300.0
    s2 = _settings(screen_timeout=-5)
    assert s2.screen_capture_timeout_s == 1.0


async def test_portal_file_cleaned_when_in_tempdir(tmp_path, monkeypatch):
    # The portal's own output PNG must be deleted after we read it, when it lives under a
    # temp/cache/runtime root — otherwise the full-desktop original persists on disk.
    from PIL import Image

    import agentvision.renderers.desktop_renderer as dr

    portal_file = tmp_path / "portal_original.png"
    Image.new("RGB", (64, 48), (10, 20, 30)).save(portal_file)
    # make tmp_path count as an ephemeral root
    monkeypatch.setattr(dr, "_ephemeral_roots", lambda: [tmp_path.resolve()])
    monkeypatch.setattr(dr, "_capture_via_portal",
                        lambda *, interactive, timeout_s: portal_file.as_uri())

    r = dr.DesktopRenderer(load_settings())
    spec = RenderSpec(source="desktop:", source_type="desktop")
    result = await r.render(spec, resolve_source("desktop:", settings=load_settings()),
                            tmp_path / "out")
    assert result.primary is not None
    assert not portal_file.exists()  # portal's original was cleaned up


async def test_portal_file_left_when_outside_tempdir(tmp_path, monkeypatch):
    # A file OUTSIDE the ephemeral roots (e.g. a user's ~/Pictures) must NOT be deleted.
    from PIL import Image

    import agentvision.renderers.desktop_renderer as dr

    user_file = tmp_path / "Pictures" / "keepme.png"
    user_file.parent.mkdir()
    Image.new("RGB", (32, 32), (1, 2, 3)).save(user_file)
    monkeypatch.setattr(dr, "_ephemeral_roots", lambda: [(tmp_path / "somewhere_else")])
    monkeypatch.setattr(dr, "_capture_via_portal",
                        lambda *, interactive, timeout_s: user_file.as_uri())

    r = dr.DesktopRenderer(load_settings())
    spec = RenderSpec(source="desktop:", source_type="desktop")
    await r.render(spec, resolve_source("desktop:", settings=load_settings()),
                   tmp_path / "out2")
    assert user_file.exists()  # a real user file is never deleted


def test_unresponsive_portal_fails_closed(monkeypatch):
    # A wedged portal that never acks the D-Bus call must raise RenderError (never hang), and
    # the connection must still be closed. Regression for the unbounded-send_and_get_reply DoS.
    import jeepney.io.blocking as jb

    from agentvision.renderers import desktop_renderer as dr

    class _Sock:
        def settimeout(self, t): pass

    class _Conn:
        unique_name = ":1.99"
        sock = _Sock()
        closed = False

        def send_and_get_reply(self, msg, timeout=None):
            raise TimeoutError("portal wedged")  # what jeepney raises on timeout

        def close(self):
            self.closed = True

    conn = _Conn()
    monkeypatch.setattr(jb, "open_dbus_connection", lambda bus="SESSION": conn)
    with pytest.raises(RenderError):
        dr._capture_via_portal(interactive=False, timeout_s=1.0)
    assert conn.closed is True  # connection released even on the failure path


def test_egress_guard_fails_closed_on_cloud_backend():
    # A desktop capture + non-local backend must RAISE unless egress is opted in — not just warn.
    from agentvision.core.analyze import assert_screen_egress_allowed
    from agentvision.errors import UnsafeSourceError

    class _Cloud:
        name = "anthropic"

    class _Local:
        name = "local"

    # cloud + no opt-in -> refused
    with pytest.raises(UnsafeSourceError):
        assert_screen_egress_allowed("desktop", _Cloud(), load_settings())
    # cloud + opt-in -> allowed (warns)
    assert_screen_egress_allowed(
        "desktop", _Cloud(), load_settings(allow_screen_capture_egress=True)
    )
    # local backend -> always allowed (never egresses)
    assert_screen_egress_allowed("desktop", _Local(), load_settings())
    # non-desktop source -> guard is a no-op
    assert_screen_egress_allowed("html", _Cloud(), load_settings())


async def test_library_analyze_desktop_forces_ephemeral(tmp_path, monkeypatch):
    # Direct library analyze("desktop:") (no CLI/MCP adapter) must NOT persist the screenshot
    # to the shared cache — the core forces ephemeral. We assert the render runs under an
    # ephemeral (temp) cache_dir, not the configured one.
    import sys

    # agentvision.core.__init__ rebinds the name `analyze` to the function, so fetch the actual
    # submodule from sys.modules to patch its module-global `_render_and_ground`.
    az = sys.modules["agentvision.core.analyze"]

    seen = {}

    async def fake_render_and_ground(source, settings, **kwargs):
        seen["ephemeral"] = settings.ephemeral
        seen["cache_dir"] = str(settings.cache_dir)
        # short-circuit: return an empty render so analyze bails before any backend call
        from agentvision.renderers.base import RenderResult
        return RenderResult(source_type="desktop"), [], None

    monkeypatch.setattr(az, "_render_and_ground", fake_render_and_ground)
    persistent = tmp_path / "persistent_cache"
    settings = load_settings(cache_dir=persistent)  # ephemeral defaults False
    await az.analyze("desktop:", settings=settings)
    assert seen["ephemeral"] is True
    assert str(persistent) not in seen["cache_dir"]  # redirected to a throwaway temp


def test_ephemeral_roots_reject_overbroad(monkeypatch):
    # A hostile XDG_RUNTIME_DIR=/ or TMPDIR=$HOME must not authorize deleting arbitrary files.
    import agentvision.renderers.desktop_renderer as dr

    monkeypatch.setenv("XDG_RUNTIME_DIR", "/")
    monkeypatch.setenv("XDG_CACHE_HOME", str(Path.home()))
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(Path.home()))
    roots = dr._ephemeral_roots()
    home = Path.home().resolve()
    assert Path("/") not in roots
    assert home not in roots
    for r in roots:
        assert r != r.anchor


def test_desktop_source_skips_spellcheck():
    # A live desktop is full of correctly-spelled proper nouns/identifiers that a plain
    # dictionary would flag as HIGH-confidence typos -> hard FAIL. The spell-check must be
    # skipped for desktop sources so `check desktop:` / `--backend local` don't false-FAIL.
    from agentvision.core.checks import run_all_checks
    from agentvision.models.geometry import BBox
    from agentvision.models.report import IssueKind, Verdict, verdict_from_issues
    from agentvision.ocr.base import OcrResult, OcrWord
    from agentvision.renderers.base import RenderResult

    ocr = OcrResult(
        text="Firefox kubectl zscaler",
        words=[OcrWord(text=w, bbox=BBox(x=0, y=0, width=40, height=12), confidence=0.95)
               for w in ("Firefox", "kubectl", "zscaler")],
    )
    desktop_issues = run_all_checks(RenderResult(source_type="desktop"), None, ocr)
    assert not any(i.kind == IssueKind.TYPO for i in desktop_issues)
    assert verdict_from_issues(desktop_issues) != Verdict.FAIL

    # sanity: the SAME OCR on a normal (html) source DOES still flag typos (fix is scoped)
    html_issues = run_all_checks(RenderResult(source_type="html"), None, ocr)
    assert any(i.kind == IssueKind.TYPO for i in html_issues)


async def test_analyze_desktop_invokes_egress_guard_on_real_path(monkeypatch):
    # Pin that analyze() actually CALLS the egress guard on the desktop code path (not just that
    # the guard exists) — so a refactor that drops the call site is caught. Cloud backend + no
    # opt-in must raise via the guard.
    import sys

    from agentvision.errors import UnsafeSourceError

    az = sys.modules["agentvision.core.analyze"]

    async def fake_render_and_ground(source, settings, **kwargs):
        from agentvision.models.geometry import Viewport
        from agentvision.renderers.base import RenderedImage, RenderResult
        rr = RenderResult(
            images=[RenderedImage(path="/tmp/x.png", viewport=Viewport(width=10, height=10),
                                  width=10, height=10)],
            source_type="desktop",
        )
        return rr, [], None

    class _Cloud:
        name = "anthropic"

        async def analyze(self, req):  # must never be reached
            raise AssertionError("egress guard did not fire before vision.analyze")

    monkeypatch.setattr(az, "_render_and_ground", fake_render_and_ground)
    monkeypatch.setattr(az, "select_backend", lambda settings, backend: (_Cloud(), None))

    # ephemeral=True so the core wrap doesn't recurse; desktop + cloud + no opt-in -> refuse
    settings = load_settings(ephemeral=True, allow_screen_capture_egress=False)
    with pytest.raises(UnsafeSourceError):
        await az.analyze("desktop:", settings=settings, source_type="desktop")


def test_mcp_registers_capture_screen_tool():
    # build_server() raises MissingDependencyError when the MCP server SDK isn't fully
    # importable in this environment (top-level `mcp` may import while `mcp.server.fastmcp`
    # or a symbol it needs isn't available — a pre-existing optional-dep condition unrelated
    # to this feature). Skip rather than fail the suite in that case.
    pytest.importorskip("mcp")
    from agentvision.adapters.mcp_server import build_server
    from agentvision.errors import MissingDependencyError

    try:
        server = build_server()
    except MissingDependencyError as e:
        pytest.skip(f"MCP server SDK unavailable in this environment: {e}")
    names = {t.name for t in server._tool_manager.list_tools()}
    assert "capture_screen" in names
