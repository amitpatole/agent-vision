"""Tests for the offline PPTX slide inspector (contrast / off-slide / overlap)."""

import zipfile

from PIL import Image

from agentvision.core.checks.slides import _bimodal_contrast, _contrast, check_pptx
from agentvision.models.report import IssueKind

A = "xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\""
P = "xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\""
SW, SH = 9144000, 6858000  # 10 x 7.5 in EMU


def test_contrast_math():
    assert _contrast((0, 0, 0), (255, 255, 255)) > 20  # black on white
    assert _contrast((40, 40, 40), (55, 55, 55)) < 1.6  # dark on dark


def test_bimodal_on_clear_and_unreadable():
    # Black text strokes on white -> high contrast.
    hi = Image.new("RGB", (60, 60), (255, 255, 255))
    for y in range(20, 40):
        for x in range(60):
            hi.putpixel((x, y), (0, 0, 0))
    r_hi = _bimodal_contrast(hi)
    assert r_hi and r_hi[0] > 4.5

    # Dark-grey text on a dark background -> unreadable.
    lo = Image.new("RGB", (60, 60), (35, 35, 40))
    for y in range(20, 40):
        for x in range(60):
            lo.putpixel((x, y), (60, 60, 70))
    r_lo = _bimodal_contrast(lo)
    assert r_lo and r_lo[0] < 3.0


def _slide_xml(shape_xml: str) -> bytes:
    return (f"<p:sld {P} {A}><p:cSld><p:spTree>{shape_xml}"
            "</p:spTree></p:cSld></p:sld>").encode()


def _shape(x, y, cx, cy, text):
    return (f"<p:sp><p:spPr><a:xfrm><a:off x=\"{x}\" y=\"{y}\"/>"
            f"<a:ext cx=\"{cx}\" cy=\"{cy}\"/></a:xfrm></p:spPr>"
            f"<p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>")


def _build_pptx(path, slide_xml: bytes):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ppt/presentation.xml",
                   f"<p:presentation {P} {A}><p:sldSz cx=\"{SW}\" cy=\"{SH}\"/>"
                   "</p:presentation>")
        z.writestr("ppt/slides/slide1.xml", slide_xml)


def test_check_pptx_flags_offslide_and_contrast(tmp_path):
    pptx = tmp_path / "deck.pptx"
    # One shape running far past the right edge, over a dark-on-dark region.
    _build_pptx(pptx, _slide_xml(_shape(0, 0, SW * 2, SH // 6, "Way off slide and unreadable")))

    # Render image: dark background with a slightly-lighter dark text strip up top.
    img = Image.new("RGB", (1000, 750), (35, 35, 40))
    for y in range(10, 110):
        for x in range(1000):
            img.putpixel((x, y), (62, 62, 72))
    p = tmp_path / "page_001.png"
    img.save(p)

    issues = check_pptx(pptx, [str(p)])
    kinds = {i.kind for i in issues}
    assert IssueKind.OVERFLOW in kinds  # off-slide geometry
    assert IssueKind.CONTRAST in kinds  # unreadable pixels
    assert all(i.message.startswith("[slide 1]") for i in issues)


def test_check_pptx_clean_slide_no_false_positives(tmp_path):
    pptx = tmp_path / "ok.pptx"
    # Well-placed shape, comfortably inside the slide.
    _build_pptx(pptx, _slide_xml(_shape(914400, 914400, 3000000, 800000, "Readable title")))
    img = Image.new("RGB", (1000, 750), (255, 255, 255))  # white bg
    for y in range(100, 140):  # black text region
        for x in range(100, 400):
            img.putpixel((x, y), (0, 0, 0))
    p = tmp_path / "page_001.png"
    img.save(p)
    issues = check_pptx(pptx, [str(p)])
    assert issues == []


def test_check_pptx_handles_bad_file(tmp_path):
    bad = tmp_path / "notzip.pptx"
    bad.write_text("not a zip")
    assert check_pptx(bad, []) == []
