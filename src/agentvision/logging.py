"""Lightweight logging setup.

Crucially: AgentVision NEVER logs resolved credentials. We scrub anything that looks
like an API key from log records as a defense-in-depth measure.
"""

from __future__ import annotations

import logging
import os
import re

_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|AIza[A-Za-z0-9_\-]{8,}"
    r"|[Bb]earer\s+[A-Za-z0-9._\-]{8,}"
    r"|(?:api[_-]?key|token|secret|password)[\"'`:=\s]+[A-Za-z0-9._\-]{6,})",
    re.IGNORECASE,
)

_LOGGER_NAME = "agentvision"

# Exact secret VALUES that have been resolved at runtime (API keys, the API token). Scrubbing
# by value is sound where the shape-based regex above is only a heuristic backstop; config
# registers every key it resolves so it is redacted even if some code path ever logs it.
_KNOWN_SECRETS: set[str] = set()


def register_secret(value: str | None) -> None:
    """Register a resolved secret value so it is redacted from any log line. No-op for short
    or empty values (avoids redacting innocuous substrings)."""
    if value and len(value) >= 6:
        _KNOWN_SECRETS.add(value)


class _SecretScrubber(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            msg = record.getMessage()
        except Exception:
            return True
        original = msg
        for secret in _KNOWN_SECRETS:
            if secret in msg:
                msg = msg.replace(secret, "[REDACTED]")
        if _SECRET_RE.search(msg):
            msg = _SECRET_RE.sub("[REDACTED]", msg)
        if msg != original:
            record.msg = msg
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
