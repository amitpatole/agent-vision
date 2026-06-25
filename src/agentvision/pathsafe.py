"""Path-traversal confinement helpers (shared by every filesystem sink).

Untrusted data (HTTP path params, agent-supplied source specs) must never widen a path
expression beyond an allowed directory. These helpers confine a candidate path under a base
directory and reject anything that escapes it.

Confinement is **lexical**: the trusted base is realpath'd, the untrusted part is joined and
normalized with ``os.path`` (no filesystem access on tainted input — so resolving an
attacker symlink is never even attempted), then ``os.path.commonpath`` is the barrier. This
both blocks real traversal and is the sanitizer CodeQL `py/path-injection` recognizes.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .errors import UnsafeSourceError

# A single path component: letters, digits, dot, underscore, hyphen — no separators.
_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")


def safe_segment(name: str) -> str:
    """Validate a single path component (a name / id). Reject separators and traversal.

    Raises :class:`UnsafeSourceError` on anything that is not a plain component.
    """
    candidate = (name or "").strip()
    if candidate in (".", "..") or _SEGMENT.fullmatch(candidate) is None:
        raise UnsafeSourceError(f"invalid name (path traversal blocked): {name!r}")
    return candidate


def _confine_lexical(base: str | Path, untrusted: str) -> str:
    """Join ``untrusted`` under the trusted ``base`` and confirm it can't escape — purely
    lexically. Returns the confined absolute path string, or raises."""
    base_r = os.path.realpath(base)  # base is trusted (not user data) — safe to realpath
    # Lexical join + normalize; if `untrusted` is absolute, join intentionally discards base so
    # the commonpath check below catches the escape. No filesystem access on tainted input.
    candidate = os.path.normpath(os.path.join(base_r, os.path.expanduser(untrusted)))
    try:
        if os.path.commonpath([base_r, candidate]) != base_r:
            raise ValueError
    except ValueError:
        raise UnsafeSourceError("path escapes the allowed directory (traversal blocked)") from None
    return candidate


def confine(base: str | Path, target: str | Path) -> Path:
    """Return ``target`` confined under ``base`` (raises if it escapes). ``target`` may be a
    child path or an absolute path; either way it must resolve within ``base``."""
    return Path(_confine_lexical(base, str(target)))


def under(base: str | Path, segment: str, *, suffix: str = "") -> Path:
    """Confine ``<base>/<validated-segment><suffix>`` — for name/id-derived files."""
    return Path(_confine_lexical(base, f"{safe_segment(segment)}{suffix}"))


def resolve_local(raw: str, settings) -> Path:
    """Resolve a local file path, confined to ``settings.file_root`` when set.

    Default (``file_root is None``) is trusted CLI/library use: any absolute path or a
    cwd-relative path is allowed (confined only to the filesystem root, a no-op) — while still
    routed through the lexical ``commonpath`` barrier. A service sets ``file_root`` (or refuses
    local files via ``allow_local_files``) to truly restrict reads.
    """
    root = getattr(settings, "file_root", None)
    expanded = os.path.expanduser(str(raw))
    if root is None:
        # Trusted: resolve relatives against cwd, allow anywhere; barrier base is the FS root.
        candidate = os.path.normpath(os.path.abspath(expanded))
        base_r = os.path.realpath(os.sep)
        try:
            if os.path.commonpath([base_r, candidate]) != base_r:
                raise ValueError
        except ValueError:
            raise UnsafeSourceError("invalid local path") from None
        return Path(candidate)
    return Path(_confine_lexical(root, expanded))
