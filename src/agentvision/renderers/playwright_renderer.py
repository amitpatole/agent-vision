"""Async headless-Chromium renderer (Playwright).

Renders HTML/SVG/URL, captures a screenshot per viewport, and extracts trustworthy
signals: DOM geometry, computed-style WCAG contrast, broken images, and console/network/
4xx errors. All coordinates are normalized to IMAGE pixels (CSS px + scroll offset ×
device_scale). Every render is bounded by a hard timeout.
"""

from __future__ import annotations

import asyncio
import ipaddress
from pathlib import Path
from urllib.parse import urlparse

from ..config import Settings
from ..errors import MissingDependencyError, RenderError, RenderTimeout
from ..logging import get_logger
from ..models.geometry import BBox, Viewport
from ..sources import ResolvedSource
from ._extract_js import EXTRACT_JS
from .base import (
    ConsoleError,
    ContrastSample,
    ElementBox,
    FailedResponse,
    RenderedImage,
    RenderResult,
    RenderSpec,
)

log = get_logger("playwright")

_SVG_WRAPPER = (
    "<!doctype html><html><head><meta charset='utf-8'>"
    "<style>html,body{{margin:0;padding:0}}</style></head>"
    "<body>{svg}</body></html>"
)

# Freeze perpetual motion before capture so a continuously-animating page can be
# screenshotted (incl. full-page) instead of waiting forever for a "stable" frame.
# Split in two: CSS/media is always safe to freeze; neutering requestAnimationFrame is NOT
# safe for a <canvas> that BUILDS its scene inside rAF (it would capture an empty canvas),
# so the renderer only applies the rAF freeze when there is no canvas.
_FREEZE_CSS_JS = """() => {
  try {
    const s = document.createElement('style');
    s.textContent = '*,*::before,*::after{animation:none !important;' +
      'animation-play-state:paused !important;transition:none !important;' +
      'scroll-behavior:auto !important;caret-color:transparent !important}';
    document.documentElement.appendChild(s);
    document.querySelectorAll('video,audio').forEach(function(m){ try { m.pause(); } catch(e){} });
  } catch (e) {}
}"""

_FREEZE_RAF_JS = """() => {
  try { window.requestAnimationFrame = function(){ return 0; };
        window.cancelAnimationFrame = function(){}; } catch (e) {}
}"""

# Report sizable non-text visual elements present, so the analyzer can overrule a vision
# "missing" claim about a canvas/chart/image that demonstrably exists.
_VISUALS_JS = """() => {
  const out = new Set(); const min = 64;
  document.querySelectorAll('canvas,svg,img,video').forEach(function(el){
    const r = el.getBoundingClientRect();
    if (r.width >= min && r.height >= min) out.add(el.tagName.toLowerCase());
  });
  return Array.from(out);
}"""

# Headless flags. --no-sandbox is commonly required on bare/CI Linux without user
# namespaces; the SSRF/file:// guards below are our real safety boundary.
_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--hide-scrollbars",
    "--force-color-profile=srgb",
]


def _import_playwright():
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except ImportError as e:
        raise MissingDependencyError(
            "headless rendering", pip_extra="render",
            system="playwright install chromium  (+ system libs; see `agentvision doctor`)",
        ) from e
    return async_playwright


