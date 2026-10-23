"""Deterministic DOM checks added for the media pilot (bench corpus misses), plus OCR fail-closed.

- container_clipped: text partially cut by an ancestor's overflow:hidden (any axis), while
  fully-hidden text (off-screen carousel slides) and line-clamp stay unflagged.
- overlap: a positioned element covering text, hit-test confirmed.
- error_text: visible error copy, narrow patterns (news copy saying "failed" is fine).
- OCR that is installed but fails adds a WARNING (text checks did not run), never a silent PASS.
"""

from __future__ import annotations

import asyncio

import pytest

from agentvision import IssueKind, load_settings

WRAP = "<!doctype html><html><body style='margin:0;padding:20px;font:16px Arial'>{}</body></html>"


def _chromium_available() -> bool:
    try:
        from agentvision import render

        asyncio.run(render("<html><body><p>ok</p></body></html>",
                           settings=load_settings(), source_type="html"))
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _chromium_available(),
                                reason="Chromium not launchable in this env")


def _kinds(html: str, tmp_path) -> list:
    from agentvision import check

    f = tmp_path / "p.html"
    f.write_text(WRAP.format(html))
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), use_ocr=False))
    return rep.issues


def _of(issues, kind):
    return [i for i in issues if i.kind == kind]


def test_container_vertical_clip_flagged(tmp_path):
    issues = _kinds("<div style='width:300px;height:40px;overflow:hidden'><h2 style="
                    "'margin:0;font-size:24px'>Central bank holds rates steady as inflation "
                    "cools faster than expected</h2></div>", tmp_path)
    c = _of(issues, IssueKind.CLIPPED)
    assert c and c[0].detail["kind"] == "container_clipped"


def test_fully_hidden_carousel_slide_not_flagged(tmp_path):
    issues = _kinds("<div style='width:300px;height:60px;overflow:hidden;position:relative'>"
                    "<p style='margin:0'>Slide one</p>"
                    "<p style='position:absolute;left:400px;top:0;margin:0'>Slide two</p></div>",
                    tmp_path)
    assert not _of(issues, IssueKind.CLIPPED)


def test_line_clamp_not_flagged(tmp_path):
    issues = _kinds("<p style='width:200px;display:-webkit-box;-webkit-line-clamp:2;"
                    "-webkit-box-orient:vertical;overflow:hidden;margin:0'>"
                    + "long words " * 40 + "</p>", tmp_path)
    assert not _of(issues, IssueKind.CLIPPED)


def test_fitting_card_not_flagged(tmp_path):
    issues = _kinds("<div style='width:500px;overflow:hidden'><h2>Short headline</h2></div>",
                    tmp_path)
    assert not _of(issues, IssueKind.CLIPPED)


def test_positioned_badge_over_text_flagged(tmp_path):
    issues = _kinds("<div style='position:relative;width:500px'><span style='position:absolute;"
                    "top:4px;left:30px;background:#e63946;color:#fff;padding:6px'>LIVE NOW</span>"
                    "<h2 style='margin:0;font-size:28px'>Election night results</h2></div>",
                    tmp_path)
    o = _of(issues, IssueKind.OVERLAP)
    assert o and "Election night" in o[0].message


def test_badge_beside_text_not_flagged(tmp_path):
    issues = _kinds("<div style='position:relative;width:600px;padding-top:40px'><span style="
                    "'position:absolute;top:0;left:0;background:#e63946;color:#fff'>LIVE</span>"
                    "<h2 style='margin:0'>Election night results</h2></div>", tmp_path)
    assert not _of(issues, IssueKind.OVERLAP)


@pytest.mark.parametrize("copy", [
    "Error 403: Playback failed.", "Something went wrong. Please try again.",
    "[object Object]", "This title is not available in your region.",
])
def test_visible_error_copy_flagged(tmp_path, copy):
    assert _of(_kinds(f"<p>{copy}</p>", tmp_path), IssueKind.ERROR_TEXT)


@pytest.mark.parametrize("copy", [
    "Peace talks failed after a long night of negotiation.",
    "The error in the forecast was smaller than last year.",
    "Room 404 hosts the press briefing at noon.",
])
def test_news_copy_not_flagged_as_error(tmp_path, copy):
    assert not _of(_kinds(f"<p>{copy}</p>", tmp_path), IssueKind.ERROR_TEXT)


def test_ocr_failure_fails_closed(tmp_path, monkeypatch):
    from agentvision import check
    from agentvision.models.report import Verdict
    from agentvision.ocr import tesseract

    class _Boom:
        def available(self):
            return True

        def run(self, path):
            raise RuntimeError("Tesseract process timeout")

    import agentvision.ocr as ocr_pkg

    monkeypatch.setattr(ocr_pkg, "get_ocr_backend", lambda: _Boom())
    assert tesseract  # module import is fine
    f = tmp_path / "p.html"
    f.write_text(WRAP.format("<p>Clean page.</p>"))
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True)))
    assert rep.verdict == Verdict.FAIL
    assert any("OCR failed" in i.message for i in rep.issues)


# --- Red-team R1: a page must not suppress or stall the DOM grader -------------------------

_DEFECTS = ("<p style='color:#ddd'>Hard to read promo copy here</p>"
            "<img src='missing.png' width='100' height='50' alt='x'>")


@pytest.mark.parametrize("poison", [
    "Range.prototype.getClientRects=()=>{throw 1};",
    "const _t=RegExp.prototype.test;RegExp.prototype.test=function(s){throw 1};",
    "Element.prototype.getBoundingClientRect=function(){return {left:0,top:0,right:0,"
    "bottom:0,width:0,height:0}};",
    "window.getComputedStyle=()=>{throw 1};",
])
def test_prototype_poisoning_cannot_hide_defects(tmp_path, poison):
    issues = _kinds(f"<script>{poison}</script>{_DEFECTS}", tmp_path)
    kinds = {i.kind for i in issues}
    assert IssueKind.CONTRAST in kinds and IssueKind.BROKEN_IMAGE in kinds, kinds


def test_pointer_events_overlay_flood_does_not_stall(tmp_path):
    import time

    spans = "".join(f"<span style='font-size:9px'>w{i} </span>" for i in range(1500))
    overlays = "".join("<div style='position:absolute;inset:0;pointer-events:none;"
                       "transform:rotate(0.01deg)'></div>" for _ in range(400))
    t0 = time.monotonic()
    _kinds(f"<div style='position:relative'>{spans}{overlays}</div>", tmp_path)
    assert time.monotonic() - t0 < 30, "overlay flood stalled the grader"


def test_extraction_failure_is_a_fail(monkeypatch, tmp_path):
    from agentvision import check
    from agentvision.models.report import Verdict
    from agentvision.renderers import playwright_renderer as pr

    real = pr._evaluate_isolated

    async def _boom(page, fn_js, **k):
        if fn_js is pr.EXTRACT_JS:
            raise RuntimeError("isolated world unavailable")
        return await real(page, fn_js, **k)

    monkeypatch.setattr(pr, "_evaluate_isolated", _boom)
    f = tmp_path / "p.html"
    f.write_text(WRAP.format("<p>Clean.</p>"))
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), use_ocr=False))
    assert rep.verdict == Verdict.FAIL
    assert any("DOM checks could not run" in i.message for i in rep.issues)


def test_offline_quoted_claim_reads_light_on_dark(tmp_path):
    # Bench finding: OCR missed a white-on-blue "Subscribe" button, so the offline check
    # falsely VIOLATED a met requirement. Claims are now OCR-only, read normal AND inverted.
    from agentvision import check
    from agentvision.models.intent import Brief
    from agentvision.models.report import Verdict

    f = tmp_path / "p.html"
    f.write_text(WRAP.format("<a style='background:#0b5394;color:#fff;padding:12px 22px'>"
                             "Subscribe</a>"))
    brief = Brief.from_inputs(expect=['must: a "Subscribe" button is visible'])
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), brief=brief))
    assert rep.verdict != Verdict.FAIL
    assert rep.conformance and not rep.conformance.violated


# --- Red-team R2: caps, truncation, shared-cap crowding, forged visuals, colour syntax ------

_LOW = "<p style='color:#eee;background:#fff'>Low contrast promo copy</p>"


def test_element_cap_never_grades_clean(tmp_path):
    from agentvision import check
    from agentvision.models.report import Verdict

    f = tmp_path / "p.html"
    f.write_text(WRAP.format("<h1>Hello</h1>" + "<i></i>" * 60 + _LOW))
    s = load_settings(ephemeral=True, dom_max_elements=30)
    rep = asyncio.run(check(str(f), settings=s, use_ocr=False))
    assert rep.verdict == Verdict.FAIL
    assert any("hit their limit" in i.message for i in rep.issues)


