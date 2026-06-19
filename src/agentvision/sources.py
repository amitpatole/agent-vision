"""Source resolution + safety policy.

A "source" is whatever an agent hands us: an inline HTML/SVG string, a file path, or a
URL. ``resolve_source`` normalizes it into a :class:`ResolvedSource` and enforces the
safety policy (SSRF + ``file://`` denial) because we render untrusted, agent-produced
content in a real browser.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .config import Settings
from .errors import UnsafeSourceError

# Logical source kinds. ``html``/``svg`` may be inline (content) or from a file.
KINDS = ("html", "svg", "url", "pdf", "image", "file")
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


@dataclass
class ResolvedSource:
    kind: str  # one of: html, svg, url, pdf, image
    content: str | None = None  # inline HTML/SVG text
    path: Path | None = None  # local file
    url: str | None = None  # remote URL

    def cache_bytes(self) -> bytes:
        if self.content is not None:
            return self.content.encode("utf-8", "replace")
        if self.path is not None:
            try:
                return self.path.read_bytes()
            except OSError:
                return str(self.path).encode()
        return (self.url or "").encode()


def _looks_like_markup(s: str) -> bool:
    head = s.lstrip()[:512].lower()
    return head.startswith("<") and ("<" in head and ">" in s)


def _detect_type(source: str) -> str:
    s = source.strip()
    low = s.lower()
    if low.startswith(("http://", "https://")):
        return "url"
    if low.startswith("file://"):
        return "file"
    if _looks_like_markup(s):
        return "svg" if "<svg" in low[:512] and "<html" not in low[:512] else "html"
    # Treat as a path; classify by extension.
    p = Path(s)
    ext = p.suffix.lower()
    if ext in {".html", ".htm"}:
        return "html"
    if ext == ".svg":
        return "svg"
    if ext == ".pdf":
        return "pdf"
    if ext in _IMAGE_EXT:
        return "image"
    return "html" if ext in {"", ".txt"} and not p.exists() else "file"


def _check_url_safety(url: str, settings: Settings) -> None:
    if not settings.allow_url_rendering:
        raise UnsafeSourceError("URL rendering is disabled (allow_url_rendering=False).")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeSourceError(f"Disallowed URL scheme: {parsed.scheme!r}")
    if not settings.block_private_networks:
        return
    host = parsed.hostname
    if not host:
        raise UnsafeSourceError("URL has no host.")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as e:
        raise UnsafeSourceError(f"Could not resolve host {host!r}: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise UnsafeSourceError(
                f"Refusing to render {host!r}: resolves to non-public address {ip} "
                "(SSRF protection). To allow a localhost / LAN dev server, pass --allow-local "
                "(CLI) or set AGENTVISION_BLOCK_PRIVATE_NETWORKS=false."
            )


def resolve_source(source: str, source_type: str = "auto", *, settings: Settings) -> ResolvedSource:
    """Normalize ``source`` into a :class:`ResolvedSource`, enforcing the safety policy."""
    stype = source_type if source_type != "auto" else _detect_type(source)

    if stype == "url":
        url = source.strip()
        _check_url_safety(url, settings)
        return ResolvedSource(kind="url", url=url)

    if stype in {"html", "svg"} and _looks_like_markup(source):
        return ResolvedSource(kind=stype, content=source)

    # Everything else is a file path (including file:// URLs, which we then gate).
    raw = source.strip()
    if raw.lower().startswith("file://"):
        if not settings.allow_file_scheme:
            raise UnsafeSourceError(
                "Refusing file:// source (local-file exfiltration protection). "
                "Set allow_file_scheme=True to override."
            )
        raw = urlparse(raw).path

    path = Path(raw).expanduser()
    if not path.exists():
        # A bare HTML/SVG string with no recognizable markup that isn't a real file.
        if stype in {"html", "svg"}:
            return ResolvedSource(kind=stype, content=source)
        raise UnsafeSourceError(f"Source path does not exist: {path}")

    ext = path.suffix.lower()
    if stype == "file" or source_type == "auto":
        if ext == ".pdf":
            kind = "pdf"
        elif ext == ".svg":
            kind = "svg"
        elif ext in _IMAGE_EXT:
            kind = "image"
        else:
            kind = "html"
    else:
        kind = stype if stype in {"pdf", "image", "svg", "html"} else "html"

    if kind in {"svg", "html"} and source_type in {"svg", "html", "auto", "file"}:
        # Inline file content so the renderer can wrap/serve it without file:// access.
        try:
            return ResolvedSource(kind=kind, content=path.read_text(encoding="utf-8"), path=path)
        except (OSError, UnicodeDecodeError):
            pass
    return ResolvedSource(kind=kind, path=path)
