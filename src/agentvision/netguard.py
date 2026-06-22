"""Network safety policy — the single source of truth for SSRF defense.

Used at two points so the check can't be bypassed:
- **resolve-time** (`assert_host_safe`, sync) — reject obviously-internal URLs early with a
  helpful CLI message;
- **fetch-time** (`host_is_safe`, async) — re-resolved inside the renderer's route guard for
  *every* request (top-level navigation, every subresource, and redirect target), which is
  what actually defeats DNS-rebinding, hostname-that-resolves-internally, and redirect-to-LAN.

A blocked address is any private / loopback / link-local / reserved / multicast / unspecified
range, the well-known cloud-metadata endpoints, or an unparseable host. IPv4-mapped IPv6
(`::ffff:a.b.c.d`) is normalized before classification so it can't smuggle a link-local /
metadata address past the range checks.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket

from .errors import UnsafeSourceError

ALLOWED_SCHEMES = ("http", "https")

# Cloud-metadata endpoints — defense-in-depth beyond the range checks.
_METADATA = {
    "169.254.169.254",      # AWS / GCP / Azure / OpenStack IMDS
    "fd00:ec2::254",        # AWS IMDS over IPv6
    "100.100.100.200",      # Alibaba Cloud
}

# Ranges not flagged by ipaddress's is_private but routed internally on some fabrics.
_EXTRA_BLOCKED = [
    ipaddress.ip_network("100.64.0.0/10"),   # carrier-grade NAT (RFC 6598)
]


def _normalize(ip: ipaddress.IPv4Address | ipaddress.IPv6Address):
    """Collapse IPv4-mapped IPv6 to its IPv4 form so range checks classify it correctly."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def ip_is_blocked(addr: str) -> bool:
    """True if a literal address string is internal / metadata / unparseable (fail closed)."""
    try:
        ip = _normalize(ipaddress.ip_address(addr))
    except ValueError:
        return True
    if str(ip) in _METADATA or addr in _METADATA:
        return True
    if any(ip in net for net in _EXTRA_BLOCKED):
        return True
    return bool(
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def _is_literal_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def assert_host_safe(host: str | None, port: int | None) -> None:
    """Resolve-time SSRF check (sync). Raise :class:`UnsafeSourceError` if internal.

    The message names the (caller-supplied) host but never the resolved IP — disclosing the
    resolved address would turn the service into an SSRF/port oracle.
    """
    if not host:
        raise UnsafeSourceError("URL has no host.")
    blocked_msg = (
        f"Refusing to render {host!r}: resolves to a non-public address (SSRF protection). "
        "To allow a localhost / LAN dev server, pass --allow-local (CLI) or set "
        "AGENTVISION_BLOCK_PRIVATE_NETWORKS=false."
    )
    if _is_literal_ip(host):
        if ip_is_blocked(host):
            raise UnsafeSourceError(blocked_msg)
        return
    try:
        infos = socket.getaddrinfo(host, port or 80, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeSourceError(f"Could not resolve host {host!r} (SSRF protection).") from e
    if any(ip_is_blocked(str(info[4][0])) for info in infos):
        raise UnsafeSourceError(blocked_msg)


async def host_is_safe(host: str | None, port: int | None) -> bool:
    """Fetch-time SSRF check (async, non-blocking) for the renderer route guard.

    Re-resolves the hostname at request time so a name that points at an internal address —
    including after a DNS flip or an HTTP redirect — is blocked. Returns False (fail closed)
    on any resolution error.
    """
    if not host:
        return False
    if _is_literal_ip(host):
        return not ip_is_blocked(host)
    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, port or 80, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, OSError):
        return False
    return all(not ip_is_blocked(str(info[4][0])) for info in infos)


async def resolve_safe_ip(host: str | None, port: int | None) -> str | None:
    """Resolve+vet once and return a safe IP to PIN the connection to (defeats DNS rebinding:
    the renderer connects to this exact vetted IP rather than re-resolving). Returns the literal
    host if it is already a safe literal IP, or None if anything is internal/unresolvable."""
    if not host:
        return None
    if _is_literal_ip(host):
        return None if ip_is_blocked(host) else host
    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, port or 80, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, OSError):
        return None
    ips = [str(info[4][0]) for info in infos]
    if not ips or any(ip_is_blocked(ip) for ip in ips):
        return None
    return ips[0]