def test_budget_truncation_is_a_fail(tmp_path):
    from agentvision import check
    from agentvision.models.report import Verdict

    flood = "".join("<p style='width:10px;font-size:4px'>" + "w " * 4000 + "</p>"
                    for _ in range(20))
    f = tmp_path / "p.html"
    f.write_text(WRAP.format(flood + _LOW))
    s = load_settings(ephemeral=True, dom_budget_ms=1)
    rep = asyncio.run(check(str(f), settings=s, use_ocr=False))
    assert rep.verdict == Verdict.FAIL


def test_container_clips_cannot_crowd_out_svg_clip(tmp_path):
    decoys = "".join("<div style='width:60px;height:12px;overflow:hidden;display:inline-block'>"
                     "<span style='white-space:nowrap'>decoy decoy decoy decoy</span></div>"
                     for _ in range(205))
    svg = ("<svg width='100' height='40'><text x='-30' y='20' font-size='14'>"
           "Clipped svg label</text></svg>")
    issues = _kinds(decoys + svg, tmp_path)
    assert any(i.detail.get("kind") == "svg_clipped" for i in issues)


def test_forged_query_selector_cannot_fake_visuals(tmp_path):
    from agentvision import render

    page = ("<script>const q=Document.prototype.querySelectorAll;"
            "Document.prototype.querySelectorAll=function(s){if(s.includes('canvas'))"
            "return [{tagName:'CANVAS',getBoundingClientRect:()=>({left:0,top:0,width:500,"
            "height:300})}];return q.call(this,s)};</script><p>No chart here.</p>")
    f = tmp_path / "p.html"
    f.write_text(WRAP.format(page))
    r = asyncio.run(render(str(f), settings=load_settings(ephemeral=True)))
    assert "canvas" not in r.visual_tags


@pytest.mark.parametrize("fg", ["oklch(0.95 0 0)", "color(srgb 0.93 0.93 0.93)"])
def test_modern_colour_syntax_is_graded(tmp_path, fg):
    issues = _kinds(f"<p style='color:{fg};background:#fff'>Hard to read copy</p>"
                    "<p>Other readable content on the page</p>", tmp_path)
    assert _of(issues, IssueKind.CONTRAST)


def test_dotenv_off_under_ci_unless_opted_in(monkeypatch):
    from agentvision.config import dotenv_enabled

    monkeypatch.delenv("AGENTVISION_DOTENV", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CI", raising=False)
    assert dotenv_enabled()
    monkeypatch.setenv("CI", "true")
    assert not dotenv_enabled()
    monkeypatch.setenv("AGENTVISION_DOTENV", "1")
    assert dotenv_enabled()
    monkeypatch.setenv("AGENTVISION_DOTENV", "0")
    monkeypatch.delenv("CI")
    assert not dotenv_enabled()


def test_doctor_installs_in_isolated_mode():
    from pathlib import Path

    import agentvision.adapters.doctor as d

    src = Path(d.__file__).read_text()
    assert '"-I", "-m", "playwright"' in src


def test_action_never_runs_python_m_from_checkout():
    from pathlib import Path

    import yaml

    spec = yaml.safe_load((Path(__file__).parents[2] / "action.yml").read_text())
    for step in spec["runs"]["steps"]:
        run = step.get("run", "")
        for line in run.splitlines():
            if "python" in line and " -m " in line:
                assert " -I -m " in line, line
        if "python" in run and " -m " in run:
            assert step.get("working-directory") == "${{ runner.temp }}"
    assert any(s.get("env", {}).get("AGENTVISION_DOTENV") == "0" for s in spec["runs"]["steps"])


# --- Red-team R3: grade what is PAINTED, not what the DOM claims ---------------------------

_DECOY = "<p>Readable decoy paragraph.</p><div style='width:80px;height:40px;background:#222'></div>"


@pytest.mark.parametrize("style", [
    "color:rgba(0,0,0,0.08)",
    "color:#000;-webkit-text-fill-color:#eee",
    "color:transparent",
])
def test_invisible_painted_text_fails(tmp_path, style):
    from agentvision.models.report import Severity

    issues = _kinds(f"{_DECOY}<p style='{style}'>Invisible promo copy text</p>", tmp_path)
    c = _of(issues, IssueKind.CONTRAST)
    assert c and any(i.severity == Severity.ERROR for i in c), [i.message for i in issues]


@pytest.mark.parametrize("wrap", [
    "<div style='filter:brightness(6)'><p style='color:#333'>Washed out copy text</p></div>",
    "<div style='opacity:0.99'><p style='color:#fff'>White on white copy text</p></div>",
])
def test_paint_effects_are_pixel_graded_to_error(tmp_path, wrap):
    from agentvision.models.report import Severity

    issues = _kinds(_DECOY + wrap, tmp_path)
    c = _of(issues, IssueKind.CONTRAST)
    assert c and any(i.severity == Severity.ERROR for i in c), [i.message for i in issues]


@pytest.mark.parametrize("hidden", [
    "<p style='position:absolute;left:-9999px'>Subscribe now</p>",
    "<p style='color:transparent'>Subscribe now</p>",
    "<div style='height:2px;overflow:hidden'><p style='margin:0'>Subscribe now</p></div>",
])
def test_hidden_text_cannot_satisfy_quoted_claim(tmp_path, hidden):
    from agentvision import check
    from agentvision.models.intent import Brief
    from agentvision.models.report import Verdict

    f = tmp_path / "p.html"
    f.write_text(WRAP.format(_DECOY + hidden))
    brief = Brief.from_inputs(expect=['must: the page shows "Subscribe now"'])
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), brief=brief))
    assert rep.verdict == Verdict.FAIL
    assert rep.conformance and rep.conformance.violated


def test_watch_vision_failure_is_an_error(tmp_path):
    from PIL import Image

    from agentvision import watch
    from agentvision.models.report import Verdict

    frames = [Image.new("RGB", (64, 64), (i * 40, 0, 0)) for i in range(4)]
    gif = tmp_path / "a.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=100, loop=0)
    s = load_settings(ephemeral=True, ollama_base_url="http://127.0.0.1:1/v1",
                      allow_local_files=True)
    rep = asyncio.run(watch(str(gif), settings=s, backend="ollama"))
    assert rep.verdict == Verdict.FAIL
    assert any("vision pass over the sampled frames failed" in i.message for i in rep.issues)


# --- Red-team R4: opacity/effects across the whole chain, strict claim visibility, and no
# --- false FAILs on ordinary filtered cards / footers -------------------------------------

@pytest.mark.parametrize("html", [
    "<p style='opacity:0.1;color:#000'>Please read the cancellation terms</p>",
    "<div style='background:#fff'><div style='opacity:.1'><p>Please read the terms</p></div></div>",
    "<div style='filter:opacity(0.1)'><div style='background:#fff'><p style='color:#000'>"
    "Please read the cancellation terms</p></div></div>",
    "<div style='opacity:0.12'><div style='background:#fff'><p>Please read the terms</p></div></div>",
])
def test_opacity_and_effects_anywhere_on_chain_fail(tmp_path, html):
    from agentvision.models.report import Severity

    issues = _kinds(_DECOY + html, tmp_path)
    c = _of(issues, IssueKind.CONTRAST)
    assert c and any(i.severity == Severity.ERROR for i in c), [i.message for i in issues]


@pytest.mark.parametrize("hidden", [
    "<div style='opacity:0'><div style='background:#fff'><p>Subscribe now</p></div></div>",
    "<p style='clip-path:inset(50%)'>Subscribe now</p>",
    "<p style='-webkit-mask-image:linear-gradient(transparent,transparent);"
    "mask-image:linear-gradient(transparent,transparent)'>Subscribe now</p>",
    "<p style='position:absolute;clip:rect(0 0 0 0)'>Subscribe now</p>",
    "<div style='content-visibility:hidden;height:40px'><p>Subscribe now</p></div>",
    "<p style='font-size:2px'>Subscribe now</p>",
    "<p style='margin:0'>Subscribe now</p><div style='position:relative;margin-top:-30px;"
    "height:40px;background:#fff'></div>",
])
def test_hidden_text_never_satisfies_claim_r4(tmp_path, hidden):
    from agentvision import check
    from agentvision.models.intent import Brief

    f = tmp_path / "p.html"
    f.write_text(WRAP.format(_DECOY + hidden))
    brief = Brief.from_inputs(expect=['must: the page shows "Subscribe now"'])
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), brief=brief))
    assert rep.conformance and rep.conformance.violated, rep.summary


