"""Ollama backend: self-hosted (keyless) vs cloud credential scoping, and fail-closed parsing.

Pins two pilot fixes:
1. The Ollama Cloud key is sent ONLY to ollama.com. Pointing ``ollama_base_url`` at a LAN box
   (or a lookalike host) must never leak the key file's contents to it.
2. An unparseable model reply surfaces a WARNING issue, so it can never grade as PASS.
"""

from __future__ import annotations

import pytest
from PIL import Image

import agentvision.config as cfg
from agentvision.backends import ollama_backend as ob
from agentvision.backends.base import AnalysisRequest
from agentvision.config import load_settings
from agentvision.models.report import Verdict

CLOUD_KEY = "sk-cloud-secret-123"


@pytest.fixture
def cloud_key_file(monkeypatch, tmp_path):
    key = tmp_path / "key"
    key.write_text(CLOUD_KEY)
    monkeypatch.setattr(cfg, "KEY_FILES", {"ollama": key})
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    return key


@pytest.mark.parametrize("url,cloud", [
    ("https://ollama.com/v1", True),
    ("https://OLLAMA.COM./v1", True),
    ("https://api.ollama.com/v1", True),
    ("http://192.0.2.10:11434/v1", False),
    ("http://localhost:11434/v1", False),
    ("https://ollama.com.evil.net/v1", False),      # lookalike suffix
    ("https://evilollama.com/v1", False),           # lookalike prefix
    ("https://evil.net/v1?h=ollama.com", False),    # host in the query string
    ("https://ollama.com@evil.net/v1", False),      # userinfo trick
    ("https://ollama.com:443@evil.net/v1", False),  # userinfo with port
    ("http://ollama.com/v1", False),                # cleartext never gets the key
    ("not a url", False),
])
def test_is_cloud_url(url, cloud):
    assert ob.is_cloud_url(url) is cloud


def test_self_hosted_never_receives_cloud_key_file(cloud_key_file):
    s = load_settings(ollama_base_url="http://192.0.2.10:11434/v1")
    cred = ob.resolve_credential(s)
    assert cred != CLOUD_KEY
    assert cred == ob._SELF_HOSTED_PLACEHOLDER_KEY
    assert ob.OllamaBackend(s).available()


def test_lookalike_host_never_receives_cloud_key_file(cloud_key_file):
    s = load_settings(ollama_base_url="https://ollama.com.evil.net/v1")
    assert ob.resolve_credential(s) != CLOUD_KEY


def test_cloud_uses_key_file(cloud_key_file):
    s = load_settings(ollama_base_url="https://ollama.com/v1")
    assert ob.resolve_credential(s) == CLOUD_KEY


def test_cloud_without_key_is_unavailable(monkeypatch):
    monkeypatch.setattr(cfg, "KEY_FILES", {})
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    s = load_settings(ollama_base_url="https://ollama.com/v1")
    assert ob.resolve_credential(s) is None
    assert not ob.OllamaBackend(s).available()


def test_self_hosted_never_receives_cloud_env_key(cloud_key_file, monkeypatch):
    # Red-team R1: OLLAMA_API_KEY (the documented cloud key) must not follow a redirected URL.
    monkeypatch.setenv("OLLAMA_API_KEY", "sk-env-cloud-key")
    s = load_settings(ollama_base_url="http://127.0.0.1:18765/v1")
    assert ob.resolve_credential(s) == ob._SELF_HOSTED_PLACEHOLDER_KEY


def test_self_hosted_proxy_key_is_separate(cloud_key_file, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "sk-env-cloud-key")
    monkeypatch.setenv("AGENTVISION_OLLAMA_SELF_HOSTED_KEY", "proxy-tok")
    s = load_settings(ollama_base_url="http://proxy.internal/v1")
    assert ob.resolve_credential(s) == "proxy-tok"
    # ...and the proxy key is never sent to the cloud
    s2 = load_settings(ollama_base_url="https://ollama.com/v1")
    assert ob.resolve_credential(s2) == "sk-env-cloud-key"


@pytest.mark.parametrize("url", ["http://ollama.com/v1", "//ollama.com/v1",
                                 "file://ollama.com/v1"])
def test_cloud_key_requires_https(url, cloud_key_file):
    assert not ob.is_cloud_url(url)
    assert ob.resolve_credential(load_settings(ollama_base_url=url)) != CLOUD_KEY


