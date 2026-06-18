"""Lightweight logging setup.

Crucially: AgentVision NEVER logs resolved credentials. We scrub anything that looks
like an API key from log records as a defense-in-depth measure.
"""

from __future__ import annotations

import logging
import os
import re

_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|AIza[A-Za-z0-9_\-]{8,}|[A-Za-z0-9_\-]{0,4}(?:api[_-]?key|token|secret)"
    r"[\"'`:=\s]+[A-Za-z0-9_\-]{8,})",
    re.IGNORECASE,
)

_LOGGER_NAME = "agentvision"


class _SecretScrubber(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            msg = record.getMessage()
        except Exception:
            return True
        if _SECRET_RE.search(msg):
            record.msg = _SECRET_RE.sub("[REDACTED]", msg)
            record.args = ()
        return True


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a namespaced logger under ``agentvision``."""
    base = logging.getLogger(_LOGGER_NAME)
    if not base.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s agentvision: %(message)s"))
        handler.addFilter(_SecretScrubber())
        base.addHandler(handler)
        level = os.environ.get("AGENTVISION_LOG_LEVEL", "WARNING").upper()
        base.setLevel(getattr(logging, level, logging.WARNING))
        base.propagate = False
    if name:
        return base.getChild(name)
    return base