@pytest.mark.parametrize("html", [
    # filtered wrapper with a footer below the fold
    "<main style='filter:drop-shadow(0 2px 4px rgba(0,0,0,.2))'><h1>Story</h1>"
    "<div style='height:1400px'></div><footer><p>Copyright footer text</p></footer></main>",
    # backdrop-filter card below the fold
    "<h1>Front page</h1><div style='height:1400px'></div><div style='backdrop-filter:blur(4px);"
    "background:rgba(255,255,255,.9)'><p>Card copy below the fold</p></div>",
    # house-style muted grey (#6b6862, AA-passing) at small size inside a drop-shadow card
    "<div style='filter:drop-shadow(0 1px 2px rgba(0,0,0,.15));background:#fff;padding:12px'>"
    "<p style='color:#6b6862;font-size:11px'>Published 22 October, updated 09:40</p></div>",
    "<div style='filter:drop-shadow(0 1px 2px rgba(0,0,0,.15));background:#fff;padding:12px'>"
    "<p style='color:#666;font-size:10px'>Small caption copy under a photo</p></div>",
    # carousel: second slide clipped away on purpose, both slides under a filter
    "<h1>Picks</h1><div style='overflow:hidden;width:600px'><div style='display:flex;"
    "width:3000px'><p style='width:600px;flex:none;filter:drop-shadow(0 0 1px #0003);"
    "color:#111'>Slide one text</p><p style='width:600px;flex:none;filter:drop-shadow(0 0 1px"
    " #0003);color:#111'>Slide two text</p></div></div>",
])
def test_filtered_clean_pages_do_not_fail(tmp_path, html):
    from agentvision import check
    from agentvision.models.report import Verdict

    f = tmp_path / "p.html"
    f.write_text(WRAP.format(html))
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), use_ocr=False))
    assert rep.verdict != Verdict.FAIL, [i.message for i in rep.issues]


def test_drop_shadow_card_small_grey_text_is_quiet(tmp_path):
    # R4 regression: anti-aliasing made AA-passing grey text under a drop-shadow warn/fail.
    issues = _kinds("<div style='filter:drop-shadow(0 2px 4px rgba(0,0,0,.2));background:#fff;"
                    "padding:16px;width:300px'><h3 style='margin:0;color:#111'>Card title</h3>"
                    "<p style='color:#444;font-size:13px'>Card description goes here</p>"
                    "<small style='color:#555;font-size:11px'>2 min read</small></div>", tmp_path)
    assert not _of(issues, IssueKind.CONTRAST), [i.message for i in issues]


# --- Red-team R5: glyph-box grading, transform-aware visibility, pixel-verified claims,
# --- WCAG-exempt disabled controls ----------------------------------------------------------

@pytest.mark.parametrize("html", [
    # element box far wider / taller than the capture: the glyphs are still in frame
    "<div style='overflow:hidden'><div style='width:2000px;opacity:.1'>Please read the "
    "cancellation terms</div></div>",
    "<section style='min-height:110vh;opacity:.06'>Please read the cancellation terms</section>",
    # scale() on an overflow:hidden ancestor must not deflate visibility and skip grading
    "<div style='overflow:hidden;width:300px;transform:scale(2);transform-origin:0 0'>"
    "<p style='opacity:.1;white-space:nowrap;margin:0'>Please read the terms</p></div>",
    # overflow:clip paints into overflow-clip-margin
    "<div style='overflow:clip;overflow-clip-margin:400px;height:20px;width:20px'>"
    "<p style='opacity:.1;white-space:nowrap;margin:0'>Please read the terms</p></div>",
])
def test_destroyed_paint_graded_on_glyphs(tmp_path, html):
    from agentvision.models.report import Severity

    issues = _kinds(_DECOY + html, tmp_path)
    c = _of(issues, IssueKind.CONTRAST)
    assert c and any(i.severity == Severity.ERROR for i in c), [i.message for i in issues]


@pytest.mark.parametrize("hidden", [
    "<style>.x{position:relative}.x::after{content:'';position:absolute;inset:0;"
    "background:#fff}</style><p class=x>Subscribe now</p>",
    "<p style='position:relative'>Subscribe now<span style='position:absolute;inset:0;"
    "background:#fff'></span></p>",
    "<p style='transform:scaleX(0.02);transform-origin:0 0'>Subscribe now</p>",
])
def test_covered_or_squashed_text_never_satisfies_claim(tmp_path, hidden):
    from agentvision import check
    from agentvision.models.intent import Brief

    f = tmp_path / "p.html"
    f.write_text(WRAP.format(_DECOY + hidden))
    brief = Brief.from_inputs(expect=['must: the page shows "Subscribe now"'])
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), brief=brief))
    assert rep.conformance and rep.conformance.violated, rep.summary


def test_visible_quoted_text_still_satisfies_claim(tmp_path):
    from agentvision import check
    from agentvision.models.intent import Brief

    f = tmp_path / "p.html"
    f.write_text(WRAP.format(_DECOY + "<p style='color:#111'>Subscribe now</p>"))
    brief = Brief.from_inputs(expect=['must: the page shows "Subscribe now"'])
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), brief=brief))
    assert rep.conformance and not rep.conformance.violated, rep.summary


@pytest.mark.parametrize("html", [
    "<button disabled style='opacity:.5;background:#0066cc;color:#fff;border:0;padding:8px'>"
    "Load more stories</button>",
    "<fieldset disabled style='border:0'><button style='color:#ccc;background:#fff'>"
    "Submit comment</button></fieldset>",
])
def test_disabled_controls_are_wcag_exempt(tmp_path, html):
    assert not _of(_kinds(_DECOY + html, tmp_path), IssueKind.CONTRAST)


def test_aria_disabled_wrapper_exempts_nothing(tmp_path):
    issues = _kinds(f"<div aria-disabled='true'>{_DECOY}<p style='color:#eee'>Faint copy "
                    "text here</p></div>", tmp_path)
    assert _of(issues, IssueKind.CONTRAST)


def test_scaled_container_text_not_falsely_clipped(tmp_path):
    issues = _kinds("<div style='overflow:hidden;width:300px;transform:scale(1.5);"
                    "transform-origin:0 0'><p style='margin:0'>Short line</p></div>", tmp_path)
    assert not _of(issues, IssueKind.CLIPPED), [i.message for i in issues]


# --- Red-team R6: OCR-only claim truth, bounded inactive exemption, per-line pixel grading,
# --- no false "no ink" at the fold ---------------------------------------------------------

@pytest.mark.parametrize("cover", [
    "<p style='position:relative;color:#000;background:#fff'>Free shipping on all orders"
    "<span style='position:absolute;inset:0;background:#fff;color:#000'>Prices may vary by "
    "region today</span></p>",
    "<style>.c{position:relative}.c::after{content:'Prices may vary by region today';"
    "position:absolute;inset:0;background:#fff;color:#000}</style><p class=c>Free shipping on "
    "all orders</p>",
    "<p style='margin:0'>Free shipping on all orders</p><div style='position:relative;"
    "margin-top:-22px;background:#fff;pointer-events:none'>Prices may vary by region today</div>",
])
def test_cover_with_its_own_text_does_not_satisfy_claim(tmp_path, cover):
    from agentvision import check
    from agentvision.models.intent import Brief

    f = tmp_path / "p.html"
    f.write_text(WRAP.format(_DECOY + cover))
    brief = Brief.from_inputs(expect=['must: the page shows "Free shipping on all orders"'])
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), brief=brief))
    assert rep.conformance and rep.conformance.violated, rep.summary
    assert "exists in the page DOM" in rep.conformance.violated[0].evidence


_FAINT = ("<p style='color:#f2f2f2'>This is the faint article body text that nobody can "
          "read on a white page.</p>")


@pytest.mark.parametrize("wrap", [
    "<a href='#' aria-disabled='true' style='display:block;color:inherit'>{}</a>",
    "<article role='button' aria-disabled='true'>{}</article>",
    "<button disabled style='all:unset;display:block'>{}</button>",
])
def test_inactive_wrapper_cannot_exempt_body_copy(tmp_path, wrap):
    issues = _kinds(_DECOY + wrap.format(_FAINT), tmp_path)
    assert _of(issues, IssueKind.CONTRAST), "body copy escaped grading via a disabled wrapper"


