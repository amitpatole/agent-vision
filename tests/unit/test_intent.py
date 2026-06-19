"""Intent-conformance core logic (pure, no network/render)."""

from agentvision.core.intent import (
    build_conformance,
    check_claims_ocr,
    gate_verdict,
    ocr_violation_issues,
)
from agentvision.models.intent import Brief, IntentClaim
from agentvision.models.report import (
    ClaimResult,
    ClaimStatus,
    Confidence,
    Conformance,
    Importance,
    Issue,
    IssueKind,
    IssueSource,
    Severity,
    Verdict,
)


def test_claim_parse_importance_prefixes():
    assert IntentClaim.parse("must: title reads X").importance == Importance.MUST
    assert IntentClaim.parse("should - dark theme").importance == Importance.SHOULD
    assert IntentClaim.parse("(nice) a subtle shadow").importance == Importance.NICE
    assert IntentClaim.parse("logo top-left").importance == Importance.MUST  # default


def test_brief_from_inputs_and_empty():
    assert Brief.from_inputs().is_empty()
    b = Brief.from_inputs(text="an infographic", expect=["should: 4 stages", "", "  "])
    assert not b.is_empty()
    assert [c.text for c in b.claims] == ["4 stages"]
    assert b.claims[0].importance == Importance.SHOULD


def test_check_claims_ocr_present_and_absent():
    claims = [
        IntentClaim.parse('the title reads "AgentVision"'),
        IntentClaim.parse('a tab labeled "Settings"'),
        IntentClaim.parse("uses a dark theme"),  # no quotes -> not OCR-decidable
    ]
    res = check_claims_ocr(claims, "Welcome to AgentVision dashboard")
    assert res[0].status == ClaimStatus.SATISFIED
    assert res[1].status == ClaimStatus.VIOLATED
    assert 2 not in res  # left to the vision backend


def test_build_conformance_vision_flagged_and_unflagged():
    claims = [IntentClaim.parse("a"), IntentClaim.parse("b")]
    issues = [
        Issue.make(IssueKind.INTENT_MISMATCH, Severity.ERROR, "[#1] missing thing a",
                   confidence=Confidence.HIGH, source=IssueSource.VISION),
    ]
    conf = build_conformance(claims, issues, {}, semantic_graded=True)
    assert conf.claims[0].status == ClaimStatus.VIOLATED
    assert conf.claims[1].status == ClaimStatus.SATISFIED  # unflagged + graded


def test_build_conformance_not_graded_is_uncertain():
    claims = [IntentClaim.parse("a")]
    conf = build_conformance(claims, [], {}, semantic_graded=False)
    assert conf.claims[0].status == ClaimStatus.UNCERTAIN  # local backend can't claim PASS


def test_ocr_results_override_vision():
    claims = [IntentClaim.parse('title "X"')]
    ocr = check_claims_ocr(claims, "no match here")  # -> violated
    conf = build_conformance(claims, [], ocr, semantic_graded=True)
    assert conf.claims[0].status == ClaimStatus.VIOLATED
    assert conf.claims[0].source == IssueSource.OCR


def test_ocr_violation_issues():
    claims = [IntentClaim.parse('title "X"')]
    ocr = check_claims_ocr(claims, "nope")
    issues = ocr_violation_issues(ocr)
    assert len(issues) == 1
    assert issues[0].kind == IssueKind.INTENT_MISMATCH
    assert issues[0].message.startswith("[#1]")
    assert issues[0].severity == Severity.ERROR


def _one(importance, status):
    return Conformance(claims=[ClaimResult(text="a", importance=importance, status=status)])


def test_gate_verdict():
    assert gate_verdict(Verdict.PASS, _one(Importance.MUST, ClaimStatus.VIOLATED)) == Verdict.FAIL
    assert gate_verdict(Verdict.PASS, _one(Importance.SHOULD, ClaimStatus.VIOLATED)) == Verdict.WARN
    assert gate_verdict(Verdict.PASS, _one(Importance.MUST, ClaimStatus.UNCERTAIN)) == Verdict.WARN
    assert gate_verdict(Verdict.PASS, _one(Importance.MUST, ClaimStatus.SATISFIED)) == Verdict.PASS
    assert gate_verdict(Verdict.PASS, None) == Verdict.PASS


def test_conformance_score_and_matches_intent():
    conf = Conformance(claims=[
        ClaimResult(text="a", importance=Importance.MUST, status=ClaimStatus.SATISFIED),
        ClaimResult(text="b", importance=Importance.SHOULD, status=ClaimStatus.VIOLATED),
    ])
    assert conf.score == 0.5
    assert conf.matches_intent()  # only a SHOULD is violated -> intent (musts) still met

    conf2 = Conformance(claims=[
        ClaimResult(text="a", importance=Importance.MUST, status=ClaimStatus.VIOLATED),
    ])
    assert not conf2.matches_intent()
