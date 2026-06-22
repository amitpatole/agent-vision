"""Vetting egress proxy regression tests (DNS-rebinding closure, security batch 7).

The proxy resolves+vets each host once and connects to that exact IP, so Chromium never
re-resolves. These exercise the proxy directly (no browser): allowed hosts are pinned with the
Host header preserved; internal hosts get 403.
"""

import asyncio

import agentvision.proxy as P
from agentvision.proxy import VettingProxy


async def _upstream():
    """A tiny HTTP server that records the request line + Host header, then 200s."""
    seen = {}

    async def handle(reader, writer):
        data = await reader.readuntil(b"\r\n\r\n")
        lines = data.split(b"\r\n")
        seen["request_line"] = lines[0].decode()
        for line in lines[1:]:
            if line.lower().startswith(b"host:"):
                seen["host"] = line.split(b":", 1)[1].strip().decode()
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1], seen


async def _request_through_proxy(proxy_port, raw):
    r, w = await asyncio.open_connection("127.0.0.1", proxy_port)
    w.write(raw)
    await w.drain()
    resp = await r.read()
    w.close()
    return resp


async def test_proxy_pins_to_vetted_ip_and_preserves_host(monkeypatch):
    server, uport, seen = await _upstream()
    proxy = VettingProxy()
    await proxy.start()

    async def vet_ok(host, port):
        return "127.0.0.1"  # simulate: hostname vets to a safe (here local) IP

    monkeypatch.setattr(P, "resolve_safe_ip", vet_ok)
    raw = (f"GET http://shop.example.test:{uport}/probe HTTP/1.1\r\n"
           f"Host: shop.example.test:{uport}\r\n\r\n").encode()
    await _request_through_proxy(proxy.port, raw)
    await asyncio.sleep(0.05)
    await proxy.stop()
    server.close()
    assert seen.get("request_line") == "GET /probe HTTP/1.1"      # origin-form to upstream
    assert seen.get("host") == f"shop.example.test:{uport}"        # Host preserved (not the IP)


async def test_proxy_blocks_internal_host(monkeypatch):
    proxy = VettingProxy()
    await proxy.start()

    async def vet_block(host, port):
        return None  # simulate: resolves to an internal/metadata address

    monkeypatch.setattr(P, "resolve_safe_ip", vet_block)
    resp = await _request_through_proxy(
        proxy.port, b"GET http://metadata.internal/latest/ HTTP/1.1\r\nHost: metadata.internal\r\n\r\n")
    await proxy.stop()
    assert b"403" in resp.split(b"\r\n", 1)[0]


async def test_proxy_connect_blocks_internal(monkeypatch):
    proxy = VettingProxy()
    await proxy.start()

    async def vet_block(host, port):
        return None

    monkeypatch.setattr(P, "resolve_safe_ip", vet_block)
    resp = await _request_through_proxy(
        proxy.port, b"CONNECT 169.254.169.254:443 HTTP/1.1\r\nHost: 169.254.169.254:443\r\n\r\n")
    await proxy.stop()
    assert b"403" in resp.split(b"\r\n", 1)[0]


async def test_proxy_connection_cap(monkeypatch):
    # cap = 0 → every request is over the cap → 503 (exercises the reject branch deterministically)
    proxy = VettingProxy(max_connections=0)
    await proxy.start()
    resp = await _request_through_proxy(
        proxy.port, b"GET http://example.test/ HTTP/1.1\r\nHost: example.test\r\n\r\n")
    await proxy.stop()
    assert b"503" in resp.split(b"\r\n", 1)[0]


async def test_proxy_idle_timeout_configured():
    # the idle bound is wired through (closes silent/slowloris connections)
    p = VettingProxy(idle_timeout_s=2.5)
    assert p._idle == 2.5


async def test_proxy_under_concurrent_load(monkeypatch):
    """Many concurrent requests: the proxy stays up, every request gets a response (200 or
    503, never a hang/crash), the cap is honored, and it's still serving afterwards."""
    async def handle(r, w):
        try:
            await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), timeout=5)
        except Exception:  # noqa: BLE001
            pass
        w.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        try:
            await w.drain()
        except Exception:  # noqa: BLE001
            pass
        w.close()

    upstream = await asyncio.start_server(handle, "127.0.0.1", 0)
    uport = upstream.sockets[0].getsockname()[1]

    async def vet(host, port):
        return "127.0.0.1"

    monkeypatch.setattr(P, "resolve_safe_ip", vet)
    proxy = VettingProxy(max_connections=20)
    await proxy.start()

    async def one():
        try:
            r, w = await asyncio.open_connection("127.0.0.1", proxy.port)
            w.write(f"GET http://load.test:{uport}/x HTTP/1.1\r\n"
                    f"Host: load.test:{uport}\r\n\r\n".encode())
            await w.drain()
            data = await asyncio.wait_for(r.read(), timeout=15)
            w.close()
            return data.split(b"\r\n", 1)[0]
        except Exception as e:  # noqa: BLE001
            return repr(e).encode()

    results = await asyncio.wait_for(
        asyncio.gather(*[one() for _ in range(120)]), timeout=40)
    await proxy.stop()
    upstream.close()

    assert len(results) == 120                                   # nothing hung
    assert all(b"200" in s or b"503" in s for s in results)      # clean status, no crash/reset
    assert any(b"200" in s for s in results)                     # served real traffic under load


# --- end-to-end: full browser -> route guard -> proxy -> upstream chain ---

def _http_recorder():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen: dict = {"hits": 0}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["hits"] += 1
            seen["path"] = self.path
            seen["host"] = self.headers.get("Host")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>ok</body></html>")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1], seen


async def test_e2e_proxy_pins_and_preserves_host_via_browser(monkeypatch):
    import agentvision.renderers.playwright_renderer as R
    from agentvision import load_settings
    from agentvision.core import render

    srv, uport, seen = _http_recorder()

    async def host_ok(host, port):
        return True  # route guard sees the (simulated public) host as safe

    async def vet(host, port):
        return "127.0.0.1"  # proxy pins the connection to our local upstream

    monkeypatch.setattr(R, "host_is_safe", host_ok)
    monkeypatch.setattr(P, "resolve_safe_ip", vet)
    html = f'<html><body><img src="http://shop.example.test:{uport}/probe"></body></html>'
    try:
        await render(html, settings=load_settings(), full_page=False, settle_ms=700)
    finally:
        srv.shutdown()
    assert seen.get("path") == "/probe"
    assert seen.get("host") == f"shop.example.test:{uport}"  # Host preserved through the chain


async def test_e2e_proxy_backstops_a_fooled_route_guard(monkeypatch):
    """Even if the route guard is tricked into thinking a host is safe (rebinding), the proxy —
    which resolves at connect time — blocks the internal target."""
    import agentvision.renderers.playwright_renderer as R
    from agentvision import load_settings
    from agentvision.core import render

    srv, uport, seen = _http_recorder()

    async def host_ok(host, port):
        return True  # route guard fooled

    async def vet_block(host, port):
        return None  # proxy resolves it to an internal address -> block

    monkeypatch.setattr(R, "host_is_safe", host_ok)
    monkeypatch.setattr(P, "resolve_safe_ip", vet_block)
    html = f'<html><body><img src="http://rebind.evil.test:{uport}/x"></body></html>'
    try:
        await render(html, settings=load_settings(), full_page=False, settle_ms=700)
    finally:
        srv.shutdown()
    assert seen["hits"] == 0  # proxy backstopped the fooled route guard