@pytest.mark.parametrize("html", [
    "<p style='background-image:linear-gradient(#fff,#fff);color:#f0f0f0'>Faint words "
    "here and <b style='color:#111'>nobody</b> can read the rest</p>",
    "<p style='background-image:linear-gradient(#fff,#fff);color:#f0f0f0'>Faint top line"
    "<strong style='display:block;color:#111'>Dark middle</strong>Faint bottom line</p>",
    "<p style='background-image:linear-gradient(#fff,#fff);color:#f0f0f0;text-decoration:"
    "underline 2px #000'>Faint underlined copy text</p>",
])
def test_other_ink_cannot_stand_in_for_faint_text(tmp_path, html):
    from agentvision.models.report import Severity

    issues = _kinds(_DECOY + html, tmp_path)
    c = _of(issues, IssueKind.CONTRAST)
    assert c and any(i.severity == Severity.ERROR for i in c), [i.message for i in issues]


@pytest.mark.parametrize("top", [784, 786, 790])
def test_headline_sliced_at_the_fold_is_not_no_ink(tmp_path, top):
    from agentvision import check
    from agentvision.models.report import Verdict

    hero = (f"<div style='position:absolute;top:0;left:0;width:1280px;height:{top + 80}px;"
            "background:linear-gradient(#123,#234)'></div><h1 style='position:absolute;"
            f"top:{top}px;left:40px;margin:0;color:#fff;font-size:48px'>Election night live"
            "</h1><p style='position:relative;color:#fff'>Top story</p>")
    f = tmp_path / "p.html"
    f.write_text(WRAP.format(hero))
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), use_ocr=False))
    assert rep.verdict != Verdict.FAIL, [i.message for i in rep.issues]


def test_aria_disabled_is_not_an_exemption(tmp_path):
    # R7: aria-disabled can be asserted on anything, one line at a time, so only NATIVE
    # disabled form controls are WCAG-exempt.
    issues = _kinds(_DECOY + "<a href='#' aria-disabled='true' style='color:#e0e0e0'>Next page "
                    "of results</a>", tmp_path)
    assert _of(issues, IssueKind.CONTRAST)


def test_inactive_exemption_cannot_be_split_per_line(tmp_path):
    lines = "".join("<button disabled style='all:unset;display:block;color:#e0e0e0'>"
                    f"Sentence number {i} of the faint article body.</button>" for i in range(10))
    assert _of(_kinds(_DECOY + lines, tmp_path), IssueKind.CONTRAST)


@pytest.mark.parametrize("html", [
    "<svg width='400' height='60'><text x='10' y='40' font-size='24' fill='#e8e8e8'>"
    "Q1 revenue: $4.2M</text></svg>",
    "<svg width='400' height='60'><text x='10' y='40' font-size='24' fill='#000' "
    "fill-opacity='.05'>Q1 revenue: $4.2M</text></svg>",
    "<div style='background-image:linear-gradient(#0a0a0a,#0a0a0a);padding:12px'>"
    "<p style='color:#000;margin:0'>Dark text on a dark image</p></div>",
    "<div style='color:#fff;background-image:linear-gradient(#000 0,#000 300px,#fff 300px)'>"
    + "<br>".join(f"Line {i} of the long caption block" for i in range(30)) + "</div>",
])
def test_r7_contrast_bypasses_fail(tmp_path, html):
    from agentvision.models.report import Severity

    issues = _kinds(_DECOY + html, tmp_path)
    c = _of(issues, IssueKind.CONTRAST)
    assert c and any(i.severity == Severity.ERROR for i in c), [i.message for i in issues]


@pytest.mark.parametrize("cover", [
    "<div style='position:relative;background:rgba(255,255,255,0.99);height:40px;"
    "margin-top:-34px'></div>",
    "<div style='opacity:.97;background:#fff;height:40px;margin-top:-34px;position:relative'>"
    "</div>",
])
def test_near_opaque_cover_does_not_satisfy_claim(tmp_path, cover):
    from agentvision import check
    from agentvision.models.intent import Brief

    f = tmp_path / "p.html"
    f.write_text(WRAP.format(_DECOY + "<p style='color:#000;margin:0;font-size:20px'>"
                             "Subscribe today</p>" + cover))
    brief = Brief.from_inputs(expect=['must: the page shows "Subscribe today"'])
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), brief=brief))
    assert rep.conformance and rep.conformance.violated, rep.summary


def test_claim_matches_whole_words_only(tmp_path):
    from agentvision import check
    from agentvision.models.intent import Brief

    f = tmp_path / "p.html"
    f.write_text(WRAP.format("<p style='font-size:24px'>Unsubscribe today</p>"))
    brief = Brief.from_inputs(expect=['must: the page shows "Subscribe today"'])
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), brief=brief))
    assert rep.conformance and rep.conformance.violated


def test_halo_headline_over_photo_is_clean(tmp_path):
    from agentvision import check
    from agentvision.models.intent import Brief
    from agentvision.models.report import Verdict

    hero = ("<div style='background:linear-gradient(90deg,#eee,#333);padding:40px'>"
            "<h1 style='color:#fff;text-shadow:0 2px 6px rgba(0,0,0,.9);font-size:44px;"
            "margin:0'>Storm batters coast</h1><p style='color:#fff;text-shadow:0 1px 3px "
            "rgba(0,0,0,.9)'>By our weather desk</p></div>")
    f = tmp_path / "p.html"
    f.write_text(WRAP.format(hero))
    brief = Brief.from_inputs(expect=['must: the page shows "Storm batters coast"'])
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), brief=brief))
    assert rep.verdict != Verdict.FAIL, [i.message for i in rep.issues]


# --- Red-team R8: painted halos only, same-colour backdrops, line cap, opacity folding,
# --- tiny glyphs judged locally, bounded pixel pass ----------------------------------------

@pytest.mark.parametrize("html", [
    "<p style='color:#fcfcfc;text-shadow:#000 -9999px 0 0;font-size:20px'>Free shipping on "
    "all orders</p>",
    "<p style='color:#000;line-height:24px;background-image:repeating-linear-gradient(#000 0 "
    "19px,#fff 19px 24px)'>Black body copy on black stripes nobody can read</p>",
    "<p style='color:#000;opacity:.4'>Dimmed copy that reads as light grey</p>",
])
def test_r8_invisible_text_fails(tmp_path, html):
    from agentvision.models.report import Severity

    issues = _kinds(_DECOY + html, tmp_path)
    c = _of(issues, IssueKind.CONTRAST)
    assert c and any(i.severity == Severity.ERROR for i in c), [i.message for i in issues]


def test_far_shadow_does_not_satisfy_claim(tmp_path):
    from agentvision import check
    from agentvision.models.intent import Brief

    f = tmp_path / "p.html"
    f.write_text(WRAP.format(_DECOY + "<p style='color:#fcfcfc;text-shadow:#000 -9999px 0 0;"
                             "font-size:20px'>Free shipping on all orders</p>"))
    brief = Brief.from_inputs(expect=['must: the page shows "Free shipping on all orders"'])
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), brief=brief))
    assert rep.conformance and rep.conformance.violated


def test_text_past_many_rects_is_graded(tmp_path):
    from agentvision.models.report import Severity

    lead = "i<wbr>" * 300
    html = ("<p style='color:#000;background-image:linear-gradient(#fff 0 20px,#000 20px)'>"
            f"{lead}<br>The real sentence sits on black and cannot be read at all.</p>")
    issues = _kinds(_DECOY + html, tmp_path)
    errs = [i for i in issues if i.severity == Severity.ERROR]
    assert errs, [i.message for i in issues]


def test_tiny_light_glyphs_on_dark_are_not_no_ink(tmp_path):
    from agentvision import check
    from agentvision.models.report import Verdict

    page = ("<div style='background:linear-gradient(#111,#222);padding:20px'>"
            "<span style='color:#ddd;font-size:12px'>||</span> "
            "<span style='color:#ddd;font-size:12px'>--</span> "
            "<span style='color:#ddd;font-size:12px'>· ·</span>"
            "<p style='color:#eee'>Live coverage continues below</p></div>")
    f = tmp_path / "p.html"
    f.write_text(WRAP.format(page))
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), use_ocr=False))
    assert rep.verdict != Verdict.FAIL, [i.message for i in rep.issues]