class PlaywrightRenderer:
    SUPPORTED = {"html", "svg", "url"}

    def __init__(self, settings: Settings):
        self.settings = settings

    def supports(self, kind: str) -> bool:
        return kind in self.SUPPORTED

    async def render(
        self, spec: RenderSpec, resolved: ResolvedSource, out_dir: Path
    ) -> RenderResult:
        try:
            return await asyncio.wait_for(
                self._render(spec, resolved, out_dir),
                timeout=self.settings.render_timeout_s,
            )
        except TimeoutError as e:
            raise RenderTimeout(
                f"Render exceeded {self.settings.render_timeout_s}s (hanging page?). "
                "For a live/polling page try --nav-wait load; for a continuously-animating "
                "(canvas/WebGL) page keep --freeze on or drop --full-page; raise the budget "
                "with --render-timeout."
            ) from e

    async def _render(
        self, spec: RenderSpec, resolved: ResolvedSource, out_dir: Path
    ) -> RenderResult:
        async_playwright = _import_playwright()
        out_dir.mkdir(parents=True, exist_ok=True)

        console_errors: list[ConsoleError] = []
        failed: list[FailedResponse] = []
        images: list[RenderedImage] = []
        dom_boxes: list[ElementBox] = []
        contrast: list[ContrastSample] = []
        broken: list[ElementBox] = []
        overflow_x = 0.0
        visual_tags: list[str] = []

        async with async_playwright() as pw:
            try:
                browser = await pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)
            except Exception as e:  # noqa: BLE001
                raise RenderError(
                    f"Could not launch Chromium: {e}\nRun `agentvision doctor` to diagnose "
                    "missing system libraries."
                ) from e

            try:
                for idx, vp in enumerate(spec.viewports):
                    page_result = await self._render_one(
                        browser, spec, resolved, vp, out_dir, idx
                    )
                    images.append(page_result["image"])
                    # DOM/CV signals only meaningful for the first (or each) viewport;
                    # we keep the first viewport's signals as canonical.
                    if idx == 0:
                        dom_boxes = page_result["dom_boxes"]
                        contrast = page_result["contrast"]
                        broken = page_result["broken"]
                        console_errors = page_result["console_errors"]
                        failed = page_result["failed"]
                        overflow_x = page_result["overflow_x"]
                        visual_tags = page_result["visual_tags"]
            finally:
                await browser.close()

        return RenderResult(
            images=images, dom_boxes=dom_boxes, contrast_samples=contrast,
            console_errors=console_errors, failed_responses=failed,
            broken_images=broken, overflow_x=overflow_x, visual_tags=visual_tags,
            source_type=resolved.kind,
        )

    async def _render_one(self, browser, spec, resolved, vp: Viewport, out_dir: Path, idx: int):
        dsf = spec.device_scale or 1.0
        context = await browser.new_context(
            viewport={"width": vp.width, "height": vp.height},
            device_scale_factor=dsf,
            reduced_motion="reduce" if spec.freeze else "no-preference",
        )
        await self._install_guards(context)
        page = await context.new_page()

        console_errors: list[ConsoleError] = []
        failed: list[FailedResponse] = []

        page.on("console", lambda m: console_errors.append(
            ConsoleError(text=m.text, kind="console")) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: console_errors.append(
            ConsoleError(text=str(e), kind="pageerror")))
        page.on("requestfailed", lambda r: failed.append(
            FailedResponse(url=r.url, reason=(r.failure or ""))))
        page.on("response", lambda r: failed.append(
            FailedResponse(url=r.url, status=r.status, reason="http-error"))
            if r.status >= 400 else None)

        wait = spec.wait_for or self.settings.nav_wait
        try:
            await self._navigate(page, resolved, wait)
        except Exception as e:  # noqa: BLE001
            await context.close()
            raise RenderError(f"Navigation failed: {e}") from e

        # A <canvas> scene often BUILDS inside the rAF loop, so we must let rAF run long
        # enough for it to draw before pausing it ("settle-then-freeze", not the reverse).
        has_canvas = False
        try:
            has_canvas = bool(await page.evaluate("() => !!document.querySelector('canvas')"))
        except Exception:  # noqa: BLE001
            pass

        # Settle: give client-rendered data (and canvas scenes) a beat to populate before we
        # judge the page (avoids false "blank/missing" verdicts on the shell-then-fill frame).
        settle = spec.settle_ms or 0
        if has_canvas and spec.freeze:
            settle = max(settle, self.settings.canvas_settle_ms)
        if settle > 0:
            try:
                await page.wait_for_timeout(settle)
            except Exception:  # noqa: BLE001
                pass
        # Freeze perpetual motion so capture (incl. full-page) can't hang on animation. CSS
        # is always safe; rAF is only frozen when there's no canvas (else we'd capture an
        # empty canvas). Canvas pages rely on animations="disabled" + the settle above.
        if spec.freeze:
            for js in (_FREEZE_CSS_JS, None if has_canvas else _FREEZE_RAF_JS):
                if js is None:
                    continue
                try:
                    await page.evaluate(js)
                except Exception:  # noqa: BLE001
                    pass

        # Extract signals at scroll-top so doc-space rects map cleanly to the image.
        await page.evaluate("() => window.scrollTo(0, 0)")
        try:
            data = await page.evaluate(EXTRACT_JS)
        except Exception as e:  # noqa: BLE001
            log.warning("DOM extraction failed: %s", e)
            data = {"domBoxes": [], "contrast": [], "broken": [], "overflowX": 0}

        img_path = out_dir / f"vp_{vp.label()}_{idx}.png"
        # animations="disabled" makes Playwright finish CSS animations/transitions and not
        # wait on them — combined with freeze, even WebGL/rAF pages capture deterministically.
        await page.screenshot(path=str(img_path), full_page=spec.full_page,
                              animations="disabled")
        from PIL import Image  # local import; pillow is a base dep

        with Image.open(img_path) as im:
            iw, ih = im.size

        try:
            visual_tags = await page.evaluate(_VISUALS_JS) or []
        except Exception:  # noqa: BLE001
            visual_tags = []

        dom_boxes = [self._to_box(b, dsf) for b in data.get("domBoxes", [])]
        broken = [self._to_box(b, dsf) for b in data.get("broken", [])]
        contrast = [self._to_contrast(c, dsf) for c in data.get("contrast", [])]
        # Stash overflow signal on the result via a synthetic dom box list is messy;
        # we attach it through the page result dict for the checks layer.
        result = {
            "image": RenderedImage(path=str(img_path), viewport=vp, width=iw, height=ih),
            "dom_boxes": dom_boxes, "contrast": contrast, "broken": broken,
            "console_errors": console_errors, "failed": _dedupe_failed(failed),
            "overflow_x": float(data.get("overflowX", 0) or 0) * dsf,
            "visual_tags": list(visual_tags),
        }
        await context.close()
        return result

    async def _navigate(self, page, resolved: ResolvedSource, wait: str):
        is_state = wait in ("load", "domcontentloaded", "networkidle")
        wait_state = wait if is_state else "load"
        # networkidle never fires on polling/websocket pages, so navigate to 'load' and then
        # wait for idle only BRIEFLY — never block the whole render on it.
        goto_state = "load" if wait_state == "networkidle" else wait_state
        if resolved.kind == "url":
            await page.goto(resolved.url, wait_until=goto_state)
        else:
            html = resolved.content or ""
            if resolved.kind == "svg":
                html = _SVG_WRAPPER.format(svg=html)
            await page.set_content(html, wait_until=goto_state)
        if wait_state == "networkidle":
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:  # noqa: BLE001
                pass  # bounded: a live/polling page simply never goes idle
        if not is_state:
            # treat as a selector to wait for (the client-rendered-content path)
            try:
                await page.wait_for_selector(wait, timeout=8000)
            except Exception:  # noqa: BLE001
                pass

    async def _install_guards(self, context):
        """Browser-level defense-in-depth: block file:// and private-network subrequests."""
        block_private = self.settings.block_private_networks
        allow_file = self.settings.allow_file_scheme

        async def route(route_obj):
            url = route_obj.request.url
            scheme = urlparse(url).scheme
            if scheme == "file" and not allow_file:
                await route_obj.abort()
                return
            if block_private and scheme in ("http", "https"):
                host = urlparse(url).hostname or ""
                try:
                    ip = ipaddress.ip_address(host)
                    if (ip.is_private or ip.is_loopback or ip.is_link_local
                            or ip.is_reserved):
                        await route_obj.abort()
                        return
                except ValueError:
                    pass  # hostname, not a literal IP; DNS-level SSRF handled at resolve time
            await route_obj.continue_()

        await context.route("**/*", route)

    @staticmethod
    def _to_box(b: dict, dsf: float) -> ElementBox:
        return ElementBox(
            tag=b.get("tag", ""),
            bbox=BBox(x=b["x"] * dsf, y=b["y"] * dsf, width=b["w"] * dsf, height=b["h"] * dsf),
            text=b.get("text", ""), selector=b.get("selector", ""),
        )

    @staticmethod
    def _to_contrast(c: dict, dsf: float) -> ContrastSample:
        return ContrastSample(
            bbox=BBox(x=c["x"] * dsf, y=c["y"] * dsf, width=c["w"] * dsf, height=c["h"] * dsf),
            ratio=c["ratio"], fg=c["fg"], bg=c["bg"], font_px=c["fontPx"],
            large_text=c["large"], passes_aa=c["aa"], passes_aaa=c["aaa"],
            confidence=c["confidence"], text=c.get("text", ""), selector=c.get("selector", ""),
        )


def _dedupe_failed(failed: list[FailedResponse]) -> list[FailedResponse]:
    seen = set()
    out = []
    for f in failed:
        key = (f.url, f.status)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out
