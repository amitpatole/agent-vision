"""Unit tests for the pixel-grade contrast check (DOM text over a non-solid background).

Pins the worst-case sampler (a light patch under the text drags the ratio down) and the
check's routing: low-confidence samples are graded from real pixels; when the pixels can't be
read, the honest 'verify manually' advisory is kept; a measured-readable sample is dropped.
"""

from PIL import Image

from agentvision.core.checks._pixel_contrast import contrast_ratio, worst_case_contrast
from agentvision.core.checks.contrast import check_contrast_dom
from agentvision.core.checks.contrast_pixel import check_contrast_pixel
from agentvision.models.geometry import BBox, Viewport
from agentvision.models.report import Confidence, IssueSource
from agentvision.renderers.base import ContrastSample, RenderedImage, RenderResult


def _sample(**kw):
    base = dict(bbox=BBox(x=0, y=0, width=60, height=60), ratio=1.5, fg="#ffffff",
                bg="#eeeeee", font_px=14.0, large_text=False, passes_aa=False,
                passes_aaa=False, confidence="low", text="METRICS 42", selector=".popup")
    base.update(kw)
    return ContrastSample(**base)


def _render(samples, img_path):
    return RenderResult(
        images=[RenderedImage(path=str(img_path), viewport=Viewport(), width=60, height=60)],
        contrast_samples=samples,
    )


def test_worst_case_math_black_on_white():
    img = Image.new("RGB", (60, 60), (255, 255, 255))
    for y in range(20, 40):
        for x in range(60):
            img.putpixel((x, y), (0, 0, 0))
    res = worst_case_contrast(img)
    assert res and res[0] > 15  # black ink on white -> very high


def test_worst_case_picks_the_lower_contrast_patch():
    # Black text (the minority = ink) over a two-tone background: a mid-grey patch and a white
    # patch. Worst-case must grade the ink against the LOWER-contrast (mid-grey) patch, not the
    # flattering average that a single-sample measure would give.
    img = Image.new("RGB", (100, 40), (160, 160, 160))   # left/all mid-grey…
    for y in range(40):
        for x in range(50, 100):
            img.putpixel((x, y), (255, 255, 255))         # …right half white
    for y in range(18, 23):                               # thin black text strokes across width
        for x in range(100):
            img.putpixel((x, y), (0, 0, 0))
    res = worst_case_contrast(img)
    assert res is not None
    worst = res[0]
    # black-vs-white is ~21:1; black-vs-mid-grey is ~8:1 — worst-case must land near the latter.
    assert worst < contrast_ratio((0, 0, 0), (255, 255, 255))
    assert 5.0 < worst < 12.0


def test_check_flags_unreadable_over_canvas(tmp_path):
    # A light background under white text -> pixel grading should FAIL it.
    p = tmp_path / "shot.png"
    img = Image.new("RGB", (60, 60), (245, 245, 245))
    for y in range(24, 36):
        for x in range(60):
            img.putpixel((x, y), (255, 255, 255))  # white text on near-white
    img.save(p)
    issues = check_contrast_pixel(_render([_sample()], p), str(p))
    assert len(issues) == 1
    i = issues[0]
    assert i.source == IssueSource.CV               # pixel-derived tier, not DOM
    assert "worst-case" in i.message
    assert i.detail_json and "measured_ratio" in i.detail_json


def test_check_drops_measured_readable_sample(tmp_path):
    # White text over a solid BLACK region: measured contrast is high -> no issue (the
    # computed-style low-confidence guess was a false alarm).
    p = tmp_path / "ok.png"
    img = Image.new("RGB", (60, 60), (0, 0, 0))
    for y in range(24, 36):
        for x in range(60):
            img.putpixel((x, y), (255, 255, 255))
    img.save(p)
    issues = check_contrast_pixel(_render([_sample()], p), str(p))
    assert issues == []


def test_check_advises_when_no_image():
    # No image to read -> keep the honest advisory (don't silently drop the signal).
    issues = check_contrast_pixel(_render([_sample()], None), None)
    assert len(issues) == 1
    assert issues[0].confidence == Confidence.LOW
    assert "verify manually" in issues[0].message


def test_dom_check_cedes_low_confidence():
    # The DOM contrast check no longer emits anything for a non-solid (low-confidence) sample.
    assert check_contrast_dom(_render([_sample()], None)) == []
    # …but still hard-fails a solid-background (high-confidence) sample.
    solid = _sample(confidence="high", fg="#777777", bg="#888888")
    out = check_contrast_dom(_render([solid], None))
    assert len(out) == 1 and out[0].source == IssueSource.DOM