def test_pixel_pass_is_bounded(tmp_path, monkeypatch):
    import time

    from agentvision.core.checks import contrast_pixel as cp
    from agentvision.models.report import Severity

    monkeypatch.setattr(cp, "_MAX_SAMPLES", 3)
    cards = "".join("<div style='background-image:linear-gradient(#fff,#eee);padding:4px'>"
                    f"<p style='margin:0'>Card {i} headline text</p></div>" for i in range(20))
    t0 = time.monotonic()
    issues = _kinds(cards, tmp_path)
    assert time.monotonic() - t0 < 60
    assert any(i.severity == Severity.ERROR and "hit their limit" in i.message for i in issues)


def test_media_nav_words_are_not_typos():
    from agentvision.core.checks.spelling import check_spelling_from_ocr
    from agentvision.models.geometry import BBox
    from agentvision.ocr.base import OcrResult, OcrWord

    words = ["Tech", "Podcasts", "Newsletter", "Livestream"]
    ocr = OcrResult(text=" ".join(words), words=[
        OcrWord(text=w, bbox=BBox(x=1, y=1, width=10, height=10), confidence=0.95)
        for w in words])
    assert check_spelling_from_ocr(ocr) == []


# --- Red-team R9: empty legible OCR violates, per-tile backdrop, glyph-hugging halos only,
# --- tiny glyphs judged inside their box, long pages and translucent cards don't false-fail --

@pytest.mark.parametrize("page", [
    "<div style='height:200px;background:linear-gradient(#123,#456)'></div>"
    "<p style='position:absolute;left:-9999px'>Subscribe now</p>",
    "<svg width='300' height='120'><rect width='300' height='120' fill='#3a8a99'/></svg>"
    "<span style='opacity:0'>Subscribe now</span>",
])
def test_no_legible_text_violates_quoted_claim(tmp_path, page):
    from agentvision import check
    from agentvision.models.intent import Brief
    from agentvision.models.report import Verdict

    f = tmp_path / "p.html"
    f.write_text(WRAP.format(page))
    brief = Brief.from_inputs(expect=['must: the page shows "Subscribe now"'])
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), brief=brief))
    assert rep.verdict == Verdict.FAIL and rep.conformance.violated


@pytest.mark.parametrize("html", [
    "<p style='display:inline-block;color:#000;background:linear-gradient(to right,#000 0 35%,"
    "#fff 35%)'>Your account balance is overdue, please pay today</p>",
    "<div style='background-color:#fff;background-image:radial-gradient(#000 1px,transparent "
    "1.5px);background-size:6px 6px;padding:10px'><p style='color:#fff;text-shadow:rgba(0,0,0"
    ",.5) 0 0 9px;margin:0'>Free shipping on all orders</p></div>",
])
def test_r9_bypasses_fail(tmp_path, html):
    from agentvision.models.report import Severity

    issues = _kinds(_DECOY + html, tmp_path)
    c = _of(issues, IssueKind.CONTRAST)
    assert c and any(i.severity == Severity.ERROR for i in c), [i.message for i in issues]


def test_long_article_on_subtle_gradient_does_not_hit_budget(tmp_path):
    from agentvision import check
    from agentvision.models.report import Verdict

    paras = "".join(f"<p>Paragraph {i} of a long, clean article body.</p>" for i in range(450))
    f = tmp_path / "p.html"
    f.write_text(WRAP.format(f"<div style='background:linear-gradient(#fff,#fafafa)'>{paras}</div>"))
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), use_ocr=False))
    assert rep.verdict != Verdict.FAIL, [i.message for i in rep.issues][:5]


def test_translucent_card_over_dark_hero_is_clean(tmp_path):
    from agentvision import check
    from agentvision.models.report import Verdict

    f = tmp_path / "p.html"
    f.write_text(WRAP.format("<div style='background:#000;padding:30px'><div style='opacity:.5;"
                             "background:#fff;padding:16px'><p style='color:#000;margin:0'>Card "
                             "copy over the hero image</p></div></div>"))
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), use_ocr=False))
    assert rep.verdict != Verdict.FAIL, [i.message for i in rep.issues]


# --- Red-team R10: corroboration is bounded and fails closed --------------------------------

def test_claim_corroboration_budget_is_an_error(tmp_path, monkeypatch):
    import sys

    from agentvision import check
    from agentvision.models.intent import Brief
    from agentvision.models.report import Verdict

    az = sys.modules["agentvision.core.analyze"]
    monkeypatch.setattr(az, "_CORROB_MAX_PIXELS", 10)  # exhaust immediately
    f = tmp_path / "p.html"
    f.write_text(WRAP.format("<a style='background:#0b5394;color:#fff;padding:12px 22px'>"
                             "Subscribe</a>"))
    brief = Brief.from_inputs(expect=['must: a "Subscribe" button is visible'])
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), brief=brief))
    assert rep.verdict == Verdict.FAIL
    assert any("hit their time/size limit" in i.message for i in rep.issues)


def test_claim_crops_are_not_left_on_disk(tmp_path):
    from agentvision import check
    from agentvision.models.intent import Brief

    out = tmp_path / "out"
    f = tmp_path / "p.html"
    f.write_text(WRAP.format("<a style='background:#0b5394;color:#fff;padding:12px 22px'>"
                             "Subscribe</a>"))
    brief = Brief.from_inputs(expect=['must: a "Subscribe" button is visible'])
    asyncio.run(check(str(f), settings=load_settings(), brief=brief, out_dir=out))
    assert not list(out.rglob("claim_*.png"))


@pytest.mark.parametrize("url", ["https://[::1]@ollama.com/", "https://ollama.com＠evil/",
                                 "https://[bad/"])
def test_is_cloud_url_never_raises(url):
    from agentvision.backends.ollama_backend import is_cloud_url

    assert is_cloud_url(url) in (True, False)


# --- Red-team R11: halo needs inside contrast, overlays are overlap WARNINGs (cookie banner,
# --- paywall fade), spell-check is bounded and name-aware ------------------------------------

def test_halo_with_dark_bands_but_white_line_fails(tmp_path):
    from agentvision.models.report import Severity

    html = ("<div style='background:linear-gradient(#000 0 30%,#fff 30% 70%,#000 70%)'>"
            "<h1 style='color:#fff;text-shadow:rgba(0,0,0,.6) 0 0 1px;font-size:40px;margin:0;"
            "line-height:120px'>Breaking news tonight</h1></div>")
    issues = _kinds(_DECOY + html, tmp_path)
    c = _of(issues, IssueKind.CONTRAST)
    assert c and any(i.severity == Severity.ERROR for i in c), [i.message for i in issues]


@pytest.mark.parametrize("full_page", [False, True])
def test_cookie_banner_over_article_does_not_fail(tmp_path, full_page):
    from agentvision import check
    from agentvision.models.report import Verdict

    paras = "".join(f"<p>Paragraph {i} of the story continues with more reporting.</p>"
                    for i in range(40))
    banner = ("<div style='position:fixed;left:0;right:0;bottom:0;background:#fff;padding:16px;"
              "box-shadow:0 -2px 8px rgba(0,0,0,.2)'><p style='margin:0;color:#111'>We use "
              "cookies to improve your experience. <button>Accept</button></p></div>")
    f = tmp_path / "p.html"
    f.write_text("<!doctype html><html><body style='margin:0;padding:20px;font:16px Arial;"
                 f"background:linear-gradient(#fff,#fbfaf7)'>{paras}{banner}</body></html>")
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), use_ocr=False,
                            full_page=full_page))
    assert rep.verdict != Verdict.FAIL, [i.message for i in rep.issues if i.severity.value
                                         in ("error", "critical")]


def test_paywall_fade_does_not_fail(tmp_path):
    from agentvision import check
    from agentvision.models.report import Verdict

    page = ("<div style='background:linear-gradient(#fff,#fbfaf7)'><p>Opening paragraph of "
            "the story.</p><div class='pw' style='position:relative'><p>The last visible "
            "paragraph fades out under the paywall.</p><div style='position:absolute;inset:0;"
            "background:linear-gradient(rgba(255,255,255,0),#fff)'></div></div>"
            "<p><button>Subscribe to keep reading</button></p></div>")
    f = tmp_path / "p.html"
    f.write_text(WRAP.format(page))
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), use_ocr=False))
    assert rep.verdict != Verdict.FAIL, [i.message for i in rep.issues]


