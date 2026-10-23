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


# --- Commonwealth variants + house vocabulary (pilot: global English, show/talent names) ---

@pytest.mark.parametrize("word", [
    "Harbour", "centre", "colour", "organisation", "analysed", "catalogue", "defence",
    "travelled", "programme", "favourite", "theatres",
])
def test_accepts_commonwealth_spellings(word):
    assert check_spelling_from_ocr(_ocr(word)) == []


@pytest.mark.parametrize("word", ["fourm", "seasn", "Premeire", "anounces", "houshold",
                                  "lagre", "nevre", "sevre"])
def test_variants_do_not_mask_real_typos(word):
    assert check_spelling_from_ocr(_ocr(word)), f"{word!r} should still be flagged"


def test_variants_can_be_disabled():
    assert check_spelling_from_ocr(_ocr("Harbour"), variants=False)


def test_extra_words_allowlist():
    assert check_spelling_from_ocr(_ocr("Zorblax"))
    assert check_spelling_from_ocr(_ocr("Zorblax"), extra_words=frozenset({"zorblax"})) == []


def test_settings_vocabulary_from_words_and_file(tmp_path):
    from agentvision.config import load_settings

    f = tmp_path / "vocab.txt"
    f.write_text("# show names\nZorblax\nQuentaro Vell  # host\n")
    s = load_settings(spell_allow_words=["Brandly"], spell_allow_file=f)
    assert s.spell_vocabulary() == frozenset({"zorblax", "quentaro", "vell", "brandly"})


def test_settings_vocabulary_file_is_size_capped(tmp_path):
    from agentvision.config import load_settings
    from agentvision.errors import ConfigError

    f = tmp_path / "big.txt"
    f.write_text("word\n" * 100)
    s = load_settings(spell_allow_file=f, spell_allow_file_max_bytes=50)
    with pytest.raises(ConfigError):
        s.spell_vocabulary()


def test_settings_vocabulary_missing_file_fails_closed(tmp_path):
    from agentvision.config import load_settings
    from agentvision.errors import ConfigError

    s = load_settings(spell_allow_file=tmp_path / "nope.txt")
    with pytest.raises(ConfigError):
        s.spell_vocabulary()


def test_vocabulary_file_must_be_regular(tmp_path):
    # Red-team R1: a FIFO would block open() forever.
    import os

    from agentvision.config import load_settings
    from agentvision.errors import ConfigError

    fifo = tmp_path / "vocab.fifo"
    os.mkfifo(fifo)
    with pytest.raises(ConfigError):
        load_settings(spell_allow_file=fifo).spell_vocabulary()


def test_vocabulary_cap_is_bytes(tmp_path):
    from agentvision.config import load_settings
    from agentvision.errors import ConfigError

    f = tmp_path / "u8.txt"
    f.write_text("é" * 40, encoding="utf-8")  # 40 chars, 80 bytes
    with pytest.raises(ConfigError):
        load_settings(spell_allow_file=f, spell_allow_file_max_bytes=60).spell_vocabulary()


@pytest.mark.parametrize("word", ["sise", "bise"])
def test_short_stem_ise_typos_still_flagged(word):
    # Red-team R3: "-ise -> -ize" on a 1-letter stem turned typos into "size"/"bize".
    assert check_spelling_from_ocr(_ocr(word))


@pytest.mark.parametrize("word", ["histoury", "victoury", "doctour", "majour", "gaol",
                                  "feelling", "dealling", "smilling"])
def test_british_rules_do_not_mask_common_typos(word):
    assert check_spelling_from_ocr(_ocr(word)), f"{word!r} must still be flagged"
