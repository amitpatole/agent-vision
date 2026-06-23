#!/usr/bin/env python3
"""Render every brand/social_*.html card to a crisp brand/og-<name>.png (1280x640).

Runs in CI where Chromium is available (see .github/workflows/og.yml) — local
headless Chromium is unreliable in some sandboxes, so rendering lives on a runner.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

BRAND = Path(__file__).resolve().parent  # the repo's brand/ dir
CARDS = sorted(BRAND.glob("social_*.html"))


async def main() -> None:
    if not CARDS:
        print("no social_*.html cards found — nothing to render")
        return
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        for card in CARDS:
            out = BRAND / ("og-" + card.stem.replace("social_", "") + ".png")
            page = await browser.new_page(
                viewport={"width": 1280, "height": 640}, device_scale_factor=2
            )
            await page.goto(card.resolve().as_uri())
            await page.evaluate("async () => { await document.fonts.ready; }")
            await page.wait_for_timeout(400)  # let the webfont paint settle
            await page.screenshot(path=str(out))
            await page.close()
            print("rendered", out.name)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