def test_spell_check_is_bounded_and_name_aware():
    import random
    import string
    import time

    from agentvision.core.checks.spelling import check_spelling_from_ocr
    from agentvision.models.geometry import BBox
    from agentvision.models.report import Severity
    from agentvision.ocr.base import OcrResult, OcrWord

    rnd = random.Random(7)
    junk = ["".join(rnd.choice(string.ascii_lowercase) for _ in range(30)) for _ in range(60)]
    words = ["Priya", "Goverment", "inbox", "Paywall"] + junk
    ocr = OcrResult(text=" ".join(words), words=[
        OcrWord(text=w, bbox=BBox(x=1, y=1, width=5, height=5), confidence=0.95) for w in words])
    t0 = time.monotonic()
    issues = check_spelling_from_ocr(ocr)
    assert time.monotonic() - t0 < 6
    by = {i.detail["word"]: i.severity for i in issues}
    assert by.get("Priya") == Severity.WARNING      # a byline name, not a typo
    assert "inbox" not in by and "Paywall" not in by
    assert len(issues) <= 50


# --- Red-team R12: only painted, on-top overlays skip a line; halo backdrop must meet AA;
# --- names are warnings --------------------------------------------------------------------

_FAINT_TEXT = "<p style='color:#e4e4e4;font-size:18px'>Faint promo copy nobody can read</p>"


@pytest.mark.parametrize("overlay", [
    "<div style='position:fixed;inset:0;background:#fff;z-index:-1'></div>",
    "<div style='position:fixed;inset:0;background:#000;clip-path:inset(50%);"
    "pointer-events:none'></div>",
    "<div style='position:fixed;inset:0;background:#fff;opacity:.06;pointer-events:none'></div>",
    "<div style='position:fixed;inset:0;background-image:linear-gradient(transparent,"
    "transparent)'></div>",
])
def test_fake_overlay_cannot_switch_grading_off(tmp_path, overlay):
    from agentvision.models.report import Severity

    page = ("<div style='background:linear-gradient(#fff,#fafafa);padding:10px'>"
            f"{_FAINT_TEXT}</div>{overlay}")
    issues = _kinds(_DECOY + page, tmp_path)
    c = _of(issues, IssueKind.CONTRAST)
    assert c and any(i.severity == Severity.ERROR for i in c), [i.message for i in issues]


def test_faint_halo_over_mid_grey_fails(tmp_path):
    from agentvision.models.report import Severity

    html = ("<div style='background:linear-gradient(#b0b0b0,#b0b0b0);padding:12px'>"
            "<p style='color:#fff;text-shadow:0 0 1px rgba(0,0,0,.5);margin:0'>Weather "
            "warning issued for the coast tonight</p></div>")
    issues = _kinds(_DECOY + html, tmp_path)
    c = _of(issues, IssueKind.CONTRAST)
    assert c and any(i.severity == Severity.ERROR for i in c), [i.message for i in issues]


def test_news_names_are_warnings_not_errors():
    from agentvision.core.checks.spelling import check_spelling_from_ocr
    from agentvision.models.geometry import BBox
    from agentvision.models.report import Severity
    from agentvision.ocr.base import OcrResult, OcrWord

    names = ["Starmer", "Farage", "Scholz", "Meloni", "Haaland", "Rashford", "Anfield",
             "Mensah", "Alcaraz"]
    ocr = OcrResult(text=" ".join(names), words=[
        OcrWord(text=w, bbox=BBox(x=1, y=1, width=5, height=5), confidence=0.95)
        for w in names])
    assert all(i.severity != Severity.ERROR for i in check_spelling_from_ocr(ocr))


# --- Red-team R13: overlays must paint, covered defects never vanish, halos must surround
# --- glyphs, OCR word splits are not typos -------------------------------------------------

_WHITE_ON_PALE = ("<div style='background-image:linear-gradient(#f4f4f4,#f4f4f4);padding:8px'>"
                  "<p style='color:#fff;font-size:18px;margin:0'>Pale headline copy here</p>")


@pytest.mark.parametrize("ov", [
    "position:sticky;top:0;background:#fff;mix-blend-mode:multiply",
    "position:sticky;top:0;background:#fff;mix-blend-mode:darken",
    "position:sticky;top:0;background:#fff;filter:opacity(0)",
    "position:fixed;top:0;left:0;right:0;background:#fff;mix-blend-mode:multiply",
])
def test_non_painting_overlay_does_not_hide_defect(tmp_path, ov):
    from agentvision.models.report import Severity

    page = (_WHITE_ON_PALE + f"<div style='{ov};height:40px;margin-top:-32px'></div></div>")
    issues = _kinds(_DECOY + page, tmp_path)
    c = _of(issues, IssueKind.CONTRAST)
    assert c and any(i.severity == Severity.ERROR for i in c), [i.message for i in issues]


@pytest.mark.parametrize("stripe", ["#333 9px,#333 13px", "#333 8px,#333 12px"])
def test_backdrop_stripe_is_not_a_halo(tmp_path, stripe):
    from agentvision.models.report import Severity

    html = (f"<p style='color:#fff;font-size:16px;line-height:22px;margin:0;"
            f"text-shadow:rgba(0,0,0,.6) 0 0 1px;background-image:linear-gradient(#f4f4f4 0,"
            f"#f4f4f4 {stripe.split(',')[0].split()[1]},{stripe},#f4f4f4 "
            f"{stripe.split(',')[1].split()[1]})'>Weather warning for the coast tonight</p>")
    issues = _kinds(_DECOY + html, tmp_path)
    c = _of(issues, IssueKind.CONTRAST)
    assert c and any(i.severity == Severity.ERROR for i in c), [i.message for i in issues]


def test_ocr_word_split_is_not_a_typo():
    from agentvision.core.checks.spelling import check_spelling_from_ocr
    from agentvision.models.geometry import BBox
    from agentvision.models.report import Severity
    from agentvision.ocr.base import OcrResult, OcrWord

    # "A" + "greement": the missing piece is an adjacent OCR token -> a real split, skipped.
    ocr = OcrResult(text="A greement anounces governmen", words=[
        OcrWord(text="A", bbox=BBox(x=10, y=10, width=10, height=16), confidence=0.95),
        OcrWord(text="greement", bbox=BBox(x=22, y=10, width=80, height=16), confidence=0.95),
        OcrWord(text="anounces", bbox=BBox(x=110, y=10, width=80, height=16), confidence=0.95),
        OcrWord(text="governmen", bbox=BBox(x=200, y=10, width=90, height=16), confidence=0.95),
    ])
    line = BBox(x=0, y=6, width=400, height=24)
    issues = check_spelling_from_ocr(ocr, dom_words=(
        (frozenset({"agreement", "xxxanouncesxxx", "government"}), line, 16.0),))
    by = {i.detail["word"]: i.severity for i in issues}
    assert "greement" not in by                     # confirmed OCR split
    assert by.get("anounces") == Severity.ERROR     # a non-word can't launder a typo
    assert by.get("governmen") == Severity.WARNING  # unconfirmed split: warned, never hidden

    # A tiny decoy at a different size launders nothing.
    tiny = check_spelling_from_ocr(OcrResult(text="recieve", words=[
        OcrWord(text="recieve", bbox=BBox(x=10, y=10, width=70, height=16), confidence=0.95)]),
        dom_words=((frozenset({"recieves"}), line, 3.0),))
    assert tiny and tiny[0].severity == Severity.ERROR


# --- Red-team R14: thin strips are not covers, inline textures are not halos, hidden words
# --- can't launder typos ---------------------------------------------------------------------

def test_thin_fixed_strip_is_not_a_cover(tmp_path):
    from agentvision.models.report import Severity

    page = ("<div style='background-image:linear-gradient(#fff,#fafafa);padding:10px'>"
            "<p style='color:#e6e6e6;font-size:20px;line-height:30px;margin:0'>Faint copy that "
            "nobody can read at all</p></div><div style='position:fixed;left:0;right:0;"
            "top:89px;height:1.5px;background:#fff'></div>")
    issues = _kinds(_DECOY + page, tmp_path)
    c = _of(issues, IssueKind.CONTRAST)
    assert c and any(i.severity == Severity.ERROR for i in c), [i.message for i in issues]


def test_inline_texture_is_not_a_halo(tmp_path):
    from agentvision.models.report import Severity

    html = ("<p style='margin:0'><span style='color:#ececec;font-size:18px;background-image:"
            "radial-gradient(#555 1px,transparent 1.2px);background-size:6px 6px;text-shadow:"
            "0 0 9px rgba(0,0,0,.5)'>Unreadable dotted promo copy</span></p>")
    issues = _kinds(_DECOY + html, tmp_path)
    c = _of(issues, IssueKind.CONTRAST)
    assert c and any(i.severity == Severity.ERROR for i in c), [i.message for i in issues]


