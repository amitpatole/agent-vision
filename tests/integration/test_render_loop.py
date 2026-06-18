"""Integration tests — require Chromium. Skipped automatically if unavailable.

Assertions are on Report *fields* (issue kinds, verdict), never on pixels or SSIM exact
values, so they're stable across Chromium revisions.
"""

import pytest

pytest.importorskip("playwright")

from agentvision.adapters._demo_assets import BROKEN_HTML, FIXED_HTML  # noqa: E402
from agentvision.config import load_settings  # noqa: E402
from agentvision.core import check  # noqa: E402
from agentvision.core.loop import LoopSession  # noqa: E402
from agentvision.models.report import IssueKind, Verdict  # noqa: E402


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


async def test_broken_page_fails_with_expected_kinds():
    report = await check(BROKEN_HTML, settings=load_settings(full_page=True), source_type="html")
    assert report.verdict == Verdict.FAIL
    kinds = {i.kind for i in report.issues}
    assert IssueKind.OVERFLOW in kinds
    assert IssueKind.CONTRAST in kinds
    assert IssueKind.BROKEN_IMAGE in kinds
    # contrast issues from DOM are precise
    contrast = [i for i in report.issues if i.kind == IssueKind.CONTRAST]
    assert all(i.bbox_precise for i in contrast)


async def test_fixed_page_passes():
    report = await check(FIXED_HTML, settings=load_settings(full_page=True), source_type="html")
    assert report.verdict == Verdict.PASS
    assert report.issues == []


async def test_loop_progresses_then_stuck():
    settings = load_settings(vision_backend="local", full_page=True)
    session = LoopSession(BROKEN_HTML, settings=settings, backend="local", source_type="html")
    first = await session.iterate()
    assert first.verdict == Verdict.FAIL

    fixed = await session.iterate(FIXED_HTML)
    assert fixed.verdict == Verdict.PASS
    assert fixed.progressed
    assert fixed.diff is not None  # diff vs previous iteration

    # Stuck on an unchanged failing artifact
    s2 = LoopSession(BROKEN_HTML, settings=settings, backend="local", source_type="html")
    await s2.iterate()
    second = await s2.iterate()
    assert second.stuck
