"""Vetting egress proxy — the definitive close for the DNS-rebinding race.

Chromium is launched with ``--proxy-server`` pointing here, so EVERY outbound request (plain
HTTP via absolute-form, HTTPS/WSS via CONNECT, WS) flows through this proxy. The proxy resolves
each host **once**, vets the resolved IP against the SSRF policy (:mod:`agentvision.netguard`),
and connects to **that exact IP**. Chromium never resolves the host itself, so there is no
second lookup to rebind — the TOCTOU window is gone. The original ``Host`` header / TLS SNI are
preserved because the client still speaks to the original hostname over the tunnel; only the
TCP connection is pinned to the vetted address.

Pure asyncio, loopback-bound, one short-lived instance per render. Internal targets get 403.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from .logging import get_logger
from .netguard import resolve_safe_ip

log = get_logger("proxy")


class VettingProxy:
    def __init__(self, host: str = "127.0.0.1"):
        self._host = host
        self._server: asyncio.AbstractServer | None = None
        self.port: int = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self._host, 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=15)
        except Exception:  # noqa: BLE001 (timeout / incomplete / overrun)
            return await _close(writer)
        first, _, rest = head.partition(b"\r\n")
        try:
            method, target, _version = first.split(b" ", 2)
        except ValueError:
            return await _reply_close(writer, b"400 Bad Request")

        if method.upper() == b"CONNECT":  # https / wss tunnel
            host, _, port_b = target.rpartition(b":")
            try:
                port = int(port_b or b"443")
            except ValueError:
                return await _reply_close(writer, b"400 Bad Request")
            await self._tunnel(reader, writer, host.decode("latin1"), port)
        else:  # plain HTTP, absolute-form request line
            u = urlsplit(target.decode("latin1"))
            if u.scheme != "http" or not u.hostname:
                return await _reply_close(writer, b"400 Bad Request")
            await self._http(reader, writer, u.hostname, u.port or 80, method,
                             u.path or "/", u.query, rest)

    async def _vet(self, host: str, port: int) -> str | None:
        return await resolve_safe_ip(host, port)

    async def _tunnel(self, reader, writer, host: str, port: int) -> None:
        ip = await self._vet(host, port)
        if ip is None:
            return await _reply_close(writer, b"403 Forbidden")
        try:
            up_r, up_w = await asyncio.open_connection(ip, port)
        except Exception:  # noqa: BLE001
            return await _reply_close(writer, b"502 Bad Gateway")
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await _pipe(reader, writer, up_r, up_w)

    async def _http(self, reader, writer, host, port, method, path, query, header_block) -> None:
        ip = await self._vet(host, port)
        if ip is None:
            return await _reply_close(writer, b"403 Forbidden")
        try:
            up_r, up_w = await asyncio.open_connection(ip, port)
        except Exception:  # noqa: BLE001
            return await _reply_close(writer, b"502 Bad Gateway")
        origin = path + (("?" + query) if query else "")
        out = [method + b" " + origin.encode("latin1") + b" HTTP/1.1"]
        for line in header_block.split(b"\r\n"):
            if not line:
                continue
            low = line.lower()
            if low.startswith(b"proxy-connection:") or low.startswith(b"connection:"):
                continue
            out.append(line)
        out.append(b"Connection: close")
        up_w.write(b"\r\n".join(out) + b"\r\n\r\n")
        await up_w.drain()
        await _pipe(reader, writer, up_r, up_w)


async def _pipe(c_r, c_w, u_r, u_w) -> None:
    async def copy(src, dst):
        try:
            while True:
                data = await src.read(65536)
                if not data:
                    break
                dst.write(data)
                await dst.drain()
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                dst.close()
            except Exception:  # noqa: BLE001
                pass

    await asyncio.gather(copy(c_r, u_w), copy(u_r, c_w))


async def _reply_close(writer, status: bytes) -> None:
    try:
        writer.write(b"HTTP/1.1 " + status + b"\r\nConnection: close\r\n\r\n")
        await writer.drain()
    except Exception:  # noqa: BLE001
        pass
    await _close(writer)


async def _close(writer) -> None:
    try:
        writer.close()
    except Exception:  # noqa: BLE001
        pass
