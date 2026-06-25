"""Clipped/truncated-text check (work-item #1 from the FDE-dojo dogfood).

Pins the deterministic, no-LLM detection of text cut off by an SVG viewport or a DOM hard
overflow, plus the bbox clamp that keeps an off-screen-left element (negative x) from crashing
the contract's non-negative BBox.
"""

import asyncio
from pathlib import Path

import pytest

from agentvision import BBox, IssueKind, Severity
from agentvision.core.checks.layout import check_clipped_text
from agentvision.renderers.base import ClippedText, RenderResult


def _result(*clips: ClippedText) -> RenderResult:
    return RenderResult(clipped_text=list(clips))


def test_svg_clipped_is_error_high_confidence():
    r = _result(ClippedText(
        bbox=BBox(x=250, y=28, width=120, height=18),
        text="Frontend for FDE Interview", kind="svg_clipped", overflow_px=108,
    ))
    issues = check_clipped_text(r)
    assert len(issues) == 1
    iss = issues[0]
    assert iss.kind == IssueKind.CLIPPED
    assert iss.severity == Severity.ERROR
    assert "Frontend for FDE Interview" in iss.message
    assert iss.detail.get("kind") == "svg_clipped"
    assert iss.bbox_precise is True


def test_dom_truncation_is_warning_medium():
    r = _result(ClippedText(
        bbox=BBox(x=0, y=0, width=80, height=20),
        text="Frontend for FDE Interview track", kind="truncated", overflow_px=237,
    ))
    issues = check_clipped_text(r)
    assert len(issues) == 1
    assert issues[0].kind == IssueKind.CLIPPED
    assert issues[0].severity == Severity.WARNING


def test_no_clip_no_issue():
    assert check_clipped_text(_result()) == []


# --- bbox clamp (the latent crash an off-screen-left SVG label surfaced) ---

def test_img_bbox_clamps_negative_left():
    from agentvision.renderers.playwright_renderer import _img_bbox

    # x=-8 (off-screen left) must clamp to 0 with the visible remainder, not raise.
    box = _img_bbox(-8.0, 160.0, 100.0, 18.0, 1.0)
    assert box.x == 0.0
    assert box.width == pytest.approx(92.0)  # 100 - 8 clipped off the left
    assert box.y == 160.0


# --- e2e: render a real SVG whose <text> overflows its viewBox (pins the in-page JS) ---

_CLIPPED_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200" viewBox="0 0 300 200">
  <rect x="0" y="0" width="300" height="200" fill="#ffffff"/>
  <text x="130" y="100" font-size="12" fill="#111">Core</text>
  <text x="250" y="40" font-size="14" fill="#111">Frontend for FDE Interview</text>
  <text x="-8" y="160" font-size="14" fill="#111">FDE Interview Skills</text>
</svg>"""


def _chromium_available() -> bool:
    try:
        from agentvision import load_settings, render
    except Exception:  # noqa: BLE001
        return False
    try:
        asyncio.run(render("<html><body><p>ok</p></body></html>",
                           settings=load_settings(), source_type="html"))
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _chromium_available(), reason="Chromium not launchable in this env")
def test_e2e_svg_clipped_text_detected(tmp_path):
    from agentvision import check, load_settings

    svg = tmp_path / "radar.svg"
    svg.write_text(_CLIPPED_SVG)
    report = asyncio.run(check(str(svg), settings=load_settings(), use_ocr=False,
                               out_dir=Path(tmp_path / "out")))
    clips = [i for i in report.issues if i.kind == IssueKind.CLIPPED]
    texts = " ".join(i.message for i in clips)
    assert len(clips) == 2, f"expected 2 clipped labels, got {len(clips)}: {texts}"
    assert "Frontend for FDE Interview" in texts  # overflow right
    assert "FDE Interview Skills" in texts         # negative-x left clip
    assert "Core" not in texts                     # in-bounds label not flagged
    assert report.verdict.value == "fail"
