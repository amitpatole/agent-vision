"""Live desktop capture -> normalized PNG, via the freedesktop screenshot portal.

The agent's *shell* screenshot API (e.g. ``org.gnome.Shell.Screenshot``) refuses outside
callers, and giving a compositor extension a new method needs a restart. The desktop
**portal** (``org.freedesktop.portal.Screenshot``) needs neither: it routes the request to
the session's portal backend, which shows a permission prompt on the real screen. The user
approves interactively — that consent, plus ``Settings.allow_screen_capture`` (which the
REST service forces off), is the security boundary. No pixels are captured without it.

The capture itself is a blocking D-Bus dance (call → wait for the ``Response`` signal), so
it runs in a worker thread. ``jeepney`` (pure-Python D-Bus, the ``[desktop]`` extra) is
imported lazily; its absence is a clear :class:`MissingDependencyError`, never a crash.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..config import Settings
from ..errors import MissingDependencyError, RenderError
from ..logging import get_logger
from ..models.geometry import Viewport
from ..sources import ResolvedSource
from .base import RenderedImage, RenderResult, RenderSpec

log = get_logger("renderer.desktop")

_PORTAL_BUS = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_SCREENSHOT_IFACE = "org.freedesktop.portal.Screenshot"
_REQUEST_IFACE = "org.freedesktop.portal.Request"


def _capture_via_portal(*, interactive: bool, timeout_s: float) -> str:
    """Drive the screenshot portal synchronously; return a local ``file://`` PNG path.

    Predicts the ``Request`` object path from our bus name + a per-call token and subscribes
    to its ``Response`` signal *before* calling, so the reply can never race ahead of us.
    """
    try:
        from jeepney import DBusAddress, MatchRule, message_bus, new_method_call
        from jeepney.io.blocking import open_dbus_connection
    except ModuleNotFoundError as e:  # pragma: no cover - exercised via extras
        raise MissingDependencyError("desktop screen capture", pip_extra="desktop") from e

    screenshot = DBusAddress(_PORTAL_PATH, bus_name=_PORTAL_BUS, interface=_SCREENSHOT_IFACE)

    try:
        conn = open_dbus_connection(bus="SESSION")
    except Exception as e:  # noqa: BLE001 - no session bus / no portal available
        raise RenderError(
            "Cannot reach the desktop session bus for screen capture. A screenshot portal "
            "(xdg-desktop-portal) must be running in a logged-in graphical session."
        ) from e

    try:
        # Bound EVERY blocking op: a wedged portal or D-Bus daemon must never hang the worker
        # thread forever (which would leak threadpool workers on repeated calls). We pass an
        # explicit timeout to each request/receive AND set a socket-level deadline as a backstop
        # that also covers conn.close(). All of these surface as a clean RenderError.
        try:
            conn.sock.settimeout(max(1.0, timeout_s))
        except (AttributeError, OSError):  # pragma: no cover - best-effort backstop
            pass
        # handle_token must be a valid D-Bus path element ([A-Za-z0-9_]); uuid hex is safe.
        token = f"av_{uuid.uuid4().hex}"
        sender = conn.unique_name[1:].replace(".", "_")  # ':1.13' -> '1_13'
        request_path = f"{_PORTAL_PATH}/request/{sender}/{token}"

        rule = MatchRule(
            type="signal", interface=_REQUEST_IFACE, member="Response", path=request_path
        )
        # Route matching signals to us (AddMatch) AND queue them locally (filter), both set up
        # before the method call so the Response signal cannot arrive before we are listening.
        try:
            conn.send_and_get_reply(message_bus.AddMatch(rule), timeout=timeout_s)
        except (TimeoutError, OSError) as e:
            raise RenderError(
                "Screenshot portal / D-Bus is unresponsive (AddMatch did not ack "
                f"within {timeout_s:g}s)."
            ) from e
        with conn.filter(rule) as queue:
            call = new_method_call(
                screenshot,
                "Screenshot",
                "sa{sv}",
                ("", {"handle_token": ("s", token), "interactive": ("b", bool(interactive))}),
            )
            try:
                conn.send_and_get_reply(call, timeout=timeout_s)  # returns request handle; ack
            except (TimeoutError, OSError) as e:
                raise RenderError(
                    "Screenshot portal is unresponsive (Screenshot call did not ack "
                    f"within {timeout_s:g}s)."
                ) from e
            try:
                signal = conn.recv_until_filtered(queue, timeout=timeout_s)
            except TimeoutError as e:
                raise RenderError(
                    f"Screen capture timed out after {timeout_s:g}s waiting for the desktop "
                    "portal (no response to the permission prompt)."
                ) from e

        try:
            response_code, results = signal.body
        except (ValueError, TypeError) as e:
            raise RenderError("Malformed portal Response signal (unexpected body shape).") from e
        return _uri_from_response(response_code, results)
    finally:
        # Never let a close() failure mask the real RenderError from the try body (which the CLI
        # maps to a clean exit code); a socket already torn down is nothing to report.
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - best-effort teardown
            pass


def _uri_from_response(response_code: int, results) -> str:
    """Extract the image URI from a portal ``Response``, failing closed on denial/empties.

    ``response_code``: 0=success, 1=cancelled/denied by the user, 2=other error.
    """
    if response_code != 0:
        raise RenderError(
            "Screen capture was denied or cancelled at the desktop portal prompt "
            f"(portal response code {response_code})."
        )
    uri = _unwrap(results.get("uri")) if hasattr(results, "get") else None
    if not isinstance(uri, str) or not uri:
        raise RenderError("Screen capture portal returned no image URI.")
    return uri


def _unwrap(value):
    """jeepney may return a D-Bus variant as ``(signature, value)`` or as the bare value."""
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
        return value[1]
    return value


def _ephemeral_roots() -> list[Path]:
    """Resolved directories under which the portal's own screenshot file is safe to delete.

    Rejects over-broad roots — the filesystem root, the home dir, or any ancestor of home — so
    a hostile/misconfigured ``XDG_RUNTIME_DIR=/`` or ``TMPDIR=$HOME`` can't widen the deletion
    blast radius to arbitrary user files.
    """
    candidates = [Path(tempfile.gettempdir())]
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        candidates.append(Path(runtime))
    cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    candidates.append(Path(cache))
    try:
        home = Path.home().resolve()
    except OSError:  # pragma: no cover
        home = None
    out = []
    for r in candidates:
        try:
            rp = r.resolve()
        except OSError:  # pragma: no cover
            continue
        if rp == rp.anchor:  # filesystem root '/'
            continue
        if home is not None and (rp == home or rp in home.parents):  # $HOME, /home, /
            continue
        out.append(rp)
    return out


def _cleanup_portal_file(resolved: Path) -> None:
    """Best-effort delete of the portal's own output file, ONLY if under a temp/cache/runtime
    root — never a user's real file (e.g. ~/Pictures), which we leave in place and log.

    ``resolved`` MUST already be a resolved path (the caller resolves once and reuses it for
    is_file / open / unlink, so a symlink swap can't point the delete at a different inode).
    """
    if any(resolved == root or root in resolved.parents for root in _ephemeral_roots()):
        try:
            resolved.unlink(missing_ok=True)
        except OSError as e:  # pragma: no cover - best-effort
            log.debug("could not delete portal screenshot file %s: %s", resolved, e)
    else:
        log.debug("portal screenshot file left in place (outside temp/cache): %s", resolved)


def _uri_to_path(uri: str) -> Path:
    """Convert a portal ``file://`` URI to a local path, refusing any non-file scheme."""
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise RenderError(f"Screen capture portal returned a non-file URI scheme: {parsed.scheme!r}")
    if parsed.netloc not in ("", "localhost"):
        raise RenderError(f"Screen capture portal returned a remote file URI host: {parsed.netloc!r}")
    path = unquote(parsed.path)
    if "\x00" in path:  # a decoded %00 would make Path.stat raise ValueError, not RenderError
        raise RenderError("Screen capture portal returned a URI path containing a NUL byte.")
    return Path(path)


class DesktopRenderer:
    """Capture the live desktop via the freedesktop screenshot portal."""

    SUPPORTED = {"desktop"}

    def __init__(self, settings: Settings):
        self.settings = settings

    def supports(self, kind: str) -> bool:
        return kind in self.SUPPORTED

    async def render(self, spec: RenderSpec, resolved: ResolvedSource, out_dir: Path) -> RenderResult:
        import asyncio

        from ..imageguard import open_image_safely

        interactive = self.settings.screen_capture_interactive
        timeout_s = self.settings.screen_capture_timeout_s
        # Outer wall-clock bound: even with the inner per-call timeouts, cap the whole offloaded
        # capture so the coroutine can never wait unbounded on a wedged portal (the thread itself
        # unwinds via the inner socket/request timeouts). Small slack over the inner ceiling.
        try:
            uri = await asyncio.wait_for(
                asyncio.to_thread(
                    _capture_via_portal, interactive=interactive, timeout_s=timeout_s
                ),
                timeout=timeout_s + 5.0,
            )
        except TimeoutError as e:
            raise RenderError(
                f"Screen capture exceeded its {timeout_s:g}s wall-clock bound (portal wedged)."
            ) from e
        # Resolve the portal path ONCE and reuse that single resolved path for is_file / open /
        # unlink — so a symlink swapped in between checks can't point the delete (or read) at a
        # different inode than the one we validated (TOCTOU hardening).
        try:
            src_path = _uri_to_path(uri).resolve()
        except OSError as e:
            raise RenderError("Screen capture portal returned an unresolvable path.") from e
        # Defense-in-depth: only ever read a real regular file. A FIFO/device/socket at the
        # returned path (e.g. a local process racing the portal's output) would otherwise hang
        # the open or read an endless stream; is_file() refuses all of those. The byte/pixel caps
        # in open_image_safely bound the rest.
        if not src_path.is_file():
            raise RenderError(
                f"Screen capture portal returned a path that is not a regular file: {src_path}"
            )

        out_dir.mkdir(parents=True, exist_ok=True)
        img_path = out_dir / "screenshot.png"
        # byte + pixel caps enforced before decode (decompression-bomb guard) — the portal file
        # is trusted, but we treat it like any other input and normalize to a bounded PNG.
        try:
            with open_image_safely(src_path) as im:
                im = im.convert("RGB")
                im.save(img_path, "PNG")
                w, h = im.size
        finally:
            # The portal writes its OWN full-desktop PNG (the source we just read). If it landed
            # in a temp/cache/runtime dir, delete it — otherwise the portal's original persists
            # on disk and defeats the ephemeral guarantee even though our copy is wiped. We never
            # touch a file outside those roots (e.g. a user's ~/Pictures) — only log it.
            _cleanup_portal_file(src_path)
        log.debug("captured desktop screenshot %dx%d", w, h)
        return RenderResult(
            images=[RenderedImage(
                path=str(img_path), viewport=Viewport(width=w, height=h), width=w, height=h,
            )],
            source_type="desktop",
        )
