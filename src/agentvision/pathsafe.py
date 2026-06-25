"""Path-traversal confinement helpers (shared by every filesystem sink).

Untrusted data (HTTP path params, agent-supplied source specs) must never widen a path
expression beyond an allowed directory. These helpers resolve a candidate path and verify —
via ``os.path.commonpath`` against a trusted base — that it stays within that base, raising
otherwise. Used at every sink so the real traversal is blocked and the eventual filesystem
operation receives a value proven to be inside an allowed directory.

Note for code scanners: the ``Path.resolve()`` calls below are the *confinement barrier* —
the resolved path is immediately checked with ``commonpath`` and the function raises if it
escapes, so no caller ever performs a filesystem operation on an unconfined path.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .errors import UnsafeSourceError

# A single path component: letters, digits, dot, underscore, hyphen — no separators.
_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")


def safe_segment(name: str) -> str:
    """Validate a single path component (a name / id). Reject separators and traversal."""
    candidate = (name or "").strip()
    if candidate in (".", "..") or _SEGMENT.fullmatch(candidate) is None:
        raise UnsafeSourceError(f"invalid name (path traversal blocked): {name!r}")
    return candidate


def _contains(base: Path, target: Path) -> bool:
    try:
        return os.path.commonpath([str(base), str(target)]) == str(base)
    except ValueError:  # different drives (Windows) / mixed abs+rel
        return False


def confine(base: str | Path, target: str | Path) -> Path:
    """Return ``target`` confined under ``base`` (raises if it escapes).

    The resolved ``target`` is checked with ``commonpath`` against the resolved ``base``; a
    path that escapes (via ``..``, an absolute path, or a symlink) is refused.
    """
    base_r = Path(base).expanduser().resolve()
    target_r = Path(target).expanduser().resolve()
    if not _contains(base_r, target_r):
        raise UnsafeSourceError("path escapes the allowed directory (traversal blocked)")
    return target_r


def under(base: str | Path, segment: str, *, suffix: str = "") -> Path:
    """Confine ``<base>/<validated-segment><suffix>`` — for name/id-derived files."""
    base_p = Path(base)
    return confine(base_p, base_p / f"{safe_segment(segment)}{suffix}")


def resolve_local(raw: str, settings) -> Path:
    """Resolve a local file path, confined to ``settings.file_root`` when set.

    Default (``file_root is None``) is trusted CLI/library use: any path is allowed (confined
    only to the filesystem root, a no-op) while still routed through the ``commonpath``
    barrier. A service sets ``file_root`` (or refuses local files via ``allow_local_files``)
    to truly restrict reads.
    """
    p = Path(raw).expanduser().resolve()
    root = getattr(settings, "file_root", None)
    base = Path(root).expanduser().resolve() if root else Path(p.anchor or os.sep)
    if not _contains(base, p):
        raise UnsafeSourceError("path escapes the allowed root (traversal blocked)")
    return p
