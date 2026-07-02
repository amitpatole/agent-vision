"""Unit tests for OCR-driven contrast on text painted INTO a <canvas> (no DOM handle).

Deterministic: a synthetic RenderResult (canvas region + DOM boxes) + OcrResult + a crafted
PNG, so we pin the routing (only painted-in, unreadable, confident, multi-char words are
flagged) without depending on a live Tesseract reading canvas pixels.
"""

from PIL import Image

from agentvision.core.checks.contrast_ocr import check_contrast_ocr
from agentvision.models.geometry import BBox, Viewport
from agentvision.models.report import IssueSource
from agentvision.ocr.base import OcrResult, OcrWord
from agentvision.renderers.base import ElementBox, RenderedImage, RenderResult


def _img(tmp_path):
    # 200x100 near-white; thin pure-white "text" strokes in the painted-in word's box -> the
    # crop's worst-case contrast is ~1.1:1 (unreadable).
    im = Image.new("RGB", (200, 100), (240, 240, 240))
    for y in range(48, 52):
        for x in range(10, 130):
            im.putpixel((x, y), (255, 255, 255))
    p = tmp_path / "canvas.png"
    im.save(p)
    return str(p)


def _render():
    return RenderResult(
        images=[RenderedImage(path="x", viewport=Viewport(), width=200, height=100)],
        visual_elements=[ElementBox(tag="canvas", bbox=BBox(x=0, y=0, width=200, height=100))],
        dom_boxes=[ElementBox(tag="div", text="Legend",
                              bbox=BBox(x=10, y=10, width=50, height=15))],
    )


def _ocr():
    return OcrResult(words=[
        # painted into the canvas, no DOM overlap, confident, multi-char -> candidate
        OcrWord(text="SECTORLOAD", bbox=BBox(x=10, y=40, width=120, height=20), confidence=0.8),
        # overlaps a DOM text box -> DOM-backed, must be skipped
        OcrWord(text="Legend", bbox=BBox(x=10, y=10, width=50, height=15), confidence=0.9),
        # low OCR confidence -> skipped (evidence threshold)
        OcrWord(text="blurry", bbox=BBox(x=150, y=60, width=30, height=15), confidence=0.3),
        # single glyph -> skipped
        OcrWord(text="x", bbox=BBox(x=150, y=80, width=8, height=8), confidence=0.9),
    ])


def test_flags_only_the_painted_in_unreadable_word(tmp_path):
    issues = check_contrast_ocr(_render(), _img(tmp_path), _ocr())
    assert len(issues) == 1
    i = issues[0]
    assert i.source == IssueSource.OCR
    assert "painted into a <canvas>" in i.message
    assert "SECTORLOAD" in i.message
    assert i.detail_json and "no_dom_handle" in i.detail_json


def test_no_canvas_means_no_issue(tmp_path):
    r = _render()
    r.visual_elements = []  # no canvas region → nothing to inspect
    assert check_contrast_ocr(r, _img(tmp_path), _ocr()) == []


def test_no_ocr_means_no_issue(tmp_path):
    assert check_contrast_ocr(_render(), _img(tmp_path), None) == []


def test_readable_painted_text_not_flagged(tmp_path):
    # Black strokes on the near-white canvas -> high contrast -> not flagged.
    im = Image.new("RGB", (200, 100), (245, 245, 245))
    for y in range(48, 52):
        for x in range(10, 130):
            im.putpixel((x, y), (0, 0, 0))
    p = tmp_path / "ok.png"
    im.save(p)
    ocr = OcrResult(words=[
        OcrWord(text="READABLE", bbox=BBox(x=10, y=40, width=120, height=20), confidence=0.9)])
    assert check_contrast_ocr(_render(), str(p), ocr) == []
