"""The eyes→brain handoff signal (Report -> Handoff)."""

from agentvision.models.handoff import Handoff, NextAction
from agentvision.models.report import (
    ClaimResult,
    ClaimStatus,
    Confidence,
    Conformance,
    Importance,
    Issue,
    IssueKind,
    IssueSource,
    Report,
    Severity,
    Verdict,
)


def test_pass_report_hands_off_done():
    h = Report(verdict=Verdict.PASS, summary="looks good", backend="local").to_handoff()
    assert h.next_action == NextAction.DONE
    assert h.todo == []
    assert h.matches_intent is None  # no brief graded


def test_fail_report_builds_prioritized_todo():
    report = Report(
        verdict=Verdict.FAIL, summary="x", backend="anthropic", model="claude-haiku-4-5",
        issues=[
            Issue.make(IssueKind.CONTRAST, Severity.ERROR, "low contrast header"),
            Issue.make(IssueKind.OVERFLOW, Severity.CRITICAL, "hero overflows"),
            Issue.make(IssueKind.OTHER, Severity.INFO, "fyi only"),  # excluded from todo
        ],
    )
    h = report.to_handoff()
    assert h.next_action == NextAction.REVISE
    assert h.todo[0] == "[overflow] hero overflows"  # critical sorts first
    assert any("low contrast" in t for t in h.todo)
    assert all("fyi only" not in t for t in h.todo)  # info severity not actionable
    assert h.backend == "anthropic" and h.model == "claude-haiku-4-5"


def test_warn_report_is_review():
    h = Report(verdict=Verdict.WARN, summary="x", backend="local").to_handoff()
    assert h.next_action == NextAction.REVIEW


def test_conformance_unmet_musts_and_open_questions():
    conf = Conformance(claims=[
        ClaimResult(text="a Checkout button", importance=Importance.MUST,
                    status=ClaimStatus.VIOLATED),
        ClaimResult(text="dark theme", importance=Importance.MUST,
                    status=ClaimStatus.UNCERTAIN),
        ClaimResult(text="nice shadow", importance=Importance.SHOULD,
                    status=ClaimStatus.SATISFIED),
    ])
    report = Report(verdict=Verdict.FAIL, summary="x", backend="anthropic", conformance=conf)
    h = report.to_handoff()
    assert h.matches_intent is False
    assert any("[intent/must] a Checkout button" in t for t in h.todo)
    assert any("Verify: dark theme" in q for q in h.open_questions)


def test_low_confidence_defect_becomes_open_question():
    report = Report(
        verdict=Verdict.WARN, summary="x", backend="openai",
        issues=[Issue.make(IssueKind.LAYOUT, Severity.ERROR, "maybe misaligned",
                           confidence=Confidence.LOW, source=IssueSource.VISION)],
    )
    h = report.to_handoff()
    assert any("Uncertain: maybe misaligned" in q for q in h.open_questions)


def test_handoff_roundtrips_json():
    h = Report(verdict=Verdict.PASS, summary="ok", backend="local").to_handoff()
    assert Handoff.model_validate_json(h.model_dump_json()).next_action == NextAction.DONE
