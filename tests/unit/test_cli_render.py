"""CLI report rendering — regression coverage for the agentsensory contract.

Pins the fact that `ClaimResult.source` (and `evidence`) are plain `str` in the shared
agentsensory contract, not enums. A previous build called `c.source.value` in
`_print_report`, which crashed `agentvision conform` with
`AttributeError: 'str' object has no attribute 'value'` after the 0.9.0 migration.
"""

from agentvision import (
    ClaimResult,
    ClaimStatus,
    Confidence,
    Conformance,
    Importance,
    Report,
    Verdict,
)
from agentvision.adapters.cli import _print_report


def test_print_report_with_conformance_str_source(capsys):
    """Rendering a conformance whose claim.source is a plain string must not raise."""
    report = Report(
        verdict=Verdict.FAIL,
        summary="Intent match: 0/1 requirement(s) satisfied.",
        conformance=Conformance(
            claims=[
                ClaimResult(
                    text="a 'View report' call-to-action link is visible",
                    importance=Importance.MUST,
                    status=ClaimStatus.VIOLATED,
                    confidence=Confidence.HIGH,
                    source="ocr",  # str in the agentsensory contract, NOT an enum
                ),
            ],
        ),
    )

    # The bug raised AttributeError here; the fix makes this print cleanly.
    _print_report(report, as_json=False)

    out = capsys.readouterr().out
    assert "View report" in out
    assert "(ocr)" in out  # the str source is rendered verbatim, no .value


def test_claimresult_source_is_plain_str():
    """Guard the contract assumption the renderer relies on."""
    claim = ClaimResult(text="x", source="vision")
    assert isinstance(claim.source, str)
    assert not hasattr(claim.source, "value") or isinstance(claim.source, str)
