"""Fixes from the live-dashboard field report: vision/DOM cross-check, downscale, new defaults."""

from agentvision.backends._image import load_image_b64
from agentvision.config import load_settings
from agentvision.core.intent import suppress_contradicted_vision
from agentvision.models.report import (
    Confidence,
    Issue,
    IssueKind,
    IssueSource,
    Severity,
)


def _vis(kind, msg):
    return Issue.make(kind, Severity.ERROR, msg, source=IssueSource.VISION,
                      confidence=Confidence.MEDIUM)


def test_suppress_contradicted_vision_drops_present_element():
    # vision says it's missing, but DOM/OCR proves the text is there -> drop the false fail.
    issues = [_vis(IssueKind.MISSING_ELEMENT, 'the "TODAY\'S NET" card is missing')]
    kept, dropped = suppress_contradicted_vision(issues, "Dashboard TODAY'S NET equity curve")
    assert kept == [] and len(dropped) == 1


def test_suppress_keeps_genuinely_missing():
    issues = [_vis(IssueKind.MISSING_ELEMENT, 'the "Checkout" button is missing')]
    kept, dropped = suppress_contradicted_vision(issues, "Home About Contact")
    assert len(kept) == 1 and dropped == []


def test_suppress_contradicted_intent_mismatch():
    issues = [_vis(IssueKind.INTENT_MISMATCH, '[#1] expected "Equity Curve" — not visible')]
    kept, dropped = suppress_contradicted_vision(issues, "regime EQUITY CURVE pnl")
    assert dropped and not kept


def test_suppress_ignores_non_vision_and_unquoted():
    dom = Issue.make(IssueKind.MISSING_ELEMENT, Severity.ERROR, 'the "X" is missing',
                     source=IssueSource.DOM)
    unquoted = _vis(IssueKind.MISSING_ELEMENT, "something seems off")
    kept, dropped = suppress_contradicted_vision([dom, unquoted], "X")
    assert dropped == []  # DOM-sourced and unquoted vision are never auto-suppressed
    assert len(kept) == 2


def test_suppress_empty_haystack_is_noop():
    issues = [_vis(IssueKind.MISSING_ELEMENT, 'the "X" is missing')]
    kept, dropped = suppress_contradicted_vision(issues, "")
    assert kept == issues and dropped == []


def test_load_image_b64_downscales_oversized(tmp_path):
    from PIL import Image

    p = tmp_path / "big.png"
    Image.new("RGB", (4000, 1000), "white").save(p)
    _b64, media, size = load_image_b64(str(p), max_edge=2000)
    assert max(size) == 2000  # longest edge capped
    assert size == (2000, 500)  # aspect ratio preserved
    assert media == "image/png"


def test_load_image_b64_leaves_small_images(tmp_path):
    from PIL import Image

    p = tmp_path / "small.png"
    Image.new("RGB", (800, 600), "white").save(p)
    _b64, _media, size = load_image_b64(str(p), max_edge=2000)
    assert size == (800, 600)


def test_new_render_defaults():
    s = load_settings()
    assert s.nav_wait == "load"           # not networkidle (no hang on polling pages)
    assert s.render_timeout_s == 60.0     # raised from 30
    assert s.freeze_animations is True    # freeze rAF/animations before capture
    assert s.settle_ms == 400             # let client-rendered data populate
    assert s.vision_max_edge_px == 2000   # downscale oversized screenshots
