"""Secret-handling regression tests (security batch 5).

Pins: resolved secret values are scrubbed from logs by value (not just by shape), common
token shapes are scrubbed, and there is no default auth/signing secret.
"""

import logging as pylog

from agentvision import load_settings
from agentvision.logging import _SecretScrubber, register_secret


def _scrub(msg: str) -> str:
    rec = pylog.LogRecord("t", pylog.INFO, "f", 1, msg, (), None)
    _SecretScrubber().filter(rec)
    return rec.getMessage()


def test_value_based_scrub():
    register_secret("totally-opaque-token-NOSHAPE-9931")
    out = _scrub("calling with totally-opaque-token-NOSHAPE-9931 now")
    assert "NOSHAPE" not in out and "[REDACTED]" in out


def test_bearer_token_scrubbed():
    assert "abcd1234tokenvalue" not in _scrub("Authorization: Bearer abcd1234tokenvalue")


def test_keyword_value_scrubbed():
    assert "sk-ant-aaaaaaaa" not in _scrub("ANTHROPIC_API_KEY=sk-ant-aaaaaaaa")
    assert "supersecretpw" not in _scrub("password: supersecretpw")


def test_no_default_api_token():
    assert load_settings().api_token is None  # never a baked-in default secret


def test_key_for_registers_value_for_scrub(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-REGISTERME-77778888")
    s = load_settings()
    assert s.key_for("openai") == "sk-REGISTERME-77778888"
    assert "REGISTERME" not in _scrub("accidentally logged sk-REGISTERME-77778888")


def test_short_values_not_registered():
    # don't redact innocuous short strings
    register_secret("ab")
    assert _scrub("the value ab appears") == "the value ab appears"
