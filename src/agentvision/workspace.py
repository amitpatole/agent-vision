"""Artifact store and session state.

Two distinct areas under the cache dir:

* ``renders/``  — content-addressed RENDER artifacts only. Key = hash of render inputs
  (source bytes + viewport + device_scale + wait_for + renderer version). We never cache
  ``Report``s (LLM output is non-deterministic) and never key on screenshot bytes
  (Chromium output is not bit-stable).
* ``sessions/<id>/iter_<n>/`` — per-loop-iteration state. Guarded by a short-held sync
  ``filelock`` (acquired only around filesystem mutation, never held across an ``await``).

A TTL garbage collector reaps sessions whose lock is unheld and whose mtime exceeds the
TTL, and sessions whose ``schema_version`` no longer matches the running code.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

from .config import Settings
from .logging import get_logger

log = get_logger("workspace")


@contextmanager
def ephemeral_cache(settings: Settings) -> Iterator[Settings]:
    """Yield a copy of ``settings`` whose cache lives in a throwaway temp dir, wiped on exit.

    Use for confidential inputs so renders/sessions are never written to the persistent
    on-disk cache. The temp dir is created with private (0700) permissions and removed in a
    ``finally`` so it's cleaned up even on error.

        with ephemeral_cache(load_settings()) as s:
            report = await analyze("/path/to/confidential.pptx", settings=s)
    """
    tmp = Path(tempfile.mkdtemp(prefix="agentvision-ephemeral-"))
    try:
        yield settings.model_copy(update={"cache_dir": tmp, "ephemeral": True})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

# Bump when the on-disk session layout / Report schema changes incompatibly.
SCHEMA_VERSION = "1.0"
RENDERER_VERSION = "1"  # part of the render cache key; bump on renderer behavior changes


class Workspace:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = Path(settings.cache_dir)
        self.renders = self.root / "renders"
        self.sessions = self.root / "sessions"
        self.tmp = self.root / "tmp"
        for d in (self.renders, self.sessions, self.tmp):
            d.mkdir(parents=True, exist_ok=True)

    # ---- render cache (inputs-addressed) ---------------------------------------

    @staticmethod
    def render_key(*, source_bytes: bytes, viewport: tuple[int, int], device_scale: float,
                   wait_for: str | None, full_page: bool) -> str:
        h = hashlib.sha256()
        h.update(RENDERER_VERSION.encode())
        h.update(source_bytes)
        h.update(f"|{viewport[0]}x{viewport[1]}|{device_scale}|{wait_for}|{full_page}".encode())
        return h.hexdigest()[:32]

    def render_path(self, key: str, suffix: str = ".png") -> Path:
        return self.renders / f"{key}{suffix}"

    # ---- sessions --------------------------------------------------------------

    def new_session_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def session_dir(self, session_id: str) -> Path:
        d = self.sessions / session_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def iter_dir(self, session_id: str, index: int) -> Path:
        d = self.session_dir(session_id) / f"iter_{index}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _lock(self, session_id: str) -> FileLock:
        return FileLock(str(self.sessions / f"{session_id}.lock"))

    def write_session_meta(self, session_id: str, meta: dict) -> None:
        """Write session metadata under a short-held sync lock."""
        meta = {**meta, "schema_version": SCHEMA_VERSION}
        lock = self._lock(session_id)
        with lock:  # acquire -> write -> release; never held across an await
            (self.session_dir(session_id) / "session.json").write_text(json.dumps(meta, indent=2))

    def read_session_meta(self, session_id: str) -> dict | None:
        f = self.session_dir(session_id) / "session.json"
        if not f.exists():
            return None
        try:
            meta = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if meta.get("schema_version") != SCHEMA_VERSION:
            log.warning("session %s has stale schema_version; ignoring", session_id)
            return None
        return meta

    # ---- garbage collection ----------------------------------------------------

    def gc(self) -> int:
        """Reap stale sessions. Returns the count removed."""
        removed = 0
        now = time.time()
        if not self.sessions.exists():
            return 0
        for d in self.sessions.iterdir():
            if not d.is_dir():
                continue
            session_id = d.name
            # Skip sessions whose lock is currently held by a live process.
            lock = self._lock(session_id)
            try:
                lock.acquire(timeout=0)
            except Timeout:
                continue
            try:
                stale_ttl = (now - d.stat().st_mtime) > self.settings.session_ttl_s
                meta = self.read_session_meta(session_id)  # None if schema mismatch
                if stale_ttl or meta is None:
                    shutil.rmtree(d, ignore_errors=True)
                    removed += 1
            finally:
                lock.release()
                lockfile = self.sessions / f"{session_id}.lock"
                lockfile.unlink(missing_ok=True)
        return removed
