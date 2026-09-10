"""Source resolution + safety policy.

A "source" is whatever an agent hands us: an inline HTML/SVG string, a file path, or a
URL. ``resolve_source`` normalizes it into a :class:`ResolvedSource` and enforces the
safety policy (SSRF + ``file://`` denial) because we render untrusted, agent-produced
content in a real browser.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .config import Settings
from .errors import UnsafeSourceError
from .netguard import assert_host_safe
from .office import OFFICE_EXT
from .pathsafe import resolve_local

# Logical source kinds. ``html``/``svg`` may be inline (content) or from a file.
# ``desktop`` is a live capture (no path/url/content) via the screenshot portal.
KINDS = ("html", "svg", "url", "pdf", "image", "office", "motion", "file", "desktop")
# URI schemes that request a live desktop screen capture (no file, no URL).
_SCREEN_SCHEMES = ("desktop:", "screen:")
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
# Local motion media (video files). Routed to the temporal grader, never the browser —
# handing an .mp4 to Chromium as a page renders blank and produces a misleading FAIL.
_VIDEO_EXT = {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"}


def _gif_is_animated(path: Path) -> bool:
    """True when a GIF has more than one frame (graded as motion, not a frame-0 still)."""
    try:
        from .imageguard import open_image_safely

        with open_image_safely(path) as im:
            return int(getattr(im, "n_frames", 1)) > 1
    except Exception:  # noqa: BLE001  # unreadable/oversized: let the image path report it
        return False


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


def _detect_type(source: str, settings: Settings) -> str:
    s = source.strip()
    low = s.lower()
    if low.startswith(_SCREEN_SCHEMES):
        return "desktop"
    if low.startswith(("http://", "https://")):
        return "url"
    if low.startswith("file://"):
        return "file"
    if _looks_like_markup(s):
        return "svg" if "<svg" in low[:512] and "<html" not in low[:512] else "html"
    # Treat as a path; classify by extension.
    ext = Path(s).suffix.lower()
    if ext in {".html", ".htm"}:
        return "html"
    if ext == ".svg":
        return "svg"
    if ext == ".pdf":
        return "pdf"
    if ext in OFFICE_EXT:
        return "office"
    if ext in _IMAGE_EXT:
        return "image"
    # Ambiguous (no/.txt extension): a bare string is inline HTML unless it names an existing
    # file. The existence probe is confined (commonpath barrier) so it can't be a traversal sink.
    if ext in {"", ".txt"}:
        try:
            exists = resolve_local(s, settings).exists()
        except (UnsafeSourceError, OSError):
            exists = False
        return "file" if exists else "html"
    return "file"


def _check_url_safety(url: str, settings: Settings) -> None:
    if not settings.allow_url_rendering:
        raise UnsafeSourceError("URL rendering is disabled (allow_url_rendering=False).")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeSourceError(f"Disallowed URL scheme: {parsed.scheme!r}")
    if not settings.block_private_networks:
        return
    # Resolve-time SSRF check (re-checked at fetch time in the renderer route guard).
    assert_host_safe(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))


def resolve_source(source: str, source_type: str = "auto", *, settings: Settings) -> ResolvedSource:
    """Normalize ``source`` into a :class:`ResolvedSource`, enforcing the safety policy."""
    stype = source_type if source_type != "auto" else _detect_type(source, settings)

    if stype == "desktop":
        # A live screen capture reads whatever is on the user's display, so it is refused on
        # the (untrusted) REST service, which sets allow_screen_capture=False — a remote caller
        # must never grab the host's screen. Local CLI/library use is trusted, and the portal
        # itself prompts for consent on every capture.
        # SECURITY INVARIANT: this gate is the ONLY barrier — an explicit source_type="desktop"
        # captures the screen regardless of the `source` string. Any adapter that forwards a
        # caller-supplied source_type to untrusted callers MUST keep allow_screen_capture=False.
        if not settings.allow_screen_capture:
            raise UnsafeSourceError(
                "Refusing a desktop screen-capture source (not permitted on this service). "
                "Set allow_screen_capture=True to override (local use only)."
            )
        return ResolvedSource(kind="desktop")

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

    # Resolve under the configured confinement root (commonpath barrier) — blocks traversal
    # via a bare path or a file:// URL escaping settings.file_root.
    path = resolve_local(raw, settings)
    if not path.exists():
        # A bare HTML/SVG string with no recognizable markup that isn't a real file.
        if stype in {"html", "svg"}:
            return ResolvedSource(kind=stype, content=source)
        raise UnsafeSourceError(f"Source path does not exist: {path}")
    # Reading a real local file: trusted for CLI/library; refused on the (untrusted) service so
    # a remote caller can't read host files via a bare path like "/etc/passwd".
    if not settings.allow_local_files:
        raise UnsafeSourceError(
            "Refusing to read a local file source (not permitted on this service)."
        )

    ext = path.suffix.lower()
    if stype == "file" or source_type == "auto":
        if ext == ".pdf":
            kind = "pdf"
        elif ext == ".svg":
            kind = "svg"
        elif ext in OFFICE_EXT:
            kind = "office"
        elif ext in _VIDEO_EXT:
            kind = "motion"
        elif ext == ".gif" and _gif_is_animated(path):
            kind = "motion"  # animated GIF: grade the animation, not frame 0
        elif ext in _IMAGE_EXT:
            kind = "image"
        else:
            kind = "html"
    else:
        kind = stype if stype in {"pdf", "image", "svg", "html", "office", "motion"} else "html"

    if kind in {"svg", "html"} and source_type in {"svg", "html", "auto", "file"}:
        # Inline file content so the renderer can wrap/serve it without file:// access.
        try:
            return ResolvedSource(kind=kind, content=path.read_text(encoding="utf-8"), path=path)
        except (OSError, UnicodeDecodeError):
            pass
    return ResolvedSource(kind=kind, path=path)
