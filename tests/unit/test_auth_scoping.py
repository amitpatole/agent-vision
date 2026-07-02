"""Unit tests for origin-scoped auth resolution (Phase 3b).

Pins: env-var-only secrets (never inline), secret registration/scrubbing, origin
normalisation, fail-loud on missing/malformed env, and that auth is ignored for non-URL
sources (no origin to scope to).
"""

import logging

import pytest

from agentvision import load_settings
from agentvision.errors import RenderError
from agentvision.renderers.base import RenderSpec
from agentvision.renderers.playwright_renderer import PlaywrightRenderer, _origin_of
from agentvision.sources import ResolvedSource


def _r():
    return PlaywrightRenderer(load_settings())


def _url_src(url="https://app.example.com/dashboard"):
    return ResolvedSource(kind="url", url=url)


def test_origin_normalisation():
    assert _origin_of("https://app.com/a") == "https://app.com:443"
    assert _origin_of("http://app.com/a") == "http://app.com:80"
    assert _origin_of("https://app.com:8443/x") == "https://app.com:8443"
    assert _origin_of("https://App.COM/a") == _origin_of("https://app.com/b")  # case-insensitive
    assert _origin_of("not a url") is None


def test_auth_ignored_for_non_url_source(caplog):
    spec = RenderSpec(source="<html></html>", auth_header_env="TOK")
    with caplog.at_level(logging.WARNING, logger="agentvision"):
        creds, header, origin = _r()._resolve_auth(spec, ResolvedSource(kind="html", content="x"))
    assert (creds, header, origin) == (None, None, None)
    assert any("apply only to URL" in r.getMessage() for r in caplog.records)


def test_bearer_header_resolved_and_scoped(monkeypatch):
    monkeypatch.setenv("AV_TOKEN", "Bearer super-secret-jwt-0001")
    spec = RenderSpec(source="u", auth_header_env="AV_TOKEN")
    creds, header, origin = _r()._resolve_auth(spec, _url_src())
    assert creds is None
    assert header == "Bearer super-secret-jwt-0001"
    assert origin == "https://app.example.com:443"
    from agentvision.logging import _KNOWN_SECRETS
    assert "Bearer super-secret-jwt-0001" in _KNOWN_SECRETS  # registered for scrubbing


def test_missing_header_env_raises():
    spec = RenderSpec(source="u", auth_header_env="DEFINITELY_UNSET_ENV_XYZ")
    with pytest.raises(RenderError):
        _r()._resolve_auth(spec, _url_src())


def test_basic_credentials_scoped(monkeypatch):
    monkeypatch.setenv("AV_BASIC", "alice:hunter2secret")
    spec = RenderSpec(source="u", http_credentials_env="AV_BASIC")
    creds, header, origin = _r()._resolve_auth(spec, _url_src())
    # Playwright-style origin: default port omitted (so Basic auth actually matches).
    assert creds == {"username": "alice", "password": "hunter2secret",
                     "origin": "https://app.example.com"}
    assert header is None
    from agentvision.logging import _KNOWN_SECRETS
    assert "hunter2secret" in _KNOWN_SECRETS


def test_basic_credentials_require_colon(monkeypatch):
    monkeypatch.setenv("AV_BASIC_BAD", "no-colon-here")
    spec = RenderSpec(source="u", http_credentials_env="AV_BASIC_BAD")
    with pytest.raises(RenderError):
        _r()._resolve_auth(spec, _url_src())


def test_auth_forces_ephemeral_via_cli_settings(monkeypatch):
    # The CLI helper must force ephemeral whenever any auth is supplied (no cache leak).
    from agentvision.adapters.cli import _settings
    s = _settings(auth_header_env="AV_TOKEN")
    assert s.ephemeral is True
    s2 = _settings(http_credentials_env="AV_BASIC")
    assert s2.ephemeral is True
