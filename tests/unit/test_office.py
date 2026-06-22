"""Office/OpenDocument support — detection, hardening, and multi-page rendering.

Security-cadence regression pins for the LibreOffice conversion path (untrusted input):
service gate, byte cap, missing-dependency, and argv hardening (no shell, absolute path so a
'-'-leading filename can't become a flag, isolated profile, process-group kill). The
multi-page composite logic is tested deterministically with PIL images (no poppler needed).
"""

import asyncio
from pathlib import Path

import pytest

import agentvision.office as O
from agentvision import load_settings
from agentvision.errors import MissingDependencyError, RenderError, UnsafeSourceError
from agentvision.office import OFFICE_EXT, convert_to_pdf, find_soffice
from agentvision.renderers.pdf_renderer import build_document_result, rasterize_pdf
from agentvision.sources import resolve_source

# --- detection ---

@pytest.mark.parametrize("name", ["deck.pptx", "report.docx", "sheet.xlsx", "notes.odt", "a.rtf"])
def test_office_extensions_detected(tmp_path, name):
    f = tmp_path / name
    f.write_bytes(b"stub")  # content irrelevant; detection is by extension
    resolved = resolve_source(str(f), settings=load_settings())
    assert resolved.kind == "office"
    assert resolved.path == f


def test_office_ext_set_covers_common_formats():
    for e in (".docx", ".pptx", ".xlsx", ".odt", ".odp", ".ods", ".doc", ".ppt", ".xls"):
        assert e in OFFICE_EXT


# --- conversion hardening (no soffice required: we gate/stat/mock before exec) ---

def _rtf(tmp_path) -> Path:
    f = tmp_path / "x.rtf"
    f.write_text(r"{\rtf1 hi\par}")
    return f


async def test_service_gate_blocks_office(tmp_path):
    with pytest.raises(UnsafeSourceError):
        await convert_to_pdf(_rtf(tmp_path), tmp_path / "o", load_settings(allow_office_render=False))


async def test_byte_cap_blocks_large_document(tmp_path):
    with pytest.raises(RenderError):
        await convert_to_pdf(_rtf(tmp_path), tmp_path / "o", load_settings(max_document_bytes=3))


async def test_missing_libreoffice_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(O.shutil, "which", lambda name: None)
    with pytest.raises(MissingDependencyError):
        await convert_to_pdf(_rtf(tmp_path), tmp_path / "o", load_settings(soffice_path=None))


async def test_conversion_argv_is_hardened(tmp_path, monkeypatch):
    cap = {}

    async def fake_exec(*argv, **kw):
        cap["argv"] = argv
        cap["kw"] = kw
        raise OSError("short-circuit before real exec")

    monkeypatch.setattr(O.asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(RenderError):
        await convert_to_pdf(_rtf(tmp_path), tmp_path / "o", load_settings())
    argv = cap["argv"]
    assert cap["kw"].get("start_new_session") is True          # own group → kill soffice.bin too
    assert argv[-1].startswith("/")                             # absolute path: no option injection
    assert "--convert-to" in argv and "pdf" in argv
    assert any("UserInstallation" in a for a in argv)           # isolated throwaway profile
    assert not any(a == "--no-sandbox" for a in argv)           # (sanity: not a browser arg leak)


# --- multi-page composite (deterministic; PIL only) ---

def _img(w, h, color):
    from PIL import Image
    return Image.new("RGB", (w, h), color)


def test_single_page_has_no_composite(tmp_path):
    res = build_document_result([_img(800, 1000, (255, 255, 255))], "pdf", tmp_path)
    assert len(res.images) == 1
    assert Path(res.primary.path).name == "page_001.png"


def test_multi_page_prepends_stacked_composite(tmp_path):
    pages = [_img(800, 1000, (255, 0, 0)), _img(800, 1000, (0, 255, 0)),
             _img(800, 1000, (0, 0, 255))]
    res = build_document_result(pages, "office", tmp_path)
    # composite primary + one image per page
    assert len(res.images) == 4
    assert Path(res.primary.path).name == "document.png"
    assert res.primary.height > 1000  # taller than a single page (pages stacked)
    assert [Path(i.path).name for i in res.images[1:]] == ["page_001.png", "page_002.png",
                                                           "page_003.png"]


def test_composite_stays_under_pixel_cap(tmp_path):
    from agentvision.imageguard import MAX_IMAGE_PIXELS
    # Many tall pages would exceed the decompression-bomb cap if not scaled down.
    pages = [_img(2000, 3000, (255, 255, 255)) for _ in range(20)]
    res = build_document_result(pages, "pdf", tmp_path)
    assert res.primary.width * res.primary.height <= MAX_IMAGE_PIXELS


def test_pdf_byte_cap(tmp_path):
    fake = tmp_path / "big.pdf"
    fake.write_bytes(b"%PDF-1.4 " + b"0" * 500)
    with pytest.raises(RenderError):
        rasterize_pdf(fake, load_settings(max_document_bytes=100))


# --- end-to-end (real LibreOffice + poppler) ---

def _have_tools() -> bool:
    import shutil
    return bool(find_soffice(load_settings())) and bool(shutil.which("pdftoppm"))


@pytest.mark.skipif(not _have_tools(), reason="LibreOffice and/or poppler not installed")
async def test_e2e_office_multipage_render(tmp_path):
    from agentvision.core import render

    rtf = (r"{\rtf1\ansi\fs28 Page one.\par\page Page two.\par\page Page three.\par}")
    f = tmp_path / "deck.rtf"
    f.write_text(rtf)
    res = await render(str(f), settings=load_settings())
    assert res.source_type == "office"
    assert Path(res.primary.path).name == "document.png"   # composite primary
    assert len(res.images) == 4                            # composite + 3 pages


@pytest.mark.skipif(not _have_tools(), reason="LibreOffice and/or poppler not installed")
async def test_e2e_real_docx_render(tmp_path):
    """Convert a real .docx (OOXML) — the format users actually have — end to end."""
    from agentvision.core import render

    # Make a genuine .docx from RTF via LibreOffice, then render that .docx.
    src = tmp_path / "src.rtf"
    src.write_text(r"{\rtf1\ansi\fs28 A real docx page.\par\page Second page.\par}")
    pdf = await convert_to_pdf(src, tmp_path / "viapdf", load_settings())  # sanity: tool works
    assert pdf.exists()
    proc = await asyncio.create_subprocess_exec(
        find_soffice(load_settings()), "--headless", "--convert-to", "docx",
        "--outdir", str(tmp_path), str(src.resolve()),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()
    docx = tmp_path / "src.docx"
    assert docx.exists(), "failed to synthesize a .docx fixture"
    res = await render(str(docx), settings=load_settings())
    assert res.source_type == "office"
    assert len(res.images) >= 3  # composite + >= 2 pages