def test_planted_dotenv_ignored_when_disabled(tmp_path, monkeypatch, cloud_key_file):
    # Red-team R1 exploit shape: a PR checkout plants .env redirecting the base URL.
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("AGENTVISION_OLLAMA_BASE_URL=http://127.0.0.1:18765/v1\n")
    monkeypatch.delenv("AGENTVISION_OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("AGENTVISION_DOTENV", "0")
    assert load_settings().ollama_base_url == "https://ollama.com/v1"
    monkeypatch.setenv("AGENTVISION_DOTENV", "1")
    s = load_settings()
    assert s.ollama_base_url == "http://127.0.0.1:18765/v1"
    assert ob.resolve_credential(s) != CLOUD_KEY  # even when read, the key stays home


def test_parse_findings_flags_garbage():
    _, ok = ob._parse_findings("I think the page looks fine!")
    assert not ok
    f, ok = ob._parse_findings('```json\n{"verdict":"pass","summary":"ok","issues":[]}\n```')
    assert ok and f.verdict == Verdict.PASS


class _FakeResp:
    def __init__(self, content, finish_reason=None):
        msg = type("M", (), {"content": content})()
        self.choices = [type("C", (), {"message": msg, "finish_reason": finish_reason})()]


def _fake_client(content, seen, finish_reason=None):
    class _Completions:
        async def create(self, **kw):
            seen.update(max_tokens=kw.get("max_tokens"))
            return _FakeResp(content, finish_reason)

    class _Client:
        def __init__(self, base_url, api_key):
            seen.update(base_url=base_url, api_key=api_key)
            self.chat = type("Chat", (), {"completions": _Completions()})()

        async def close(self):
            pass

    return _Client


async def _run(monkeypatch, tmp_path, content, base_url="http://192.0.2.10:11434/v1",
               finish_reason=None, **overrides):
    pytest.importorskip("openai")
    import openai

    seen: dict = {}
    monkeypatch.setattr(openai, "AsyncOpenAI", _fake_client(content, seen, finish_reason))
    img = tmp_path / "a.png"
    Image.new("RGB", (64, 64), "white").save(img)
    s = load_settings(ollama_base_url=base_url, **overrides)
    report = await ob.OllamaBackend(s).analyze(AnalysisRequest(image_path=str(img)))
    return report, seen


async def test_unparseable_reply_is_never_pass(monkeypatch, tmp_path, cloud_key_file):
    report, seen = await _run(monkeypatch, tmp_path, "Looks great to me.")
    assert report.verdict != Verdict.PASS
    assert any("unparseable" in i.message for i in report.issues)
    # and the self-hosted host got the placeholder, not the cloud key
    assert seen["api_key"] != CLOUD_KEY


async def test_parseable_clean_reply_passes(monkeypatch, tmp_path, cloud_key_file):
    report, _ = await _run(monkeypatch, tmp_path,
                           '{"verdict":"pass","summary":"clean","issues":[]}')
    assert report.verdict == Verdict.PASS


async def test_truncated_reply_says_so_and_is_never_pass(monkeypatch, tmp_path, cloud_key_file):
    # kimi-k2.7-code on Ollama Cloud: reasoning ate the budget and the JSON was cut off.
    report, _ = await _run(monkeypatch, tmp_path, '{"verdict":"fail","summary":"The bad',
                           finish_reason="length")
    assert report.verdict != Verdict.PASS
    assert any("cut off at the token limit" in i.message for i in report.issues)


async def test_max_tokens_is_configurable(monkeypatch, tmp_path, cloud_key_file):
    _, seen = await _run(monkeypatch, tmp_path, '{"verdict":"pass","summary":"ok","issues":[]}')
    assert seen["max_tokens"] == 8192  # thinking models need headroom beyond 2048
    _, seen = await _run(monkeypatch, tmp_path, '{"verdict":"pass","summary":"ok","issues":[]}',
                         ollama_max_tokens=1024)
    assert seen["max_tokens"] == 1024


def test_default_model_is_not_retired():
    # gemma3:27b was retired from Ollama Cloud on 2026-07-15; the default must be a live model.
    assert load_settings().ollama_model == "kimi-k2.7-code"
