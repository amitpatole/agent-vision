"""OpenAI / Gemini backends: token budgets and cut-off replies (no network, fake clients)."""

from __future__ import annotations

import pytest
from PIL import Image

import agentvision.config as cfg
from agentvision.backends.base import AnalysisRequest
from agentvision.config import DEFAULT_MODELS, load_settings
from agentvision.errors import BackendError
from agentvision.models.report import Verdict

CLEAN = '{"verdict":"pass","summary":"clean","issues":[]}'


def _img(tmp_path):
    p = tmp_path / "a.png"
    Image.new("RGB", (64, 64), "white").save(p)
    return AnalysisRequest(image_path=str(p))


# --- OpenAI -------------------------------------------------------------------------------

def _openai_fake(seen, content=CLEAN, finish_reason="stop"):
    class _Completions:
        async def create(self, **kw):
            seen.update(kw)
            msg = type("M", (), {"content": content})()
            choice = type("C", (), {"message": msg, "finish_reason": finish_reason})()
            return type("R", (), {"choices": [choice]})()

    class _Client:
        def __init__(self, api_key=None, **_):
            self.chat = type("Chat", (), {"completions": _Completions()})()

        async def close(self):
            pass

    return _Client


async def _openai(monkeypatch, tmp_path, **kw):
    pytest.importorskip("openai")
    import openai

    from agentvision.backends.openai_backend import OpenAIBackend

    seen: dict = {}
    fake_kw = {k: kw.pop(k) for k in ("content", "finish_reason") if k in kw}
    monkeypatch.setattr(openai, "AsyncOpenAI", _openai_fake(seen, **fake_kw))
    monkeypatch.setattr(cfg, "KEY_FILES", {})  # hermetic: never read a real key file
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    s = load_settings(**kw)
    return OpenAIBackend(s), seen


async def test_openai_sends_max_completion_tokens(monkeypatch, tmp_path):
    # GPT-5+ rejects max_tokens with a 400; max_completion_tokens works on every chat model.
    backend, seen = await _openai(monkeypatch, tmp_path)
    rep = await backend.analyze(_img(tmp_path))
    assert rep.verdict == Verdict.PASS
    assert "max_tokens" not in seen
    assert seen["max_completion_tokens"] == 8192


async def test_openai_budget_is_configurable_and_used_for_text(monkeypatch, tmp_path):
    backend, seen = await _openai(monkeypatch, tmp_path, content="ok", openai_max_tokens=1000)
    await backend.complete_text("sys", "user")
    assert "max_tokens" not in seen and seen["max_completion_tokens"] == 1000


async def test_openai_cut_off_reply_says_so(monkeypatch, tmp_path):
    backend, _ = await _openai(monkeypatch, tmp_path, content='{"verdict":"fa',
                               finish_reason="length")
    with pytest.raises(BackendError, match="cut off at the token limit"):
        await backend.analyze(_img(tmp_path))


# --- Gemini -------------------------------------------------------------------------------

def _gemini_fake(seen, text=CLEAN, finish_reason="STOP"):
    class _Models:
        async def generate_content(self, model, contents, config):
            seen.update(model=model, max_output_tokens=config.max_output_tokens)
            cand = type("Cand", (), {"finish_reason": finish_reason})()
            return type("R", (), {"text": text, "parsed": None, "candidates": [cand]})()

    class _Client:
        def __init__(self, api_key=None, **_):
            self.aio = type("Aio", (), {"models": _Models()})()

    return _Client


async def _gemini(monkeypatch, tmp_path, **kw):
    pytest.importorskip("google.genai")
    from google import genai

    from agentvision.backends.gemini_backend import GeminiBackend

    seen: dict = {}
    fake_kw = {k: kw.pop(k) for k in ("text", "finish_reason") if k in kw}
    monkeypatch.setattr(genai, "Client", _gemini_fake(seen, **fake_kw))
    monkeypatch.setattr(cfg, "KEY_FILES", {})
    monkeypatch.setenv("GOOGLE_API_KEY", "g-test")
    s = load_settings(**kw)
    return GeminiBackend(s), seen


async def test_gemini_budget_default_and_configurable(monkeypatch, tmp_path):
    backend, seen = await _gemini(monkeypatch, tmp_path)
    rep = await backend.analyze(_img(tmp_path))
    assert rep.verdict == Verdict.PASS and seen["max_output_tokens"] == 8192
    backend, seen = await _gemini(monkeypatch, tmp_path, text="ok", gemini_max_tokens=1000)
    await backend.complete_text("sys", "user")
    assert seen["max_output_tokens"] == 1000


async def test_gemini_cut_off_reply_says_so(monkeypatch, tmp_path):
    backend, _ = await _gemini(monkeypatch, tmp_path, text='{"verdict":"fa',
                               finish_reason="FinishReason.MAX_TOKENS")
    with pytest.raises(BackendError, match="cut off at the token limit"):
        await backend.analyze(_img(tmp_path))


def test_hosted_defaults_are_not_retired():
    # gemini-2.0-flash now returns 404 "no longer available"; gpt-4o-mini shuts down 2027-01-14.
    assert DEFAULT_MODELS["gemini"] != "gemini-2.0-flash"
    assert DEFAULT_MODELS["openai"] != "gpt-4o-mini"
