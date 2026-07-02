"""Integration test for pixel-graded contrast over a non-solid background (require Chromium).

The motivating case: text over a varying backdrop (a gradient / canvas / map raster) where
computed-style contrast can't see the real background. The renderer emits such a sample
``confidence == "low"``; the pixel check must grade it from the rendered bitmap and emit a
`cv`-sourced verdict — never a confident DOM ratio.
"""

import pytest

pytest.importorskip("playwright")

from agentvision.config import load_settings  # noqa: E402
from agentvision.core import check  # noqa: E402
from agentvision.models.report import IssueKind, IssueSource  # noqa: E402


def _chromium_ok() -> bool:
    import asyncio

    async def _t():
        from playwright.async_api import async_playwright
        try:
            async with async_playwright() as pw:
                b = await pw.chromium.launch(
                    headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
                await b.close()
            return True
        except Exception:
            return False

    return asyncio.run(_t())


pytestmark = pytest.mark.skipif(not _chromium_ok(), reason="Chromium not launchable")

# White text over a LIGHT gradient — a background-image, so computed-style contrast is
# low-confidence, and the real pixels are unreadable (white on near-white).
_UNREADABLE = (
    "<html><body style='margin:0'>"
    "<div style='width:400px;height:120px;background:linear-gradient(90deg,#f2f2f2,#ffffff);"
    "color:#ffffff;font-size:20px;padding:20px'>Latency 42ms · Loss 0.3%</div>"
    "</body></html>"
)


async def test_unreadable_text_over_gradient_is_pixel_graded():
    report = await check(_UNREADABLE, settings=load_settings(full_page=True), source_type="html")
    contrast = [i for i in report.issues if i.kind == IssueKind.CONTRAST]
    assert contrast, "expected a contrast issue for white text on a near-white gradient"
    # The gradient sample must be graded from pixels (cv), not emitted as a DOM computed ratio.
    cv = [i for i in contrast if i.source == IssueSource.CV]
    assert cv, "low-confidence sample should be pixel-graded (source=cv)"
    assert any("worst-case" in i.message for i in cv)
    assert all(i.bbox_precise for i in cv)  # bbox comes from the DOM sample — precise
