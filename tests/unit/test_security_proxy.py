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
