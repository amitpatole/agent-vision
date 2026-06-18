import pytest

from agentvision.core.checks.spelling import check_spelling_from_ocr
from agentvision.models.geometry import BBox
from agentvision.models.report import IssueKind
from agentvision.ocr.base import OcrResult, OcrWord

pytest.importorskip("spellchecker")


def _ocr(*tokens):
    return OcrResult(text=" ".join(tokens), words=[
        OcrWord(text=t, bbox=BBox(x=1, y=1, width=10, height=10), confidence=0.95)
        for t in tokens
    ])


def test_flags_misspelling():
    issues = check_spelling_from_ocr(_ocr("repaut", "until", "pass"))
    assert any(i.kind == IssueKind.TYPO and i.detail.get("word") == "repaut" for i in issues)


def test_ignores_correct_and_whitelisted_words():
    issues = check_spelling_from_ocr(_ocr("AgentVision", "github", "render", "perceive", "report"))
    assert issues == []


def test_handles_hyphenated_compounds():
    # "self-verifies" -> ["self","verifies"] both valid -> no flag
    assert check_spelling_from_ocr(_ocr("self-verifies")) == []


def test_skips_short_acronyms():
    assert check_spelling_from_ocr(_ocr("DOM", "WCAG", "API")) == []
