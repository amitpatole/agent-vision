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


def test_suppress_visual_missing_when_element_present():
    # vision says the 3D scene is missing, but a sizable <canvas> exists -> overrule it.
    issues = [_vis(IssueKind.MISSING_ELEMENT, "the 3D scene / canvas is not rendered")]
    kept, dropped = suppress_contradicted_vision(issues, None, visual_tags=["canvas"])
    assert dropped and not kept


def test_suppress_visual_chart_matches_svg_or_canvas():
    issues = [_vis(IssueKind.INTENT_MISMATCH, "[#1] the equity curve chart is missing")]
    kept, dropped = suppress_contradicted_vision(issues, None, visual_tags=["svg"])
    assert dropped and not kept


def test_suppress_visual_keeps_when_tag_absent():
    # claims a video is missing but only a canvas is present -> keep (genuinely could be missing)
    issues = [_vis(IssueKind.MISSING_ELEMENT, "the video player is missing")]
    kept, dropped = suppress_contradicted_vision(issues, None, visual_tags=["canvas"])
    assert kept and not dropped


def test_canvas_settle_default():
    from agentvision.config import load_settings
    assert load_settings().canvas_settle_ms == 1500


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


def test_wants_visual_judgment():
    from agentvision.core.analyze import _wants_visual_judgment
    from agentvision.models.intent import Brief, IntentClaim

    assert _wants_visual_judgment(Brief(text="a dashboard with an equity curve chart"), [])
    assert _wants_visual_judgment(None, [IntentClaim(text="the 3D scene renders")])
    assert not _wants_visual_judgment(Brief(text="a heading that reads Hello"),
                                      [IntentClaim(text='shows "Total"')])


def test_visual_crop_paths(tmp_path):
    from PIL import Image

    from agentvision.core.analyze import _visual_crop_paths
    from agentvision.models.geometry import BBox
    from agentvision.renderers.base import ElementBox

    img = tmp_path / "page.png"
    Image.new("RGB", (1000, 800), "white").save(img)
    els = [
        ElementBox(tag="canvas", bbox=BBox(x=100, y=100, width=400, height=300)),  # ok
        ElementBox(tag="img", bbox=BBox(x=10, y=10, width=20, height=20)),         # too small
        ElementBox(tag="svg", bbox=BBox(x=900, y=700, width=400, height=400)),     # clipped but ok
    ]
    crops = _visual_crop_paths(str(img), els, max_crops=3)
    assert 1 <= len(crops) <= 2  # the 20x20 is skipped
    for c in crops:
        assert Image.open(c).size[0] >= 32


def test_visual_crop_respects_max():
    import os
    import tempfile

    from PIL import Image

    from agentvision.core.analyze import _visual_crop_paths
    from agentvision.models.geometry import BBox
    from agentvision.renderers.base import ElementBox

    d = tempfile.mkdtemp()
    p = os.path.join(d, "p.png")
    Image.new("RGB", (2000, 2000), "white").save(p)
    els = [ElementBox(tag="canvas", bbox=BBox(x=i * 100, y=0, width=200, height=200))
           for i in range(6)]
    assert len(_visual_crop_paths(p, els, max_crops=2)) == 2


def test_new_render_defaults():
    s = load_settings()
    assert s.nav_wait == "load"           # not networkidle (no hang on polling pages)
    assert s.render_timeout_s == 60.0     # raised from 30
    assert s.freeze_animations is True    # freeze rAF/animations before capture
    assert s.settle_ms == 400             # let client-rendered data populate
    assert s.vision_max_edge_px == 2000   # downscale oversized screenshots
