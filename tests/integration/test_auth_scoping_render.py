"""Integration proof that the Authorization header is ORIGIN-SCOPED (Phase 3b, require Chromium).

Fable 5's blocker for Phase 1 was that `extra_http_headers` leaks a Bearer token to every
subresource origin. This proves the fix: the header reaches only the target origin, never a
cross-origin (different-port) host the page fetches from.
"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("playwright")

from agentvision import load_settings  # noqa: E402
from agentvision.core import render as do_render  # noqa: E402


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


class _Recorder(BaseHTTPRequestHandler):
    seen: dict = {}          # path -> Authorization header (or "")
    other_origin = ""        # set per-test: the cross-origin base URL the page will fetch

    def do_GET(self):  # noqa: N802
        type(self).seen[self.path] = self.headers.get("Authorization", "")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if self.path == "/":
            body = ("<html><body>ok<script>"
                    f"fetch('/same');fetch('{type(self).other_origin}/cross');"
                    "</script></body></html>")
            self.wfile.write(body.encode())

    def log_message(self, *a):
        pass


def _serve():
    srv = HTTPServer(("127.0.0.1", 0), _Recorder)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


async def test_bearer_header_is_same_origin_only(monkeypatch):
    target = _serve()      # the app we authenticate to
    third = _serve()       # a different origin (different port) the page fetches from
    _Recorder.seen = {}
    _Recorder.other_origin = f"http://127.0.0.1:{third.server_address[1]}"
    target_url = f"http://127.0.0.1:{target.server_address[1]}/"

    monkeypatch.setenv("AV_TEST_TOKEN", "Bearer scoped-secret-42")
    settings = load_settings(block_private_networks=False, auth_header_env="AV_TEST_TOKEN",
                             ephemeral=True, settle_ms=900)
    try:
        await do_render(target_url, settings=settings, source_type="url")
    finally:
        target.shutdown()
        third.shutdown()

    # Same origin (main navigation + the /same fetch) carries the token…
    assert _Recorder.seen.get("/") == "Bearer scoped-secret-42"
    assert _Recorder.seen.get("/same") == "Bearer scoped-secret-42"
    # …the cross-origin fetch does NOT (this is the leak that must not happen).
    assert _Recorder.seen.get("/cross", "") == ""
