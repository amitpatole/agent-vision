"""Async headless-Chromium renderer (Playwright).

Renders HTML/SVG/URL, captures a screenshot per viewport, and extracts trustworthy
signals: DOM geometry, computed-style WCAG contrast, broken images, and console/network/
4xx errors. All coordinates are normalized to IMAGE pixels (CSS px + scroll offset ×
device_scale). Every render is bounded by a hard timeout.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlparse

from ..config import Settings
from ..errors import MissingDependencyError, RenderError, RenderTimeout
from ..logging import get_logger
from ..models.geometry import BBox, Viewport
from ..netguard import host_is_safe
from ..sources import ResolvedSource
from ._extract_js import EXTRACT_JS
from .base import (
    ConsoleError,
    ContrastSample,
    ElementBox,
    FailedResponse,
    Frame,
    MediaState,
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

# Report sizable non-text visual elements (with geometry) so the analyzer can overrule a
# vision "missing" claim about a canvas/chart/image that exists, and send the model a
# focused full-res CROP of each region for real visual judgment. Read at scroll-top, so
# getBoundingClientRect is already document-space.
_VISUALS_JS = """() => {
  const out = []; const min = 64;
  document.querySelectorAll('canvas,svg,img,video').forEach(function(el){
    const r = el.getBoundingClientRect();
    if (r.width >= min && r.height >= min)
      out.push({tag: el.tagName.toLowerCase(), x: r.left, y: r.top, w: r.width, h: r.height});
  });
  return out;
}"""

# Deterministic media state (the trustworthy streaming signal) read from each <video>/<audio>.
_MEDIA_JS = """() => {
  const sel = function(el){ return el.id ? '#'+el.id : el.tagName.toLowerCase(); };
  return Array.from(document.querySelectorAll('video,audio')).map(function(m){
    let bEnd = 0;
    try { if (m.buffered && m.buffered.length) bEnd = m.buffered.end(m.buffered.length-1); } catch(e){}
    const tracks = m.textTracks || []; let active = 0;
    for (let i=0;i<tracks.length;i++){ if (tracks[i].mode === 'showing') active++; }
    return { selector: sel(m), currentTime: m.currentTime||0,
             duration: (isFinite(m.duration) ? m.duration : 0) || 0,
             paused: !!m.paused, ended: !!m.ended, readyState: m.readyState||0,
             videoWidth: m.videoWidth||0, videoHeight: m.videoHeight||0,
             bufferedEnd: bEnd, captions: tracks.length, activeCaptions: active };
  });
}"""

# Headless flags. The OS sandbox is kept ON by default (it's the real wall against a renderer
# RCE in attacker HTML/JS); --no-sandbox is added ONLY when chromium_sandbox is explicitly
# disabled. The SSRF/file guards are defense-in-depth for page *logic*, not a substitute.
_LAUNCH_ARGS = [
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

    async def _launch(self, pw):
        """Launch Chromium with the OS sandbox ON by default; fail loudly if it can't and the
        sandbox wasn't explicitly disabled (never silently run unsandboxed)."""
        use_sandbox = self.settings.chromium_sandbox
        args = list(_LAUNCH_ARGS) + ([] if use_sandbox else ["--no-sandbox"])
        try:
            return await pw.chromium.launch(headless=True, chromium_sandbox=use_sandbox, args=args)
        except Exception as e:  # noqa: BLE001
            if use_sandbox:
                raise RenderError(
                    f"Chromium failed to launch with the OS sandbox enabled: {e}\n"
                    "This is common on bare/CI Linux without user namespaces. Prefer running in "
                    "a container with proper isolation or enabling user namespaces. As a last "
                    "resort set AGENTVISION_CHROMIUM_SANDBOX=false to disable the sandbox "
                    "(reduces isolation — only in a trusted environment). Run `agentvision "
                    "doctor` to diagnose missing system libraries."
                ) from e
            raise RenderError(
                f"Could not launch Chromium: {e}\nRun `agentvision doctor` to diagnose."
            ) from e

    def _clamp(self, vp: Viewport, dsf: float) -> tuple[int, int, float]:
        """Bound viewport + device_scale so an attacker can't request a giant buffer."""
        cap = self.settings.max_viewport_px
        w = max(1, min(int(vp.width), cap))
        h = max(1, min(int(vp.height), cap))
        scale = max(0.1, min(float(dsf or 1.0), self.settings.max_device_scale))
        return w, h, scale

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
        visual_elements: list[ElementBox] = []

        async with async_playwright() as pw:
            browser = await self._launch(pw)
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
                        visual_elements = page_result["visual_elements"]
            finally:
                await browser.close()

        return RenderResult(
            images=images, dom_boxes=dom_boxes, contrast_samples=contrast,
            console_errors=console_errors, failed_responses=failed,
            broken_images=broken, overflow_x=overflow_x, visual_tags=visual_tags,
            visual_elements=visual_elements, source_type=resolved.kind,
        )

    async def _render_one(self, browser, spec, resolved, vp: Viewport, out_dir: Path, idx: int):
        vw, vh, dsf = self._clamp(vp, spec.device_scale or 1.0)
        vp = Viewport(width=vw, height=vh)
        context = await browser.new_context(
            viewport={"width": vw, "height": vh},
            device_scale_factor=dsf,
            reduced_motion="reduce" if spec.freeze else "no-preference",
            accept_downloads=False,  # untrusted page can't trigger disk-filling downloads
        )
        await self._install_guards(context)
        page = await context.new_page()
        # Close any EXTRA page (window.open popup) — but never our own main page.
        context.on("page", lambda pg: asyncio.create_task(pg.close()) if pg is not page else None)

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
        shot_kwargs: dict = {"path": str(img_path), "animations": "disabled"}
        if spec.full_page:
            # An attacker controls page height, so a full-page capture is an unbounded buffer.
            # Cap it: if the document is too tall, clip to a bounded height instead of full_page.
            from ..imageguard import MAX_IMAGE_PIXELS

            try:
                doc_h = int(await page.evaluate(
                    "() => Math.max(document.documentElement.scrollHeight, document.body"
                    " ? document.body.scrollHeight : 0)"
                ))
            except Exception:  # noqa: BLE001
                doc_h = vw
            max_h = max(vh, int(MAX_IMAGE_PIXELS / max(1, vw) / (dsf * dsf)))
            if doc_h > max_h:
                shot_kwargs["clip"] = {"x": 0, "y": 0, "width": vw, "height": max_h}
            else:
                shot_kwargs["full_page"] = True
        await page.screenshot(**shot_kwargs)
        from PIL import Image  # local import; pillow is a base dep

        with Image.open(img_path) as im:
            iw, ih = im.size

        try:
            visuals = await page.evaluate(_VISUALS_JS) or []
        except Exception:  # noqa: BLE001
            visuals = []
        visual_elements = [
            ElementBox(tag=v.get("tag", ""),
                       bbox=BBox(x=v["x"] * dsf, y=v["y"] * dsf,
                                 width=v["w"] * dsf, height=v["h"] * dsf))
            for v in visuals
        ]
        visual_tags = sorted({e.tag for e in visual_elements})

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
            "visual_tags": list(visual_tags), "visual_elements": visual_elements,
        }
        await context.close()
        return result

    async def render_sequence(
        self, spec: RenderSpec, resolved: ResolvedSource, out_dir: Path,
        *, frames: int, interval_ms: int,
    ) -> list[Frame]:
        """Sample ``frames`` screenshots over time (no freeze) + per-frame media state.

        For temporal verification: deliberately keeps motion so playback/loading/transition
        can be judged across frames. Viewport-only (full-page stitch is too slow/inconsistent
        frame-to-frame).
        """
        window_s = frames * interval_ms / 1000.0
        try:
            return await asyncio.wait_for(
                self._render_sequence(spec, resolved, out_dir, frames, interval_ms),
                timeout=self.settings.render_timeout_s + window_s + 10,
            )
        except TimeoutError as e:
            raise RenderTimeout(
                f"Temporal capture exceeded {self.settings.render_timeout_s + window_s:.0f}s."
            ) from e

    async def _render_sequence(self, spec, resolved, out_dir, frames, interval_ms):
        async_playwright = _import_playwright()
        out_dir.mkdir(parents=True, exist_ok=True)
        from PIL import Image

        vp = spec.viewports[0]
        dsf = spec.device_scale or 1.0
        out: list[Frame] = []
        async with async_playwright() as pw:
            browser = await self._launch(pw)
            try:
                vw, vh, dsf = self._clamp(vp, dsf)
                context = await browser.new_context(
                    viewport={"width": vw, "height": vh}, device_scale_factor=dsf,
                    accept_downloads=False,
                )
                await self._install_guards(context)
                page = await context.new_page()
                context.on("page",
                           lambda pg: asyncio.create_task(pg.close()) if pg is not page else None)
                await self._navigate(page, resolved, spec.wait_for or self.settings.nav_wait)
                if spec.settle_ms and spec.settle_ms > 0:
                    await page.wait_for_timeout(spec.settle_ms)
                for i in range(frames):
                    try:
                        media_raw = await page.evaluate(_MEDIA_JS) or []
                    except Exception:  # noqa: BLE001
                        media_raw = []
                    img = out_dir / f"frame_{i}.png"
                    await page.screenshot(path=str(img), full_page=False)  # no freeze: keep motion
                    with Image.open(img) as im:
                        iw, ih = im.size
                    out.append(Frame(
                        index=i, t_ms=i * interval_ms, image_path=str(img), width=iw, height=ih,
                        media=[_to_media(m) for m in media_raw],
                    ))
                    if i < frames - 1:
                        await page.wait_for_timeout(interval_ms)
            finally:
                await browser.close()
        return out

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
            parsed = urlparse(url)
            scheme = parsed.scheme
            # In-page non-network schemes needed for set_content / inline rendering.
            if scheme in ("about", "data", "blob"):
                await route_obj.continue_()
                return
            if scheme == "file":
                # Decouple navigation from subresources: even with allow_file_scheme, only the
                # TOP-LEVEL document may be file:// — never an (untrusted) subresource, so a
                # rendered page can't exfiltrate local files via <img>/<iframe>/fetch/CSS url().
                top_nav = False
                if allow_file:
                    try:
                        top_nav = (route_obj.request.is_navigation_request()
                                   and route_obj.request.frame.parent_frame is None)
                    except Exception:  # noqa: BLE001
                        top_nav = False
                await (route_obj.continue_() if top_nav else route_obj.abort())
                return
            # Default-deny anything that isn't http(s) (gopher/ftp/ws/chrome/etc.).
            if scheme not in ("http", "https"):
                await route_obj.abort()
                return
            # Re-resolve the host AT FETCH TIME for every request (navigation, subresource,
            # redirect target) — this is what defeats DNS rebinding and hostnames that point
            # at internal/metadata addresses (the resolve-time check only saw a stale answer).
            if block_private and not await host_is_safe(parsed.hostname, parsed.port):
                await route_obj.abort()
                return
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


def _to_media(m: dict) -> MediaState:
    return MediaState(
        selector=m.get("selector", ""), current_time=float(m.get("currentTime", 0) or 0),
        duration=float(m.get("duration", 0) or 0), paused=bool(m.get("paused", True)),
        ended=bool(m.get("ended", False)), ready_state=int(m.get("readyState", 0) or 0),
        video_width=int(m.get("videoWidth", 0) or 0), video_height=int(m.get("videoHeight", 0) or 0),
        buffered_end=float(m.get("bufferedEnd", 0) or 0), captions=int(m.get("captions", 0) or 0),
        active_captions=int(m.get("activeCaptions", 0) or 0),
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
