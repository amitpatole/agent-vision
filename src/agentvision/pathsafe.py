"""Path-traversal confinement helpers (shared by every filesystem sink).

Untrusted data (HTTP path params, agent-supplied source specs) must never widen a path
expression beyond an allowed directory. These helpers resolve a candidate path and verify —
via ``os.path.commonpath`` — that it stays within a base directory, raising otherwise. Used
at every sink so CodeQL `py/path-injection` flows are sanitized and, more importantly, real
traversal payloads are blocked.
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


def confine(base: str | Path, target: str | Path) -> Path:
    """Resolve ``target`` and return it only if it stays within ``base``; else raise.

    The ``commonpath`` check is the traversal barrier: a resolved ``target`` that escapes
    ``base`` (via ``..``, an absolute path, or a symlink) has a common path != ``base``.
    """
    base_r = Path(base).expanduser().resolve()
    target_r = Path(target).expanduser().resolve()
    try:
        if os.path.commonpath([str(base_r), str(target_r)]) != str(base_r):
            raise ValueError
    except ValueError:
        raise UnsafeSourceError("path escapes the allowed directory (traversal blocked)") from None
    return target_r


def under(base: str | Path, segment: str, *, suffix: str = "") -> Path:
    """Confine ``<base>/<validated-segment><suffix>`` — for name/id-derived files."""
    base_p = Path(base)
    return confine(base_p, base_p / f"{safe_segment(segment)}{suffix}")


def resolve_local(raw: str, settings) -> Path:
    """Resolve a local file path, confined to ``settings.file_root`` when set.

    Default (``file_root is None``) confines to the filesystem root — i.e. no restriction
    for trusted CLI/library use (an operator analyzing their own files), while still routing
    the value through the ``commonpath`` barrier. A service can set ``file_root`` (or, by
    default, refuses local files entirely via ``allow_local_files``) to truly restrict reads.
    """
    p = Path(raw).expanduser().resolve()
    root = getattr(settings, "file_root", None)
    base = Path(root) if root else Path(p.anchor or os.sep)
    return confine(base, p)
