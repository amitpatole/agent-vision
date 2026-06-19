"""Generative loop control flow — faked analyze + backend, no rendering."""

import asyncio

import agentvision.core.generate as gen
from agentvision.models.intent import Brief
from agentvision.models.report import Report, Verdict


class _FakeBackend:
    name = "fake"

    def available(self) -> bool:
        return True

    async def complete_text(self, system: str, user: str) -> str:
        return "improved prompt"


def _report(verdict):
    return Report(verdict=verdict, summary="x", backend="fake")


def test_generative_loop_refines_until_pass(monkeypatch):
    verdicts = iter([Verdict.FAIL, Verdict.PASS])
    seen_prompts = []

    async def fake_analyze(source, **kw):
        return _report(next(verdicts))

    monkeypatch.setattr(gen, "analyze", fake_analyze)
    monkeypatch.setattr(
        "agentvision.backends.registry.select_backend",
        lambda settings, backend=None: (_FakeBackend(), None),
    )

    def generator(prompt):
        seen_prompts.append(prompt)
        return "/tmp/out.png"

    session = gen.GenerativeLoopSession(Brief.from_inputs(text="make X"), generator)
    history = asyncio.run(session.run(max_iter=3))

    assert len(history) == 2
    assert session.stop_reason == "matched intent"
    assert seen_prompts == ["make X", "improved prompt"]  # refined after the FAIL


def test_generative_loop_stops_when_cannot_refine(monkeypatch):
    async def fake_analyze(source, **kw):
        return _report(Verdict.FAIL)

    class _NoText:
        name = "local"

        async def complete_text(self, system, user):
            return ""

    monkeypatch.setattr(gen, "analyze", fake_analyze)
    monkeypatch.setattr(
        "agentvision.backends.registry.select_backend",
        lambda settings, backend=None: (_NoText(), None),
    )

    session = gen.GenerativeLoopSession(Brief.from_inputs(expect=["a thing"]),
                                        lambda p: "/tmp/out.png")
    history = asyncio.run(session.run(max_iter=3))
    assert len(history) == 1
    assert session.stop_reason == "cannot refine (no LLM backend available)"


def test_generative_loop_requires_nonempty_brief():
    import pytest

    with pytest.raises(ValueError):
        gen.GenerativeLoopSession(Brief(), lambda p: "x")