def test_hidden_word_cannot_launder_typo(tmp_path):
    from agentvision import check
    from agentvision.models.report import Verdict

    f = tmp_path / "p.html"
    f.write_text(WRAP.format("<p style='font-size:22px'>You will recieve the governmnet "
                             "letter soon.</p><span style='position:absolute;left:-9999px'>"
                             "recieved governmnets</span>"))
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True)))
    assert rep.verdict == Verdict.FAIL, [i.message for i in rep.issues]


# --- Red-team R16: covers need real paint (alpha-aware), spelling splits are per line,
# --- halos never grade failing text as a PASS ----------------------------------------------

def test_transparent_border_dot_is_not_a_cover(tmp_path):
    from agentvision.models.report import Severity

    page = ("<div style='background-image:linear-gradient(#e0e0e0,#e0e0e0);padding:10px'>"
            "<p style='color:rgba(0,0,0,.35);font-size:18px;margin:0'>Faint copy that "
            "nobody can read</p></div><div style='position:fixed;left:600px;top:600px;width:2px;"
            "height:2px;border:600px solid transparent;background:#e0e0e0;"
            "background-clip:padding-box'></div>")
    issues = _kinds(_DECOY + page, tmp_path)
    errs = [i for i in issues if i.severity == Severity.ERROR]
    assert errs, [i.message for i in issues]


def test_translucent_dark_cookie_bar_does_not_fail_byline(tmp_path):
    from agentvision import check
    from agentvision.models.report import Verdict

    page = ("<div style='background:linear-gradient(#f5f7fa,#e9eef3);height:760px;padding:20px'>"
            "<h1>Storm season arrives</h1><p style='position:absolute;top:740px;color:#2a3a4a'>"
            "By Jane Doe, Weather desk</p></div><div style='position:fixed;left:0;right:0;"
            "bottom:0;height:70px;background:rgba(0,0,0,.8);color:#fff;padding:12px'>We use "
            "cookies. <button>Accept</button></div>")
    f = tmp_path / "p.html"
    f.write_text(WRAP.format(page))
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), use_ocr=False))
    assert rep.verdict != Verdict.FAIL, [i.message for i in rep.issues]


def test_two_bars_do_not_make_a_passing_halo(tmp_path):
    from agentvision import check
    from agentvision.models.report import Verdict

    page = ("<div style='position:relative;background:#fff;padding:0'>"
            "<div style='position:absolute;left:0;right:0;top:0;height:7px;background:#000'></div>"
            "<div style='position:absolute;left:0;right:0;bottom:0;height:7px;background:#000'></div>"
            "<h2 style='position:relative;color:#eee;font-size:32px;line-height:40px;margin:0;"
            "text-shadow:0 0 1px rgba(0,0,0,.5)'>Breaking news headline</h2></div>")
    f = tmp_path / "p.html"
    f.write_text(WRAP.format(_DECOY + page))
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), use_ocr=False))
    assert rep.verdict != Verdict.PASS, [i.message for i in rep.issues]


# --- Red-team R17: a fragment the page itself contains is a real break; British spellings --

def test_real_word_break_is_not_an_ocr_split(tmp_path):
    from agentvision import check
    from agentvision.models.report import Verdict

    f = tmp_path / "p.html"
    f.write_text(WRAP.format("<p style='font-size:22px'>Sign the agreeme nt today, the "
                             "agreement is final.</p>"))
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True)))
    assert rep.verdict == Verdict.FAIL, [i.message for i in rep.issues]


def test_common_british_spellings_are_not_typos():
    from agentvision.core.checks.spelling import check_spelling_from_ocr
    from agentvision.models.geometry import BBox
    from agentvision.ocr.base import OcrResult, OcrWord

    words = ["neighbourhoods", "neighbourly", "savoury", "flavoursome", "behavioural",
             "favouritism", "jewellery", "cheque", "aluminium", "pyjamas", "manoeuvre",
             "sceptical", "draught", "aeroplane", "tyres", "storeys"]
    ocr = OcrResult(text=" ".join(words), words=[
        OcrWord(text=w, bbox=BBox(x=1, y=1, width=5, height=5), confidence=0.95) for w in words])
    assert check_spelling_from_ocr(ocr) == []


# --- Red-team R18: tiny / scaled text can't pass; spelling rules don't mask common typos ---

@pytest.mark.parametrize("style", ["font-size:6px", "font-size:16px;transform:scale(.25);"
                                   "transform-origin:0 0", "font-size:16px;zoom:.25"])
def test_tiny_text_is_an_error(tmp_path, style):
    from agentvision.models.report import Severity

    issues = _kinds(f"<p style='{style}'>The fine print says the offer ends tonight.</p>",
                    tmp_path)
    tiny = [i for i in issues if "too small to read" in i.message]
    assert tiny and tiny[0].severity == Severity.ERROR, [i.message for i in issues]


def test_normal_small_print_is_fine(tmp_path):
    issues = _kinds("<p style='font-size:12px'>Copyright 2026 The Daily Ledger. All rights "
                    "reserved.</p><span style='font-size:9px'>AD</span>", tmp_path)
    assert not [i for i in issues if "too small to read" in i.message]


# --- Red-team R19: painted font size can't be inflated; fragments, fields, disabled controls
# --- are size-checked; ruby annotations are not -------------------------------------------

_TINY = "The fine print says the offer ends tonight and fees apply."


@pytest.mark.parametrize("html", [
    f"<p style='font-size:7px;transform:rotate(1deg)'>{_TINY}</p>",
    f"<p style='font-size:7px;transform:skewY(2deg)'>{_TINY}</p>",
    "<style>@font-face{font-family:Tall;src:local('DejaVu Sans');ascent-override:300%}</style>"
    f"<p style='font-family:Tall;font-size:7px'>{_TINY}</p>",
    f"<p style='font-size:7px;writing-mode:vertical-rl;height:400px'>{_TINY}</p>",
    "<p style='font-size:7px'>" + "".join(f"<span>{_TINY[i:i+2]}</span>"
                                          for i in range(0, 40, 2)) + "</p>",
    f"<input style='font-size:6px;width:400px' value='{_TINY}'>",
    f"<button disabled style='font-size:6px'>{_TINY[:40]}</button>",
])
def test_tiny_text_tricks_still_error(tmp_path, html):
    from agentvision.models.report import Severity

    issues = _kinds(html, tmp_path)
    tiny = [i for i in issues if "too small to read" in i.message]
    assert tiny and any(i.severity == Severity.ERROR for i in tiny), [i.message for i in issues]


def test_ruby_annotations_are_not_tiny_text(tmp_path):
    from agentvision import check
    from agentvision.models.report import Verdict

    ruby = "".join("<ruby>北<rt>běi</rt>京<rt>jīng</rt></ruby>今天很冷。" for _ in range(6))
    f = tmp_path / "p.html"
    f.write_text(WRAP.format(f"<p style='font-size:16px'>{ruby}</p>"))
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), use_ocr=False))
    assert not [i for i in rep.issues if "too small to read" in i.message]
    assert rep.verdict != Verdict.FAIL


# --- Red-team R20: size measured as painted (individual transform props, 3D, SVG viewBox);
# --- ruby exemption bounded; vertical fragments pooled; footnote markers only warn --------

@pytest.mark.parametrize("html", [
    f"<p style='font-size:30px;transform:rotate(1deg);scale:.22;transform-origin:0 0'>{_TINY}</p>",
    f"<p style='font-size:30px;transform:perspective(100px) translateZ(-350px) rotate(1deg);"
    f"transform-origin:0 0'>{_TINY}</p>",
    f"<svg viewBox='0 0 2000 100' width='400'><text x='10' y='50' font-size='30' "
    f"transform='rotate(1)'>{_TINY}</text></svg>",
    f"<ruby>&#8203;<rt style='font-size:5px'>{_TINY}</rt></ruby>",
    "<p style='font-size:6px;writing-mode:vertical-rl;height:300px'>" +
    "".join(f"<span>{_TINY[i:i+2]}</span>" for i in range(0, 40, 2)) + "</p>",
])
def test_r20_tiny_text_tricks_error(tmp_path, html):
    from agentvision.models.report import Severity

    issues = _kinds(html, tmp_path)
    tiny = [i for i in issues if "too small to read" in i.message]
    assert tiny and any(i.severity == Severity.ERROR for i in tiny), [i.message for i in issues]


def test_footnote_marker_only_warns(tmp_path):
    from agentvision.models.report import Severity

    issues = _kinds("<p style='font-size:11px'>Figures are provisional<sup style='font-size:.6em'>"
                    "[3]</sup> and may change.</p>", tmp_path)
    tiny = [i for i in issues if "too small to read" in i.message]
    assert not [i for i in tiny if i.severity == Severity.ERROR], [i.message for i in tiny]


