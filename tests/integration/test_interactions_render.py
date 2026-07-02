"""Integration tests for Phase-1 auth + interaction (require Chromium; auto-skipped else).

Empirically proves the security-relevant behaviours, not just that the code runs:
  * a bad step fails CLOSED (InteractionError) — never grades the pre-interaction state;
  * a supplied session on a login wall raises AuthExpiredError — never grades the login page;
  * interactions are READ-ONLY by default — a click that fires a POST is aborted, and only
    delivered when the caller explicitly opts in with allow_mutations.
"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("playwright")

from agentvision import load_settings  # noqa: E402
from agentvision.core import render as do_render  # noqa: E402
from agentvision.errors import AuthExpiredError, InteractionError  # noqa: E402
from agentvision.models.interaction import Interaction  # noqa: E402


def _chromium_ok() -> bool:
    import asyncio

    async def _t():
        from playwright.async_api import async_playwright
        try:
            async with async_playwright() as pw:
                b = await pw.chromium.launch(
                    headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
                await b.close()
            return True
        except Exception:
            return False

    return asyncio.run(_t())


pytestmark = pytest.mark.skipif(not _chromium_ok(), reason="Chromium not launchable")

# A page with a popup revealed only after clicking the button.
_POPUP_HTML = (
    "<html><body><button id='open'>open</button>"
    "<div id='popup' style='display:none'>METRICS 42</div>"
    "<script>document.getElementById('open').onclick=function(){"
    "document.getElementById('popup').style.display='block';};</script></body></html>"
)

_LOGIN_HTML = ("<html><body><form><input type='password' id='pw'>"
               "<button>Sign in</button></form></body></html>")


async def test_interaction_reveals_popup():
    # click then wait_for the popup to be VISIBLE. If the click didn't reveal it, wait_for
    # would time out and raise — so a clean render proves the interaction reached the state.
    settings = load_settings(interactions=[
        Interaction(type="click", selector="#open"),
        Interaction(type="wait_for", selector="#popup"),
    ])
    res = await do_render(_POPUP_HTML, settings=settings, source_type="html")
    assert res.primary is not None
    kinds = [s.type for s in res.interaction_log]
    assert kinds == ["click", "wait_for"]
    assert all(s.ok for s in res.interaction_log)


async def test_bad_step_fails_closed():
    settings = load_settings(interactions=[Interaction(type="click", selector="#nope")])
    with pytest.raises(InteractionError):
        await do_render(_POPUP_HTML, settings=settings, source_type="html")


async def test_login_wall_with_session_raises(tmp_path):
    state = tmp_path / "state.json"
    state.write_text('{"cookies": [], "origins": []}')
    settings = load_settings(storage_state=state, ephemeral=True)
    with pytest.raises(AuthExpiredError):
        await do_render(_LOGIN_HTML, settings=settings, source_type="html")


# --- read-only-by-default: a click that POSTs is blocked unless opted in ----------------

class _CountingHandler(BaseHTTPRequestHandler):
    posts = 0

    def _html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        body = ("<html><body><button id='go'>go</button><script>"
                "document.getElementById('go').onclick=function(){"
                "fetch('/submit',{method:'POST'});};</script></body></html>")
        self.wfile.write(body.encode())

    def do_GET(self):  # noqa: N802
        self._html()

    def do_POST(self):  # noqa: N802
        type(self).posts += 1
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):  # silence
        pass


@pytest.fixture()
def local_server():
    _CountingHandler.posts = 0
    srv = HTTPServer(("127.0.0.1", 0), _CountingHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/"
    finally:
        srv.shutdown()


async def _click_and_wait(url, *, allow_mutations):
    # block_private_networks=False so loopback isn't blocked as a private host — this test
    # isolates the MUTATION guard specifically (not the SSRF guard).
    settings = load_settings(
        block_private_networks=False, allow_mutations=allow_mutations,
        interactions=[Interaction(type="click", selector="#go"),
                      Interaction(type="wait_timeout", ms=800)],
    )
    res = await do_render(url, settings=settings, source_type="url")
    return res


async def test_click_post_blocked_by_default(local_server):
    res = await _click_and_wait(local_server, allow_mutations=False)
    blocked = sum(s.blocked_mutations for s in res.interaction_log)
    assert blocked >= 1, "the POST should have been aborted by the read-only guard"
    assert _CountingHandler.posts == 0, "no write should have reached the server"


async def test_click_post_allowed_when_opted_in(local_server):
    res = await _click_and_wait(local_server, allow_mutations=True)
    assert sum(s.blocked_mutations for s in res.interaction_log) == 0
    assert _CountingHandler.posts >= 1, "opt-in should deliver the POST"
