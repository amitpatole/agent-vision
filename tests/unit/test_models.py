from agentvision.models import (
    BBox,
    Confidence,
    Issue,
    IssueKind,
    IssueSource,
    Report,
    Severity,
    Verdict,
)
from agentvision.models.report import verdict_from_issues


def _issue(kind=IssueKind.OTHER, sev=Severity.ERROR, conf=Confidence.HIGH, msg="x"):
    return Issue.make(kind, sev, msg, confidence=conf, source=IssueSource.DOM)


def test_detail_json_roundtrip():
    i = Issue.make(IssueKind.CONTRAST, Severity.ERROR, "low", detail={"ratio": 2.1})
    assert i.detail == {"ratio": 2.1}
    # detail is stored as a string (strict-schema safe)
    assert isinstance(i.detail_json, str)


def test_verdict_from_issues():
    assert verdict_from_issues([]) == Verdict.PASS
    assert verdict_from_issues([_issue(sev=Severity.WARNING)]) == Verdict.WARN
    assert verdict_from_issues([_issue(sev=Severity.ERROR)]) == Verdict.FAIL
    # low-confidence error never escalates past WARN on its own
    assert verdict_from_issues([_issue(sev=Severity.ERROR, conf=Confidence.LOW)]) == Verdict.WARN


def test_issue_signature_is_set_identity():
    r1 = Report(verdict=Verdict.FAIL, summary="", issues=[_issue(msg="A"), _issue(msg="B")])
    r2 = Report(verdict=Verdict.FAIL, summary="", issues=[_issue(msg="b"), _issue(msg="a")])
    # order- and case-insensitive
    assert r1.issue_signature() == r2.issue_signature()


def test_report_schema_is_shallow_and_closed():
    schema = Report.model_json_schema()
    assert "properties" in schema
    # no free-form dict on Issue.detail (it's a string field)
    assert "detail_json" in Issue.model_json_schema()["properties"]


def test_bbox_transforms():
    b = BBox(x=10, y=20, width=30, height=40)
    assert b.scaled(2).width == 60
    assert b.translated(5, 5).x == 15
    assert b.x2 == 40 and b.y2 == 60