# --- Red-team R21: no DOM probe (canvas metrics), bounded letter sampling, wide glyphs,
# --- sup chunking, flex fragments, vertical pages, web words --------------------------------

_SMALL = "<p style='font-size:16px;scale:.3;transform-origin:0 0'>"


@pytest.mark.parametrize("html", [
    "<style>body > span[style*='99999']{font-size:10px !important}</style>" + _SMALL + _TINY + "</p>",
    _SMALL + "⸻" * 8 + " " + _TINY + "</p>",
    "<p style='font-size:12px'>" + " ".join(
        f"<sup style='vertical-align:baseline;font-size:5px'>{w[:4]}</sup>" for w in _TINY.split())
    + "</p>",
    "<p style='display:flex;flex-wrap:wrap;font-size:5px'>" +
    "".join(f"<span>{_TINY[i:i+2]}</span>" for i in range(0, 40, 2)) + "</p>",
])
def test_r21_tiny_text_tricks_error(tmp_path, html):
    from agentvision.models.report import Severity

    issues = _kinds(html, tmp_path)
    tiny = [i for i in issues if "too small to read" in i.message]
    assert tiny and any(i.severity == Severity.ERROR for i in tiny), [i.message for i in issues]


def test_extraction_does_not_mutate_the_page(tmp_path):
    from agentvision.models.report import Severity

    # A page that shrinks its text when it sees a DOM mutation during grading.
    html = ("<p id=t style='font-size:16px'>" + _TINY + "</p><script>new MutationObserver(()=>"
            "{document.getElementById('t').style.fontSize='5px'}).observe(document.body,"
            "{childList:true,subtree:true})</script>")
    issues = _kinds(html, tmp_path)
    assert not [i for i in issues if "too small" in i.message and i.severity == Severity.ERROR]


def test_zero_width_flood_is_bounded(tmp_path):
    import time

    t0 = time.monotonic()
    _kinds("<p>" + "​" * 300000 + "Hello world</p>", tmp_path)
    assert time.monotonic() - t0 < 40


def test_vertical_japanese_page_is_not_tiny(tmp_path):
    from agentvision import check
    from agentvision.models.report import Verdict

    body = "".join("<p>今日は晴れです。東京の天気は穏やかで、多くの人が公園を散歩しています。</p>"
                   for _ in range(4))
    f = tmp_path / "p.html"
    f.write_text("<!doctype html><html><body style='margin:0;padding:20px;font-size:16px;"
                 f"writing-mode:vertical-rl'>{body}</body></html>")
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True), use_ocr=False))
    assert not [i for i in rep.issues if "too small to read" in i.message]
    assert rep.verdict != Verdict.FAIL


def test_common_web_words_are_not_typos():
    from agentvision.core.checks.spelling import check_spelling_from_ocr
    from agentvision.models.geometry import BBox
    from agentvision.ocr.base import OcrResult, OcrWord

    words = ["intro", "outro", "admin", "emoji", "dropdown", "tooltip", "analytics",
             "workflow", "fintech", "ecommerce", "preorder", "popup", "navbar", "faq"]
    ocr = OcrResult(text=" ".join(words), words=[
        OcrWord(text=w, bbox=BBox(x=1, y=1, width=5, height=5), confidence=0.95) for w in words])
    assert check_spelling_from_ocr(ocr) == []


# --- Red-team R22: glyph ink, not font box metrics; individual rotate/scale props; digits ---

def test_size_adjusted_face_with_normal_boxes_is_tiny(tmp_path):
    from agentvision.models.report import Severity

    html = ("<style>@font-face{font-family:Tiny;src:local('DejaVu Sans');size-adjust:10%;"
            "ascent-override:900%;descent-override:250%}</style><p style='font-family:Tiny;"
            f"font-size:16px'>{_TINY}</p>")
    tiny = [i for i in _kinds(html, tmp_path) if "too small to read" in i.message]
    assert tiny and any(i.severity == Severity.ERROR for i in tiny)


def test_rotated_scaled_digits_are_tiny(tmp_path):
    from agentvision.models.report import Severity

    html = ("<p style='font-size:16px;scale:.35;rotate:90deg;width:220px'>"
            "+1 (555) 010-4477 $4.99</p>")
    tiny = [i for i in _kinds(html, tmp_path) if "too small to read" in i.message]
    assert tiny and any(i.severity == Severity.ERROR for i in tiny)


# --- Round 23: OCR misreads aren't page FAILs; URLs/handles/tech words; small caps ----------

def test_ocr_misread_not_in_page_text_only_warns():
    from agentvision.core.checks.spelling import check_spelling_from_ocr
    from agentvision.models.geometry import BBox
    from agentvision.models.report import Severity
    from agentvision.ocr.base import OcrResult, OcrWord

    ocr = OcrResult(text="resen recieve", words=[
        OcrWord(text=w, bbox=BBox(x=1, y=1, width=5, height=5), confidence=0.95)
        for w in ("resen", "recieve")])
    by = {i.detail["word"]: i.severity for i in
          check_spelling_from_ocr(ocr, page_vocab=frozenset({"reserved", "recieve"}))}
    assert by["resen"] == Severity.WARNING     # OCR misread of "reserved"
    assert by["recieve"] == Severity.ERROR     # a real typo is in the page text


def test_urls_handles_and_tech_words_are_not_typos(tmp_path):
    from agentvision import check
    from agentvision.models.report import Verdict

    f = tmp_path / "p.html"
    f.write_text(WRAP.format("<p style='font-size:18px'>Read the report at "
                             "https://ledger.example/reports/rail-2026 and follow @dailyledger. "
                             "Set the viewport, run it on localhost, then use kubectl.</p>"))
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True)))
    assert rep.verdict != Verdict.FAIL, [i.message for i in rep.issues]



# --- Round 24: page vocabulary uses full text, rejoins split words, includes form values ----

@pytest.mark.parametrize("body", [
    "<p style='font-size:18px'>Weather: the forecast calls for rain and wind tonight; residents "
    "should prepare and remain calm as crews work overnight to clear the debris and restore "
    "power, while officals monitor.</p>",
    "<p style='font-size:20px'>the council will rec&shy;ieve the report today.</p>",
    "<p style='font-size:20px'>the council will rec<span>ieve</span> the report today.</p>",
    "<p style='font-size:20px'><input type=submit style='font-size:20px' "
    "value='submit your adress'></p>",
])
def test_visible_typos_stay_errors(tmp_path, body):
    from agentvision import check
    from agentvision.models.report import Verdict

    f = tmp_path / "p.html"
    f.write_text(WRAP.format(body))
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True)))
    assert rep.verdict == Verdict.FAIL, [i.message for i in rep.issues]


# --- Round 25: bounded CDP calls; vocabulary from every visible text node -------------------

async def test_isolated_eval_never_waits_on_a_stuck_detach():
    import time

    from agentvision.renderers import playwright_renderer as pr

    class _CDP:
        async def send(self, method, params=None):
            if method == "Page.getFrameTree":
                return {"frameTree": {"frame": {"id": "F"}}}
            if method == "Page.createIsolatedWorld":
                return {"executionContextId": 1}
            return {"result": {"value": 42}}

        async def detach(self):
            await asyncio.Event().wait()   # never answers

    class _Ctx:
        async def new_cdp_session(self, page):
            return _CDP()

    class _Page:
        context = _Ctx()

    t0 = time.monotonic()
    assert await pr._evaluate_isolated(_Page(), "() => 42", timeout_s=5) == 42
    assert time.monotonic() - t0 < 1.0


@pytest.mark.parametrize("body", [
    "<p style='font-size:16px'>" + "Plain words fill this long paragraph. " * 140 +
    "The board will recieve final approval.</p>",
    "<p style='font-size:20px'><span>The new plan will rec</span><span>ieve final "
    "approval</span></p>",
    "<p style='font-size:20px'>The new plan will rec‎ieve final approval.</p>",
])
def test_visible_typos_stay_errors_r25(tmp_path, body):
    from agentvision import check
    from agentvision.models.report import Verdict

    f = tmp_path / "p.html"
    f.write_text(WRAP.format(body), encoding="utf-8")
    rep = asyncio.run(check(str(f), settings=load_settings(ephemeral=True, full_page=True)))
    assert rep.verdict == Verdict.FAIL, [i.message for i in rep.issues if i.kind.value == "typo"]
