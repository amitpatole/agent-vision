"""Async headless-Chromium renderer (Playwright).

Renders HTML/SVG/URL, captures a screenshot per viewport, and extracts trustworthy
signals: DOM geometry, computed-style WCAG contrast, broken images, and console/network/
4xx errors. All coordinates are normalized to IMAGE pixels (CSS px + scroll offset ×
device_scale). Every render is bounded by a hard timeout.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from ..config import Settings
from ..errors import (
    AuthExpiredError,
    InteractionError,
    MissingDependencyError,
    RenderError,
    RenderTimeout,
)
from ..logging import get_logger, register_secret
from ..models.geometry import BBox, Viewport
from ..netguard import host_is_safe
from ..sources import ResolvedSource
from ._extract_js import EXTRACT_JS
from .base import (
    ClippedText,
    ConsoleError,
    ContrastSample,
    ElementBox,
    FailedResponse,
    Frame,
    InteractionStep,
    MediaState,
    RenderedImage,
    RenderResult,
    RenderSpec,
)

# URL fragments that signal a login/SSO wall — used only to detect an expired session when a
# storage_state was supplied (so we refuse to silently grade the login page). Kept specific to
# avoid false positives on app routes that merely contain "auth" (a visible password field is
# the stronger, primary signal — see _looks_like_login).
_LOGIN_URL_HINTS = ("/login", "/signin", "/sign-in", "/sso/", "/oauth/", "/session/new")

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin_of(url: str | None) -> str | None:
    """Normalised ``scheme://host:port`` origin (default ports filled in) or None. Used for our
    own same-origin comparison, so an explicit vs implicit default port can't cause a mismatch."""
    if not url:
        return None
    p = urlparse(url)
    if not p.scheme or not p.hostname:
        return None
    port = p.port or _DEFAULT_PORTS.get(p.scheme)
    return f"{p.scheme}://{p.hostname.lower()}:{port}"


def _web_origin(url: str | None) -> str | None:
    """Browser-style origin (``scheme://host[:non-default-port]``) for Playwright's
    ``http_credentials.origin`` matching, which omits default ports."""
    if not url:
        return None
    p = urlparse(url)
    if not p.scheme or not p.hostname:
        return None
    host = p.hostname.lower()
    port = p.port
    if port and port != _DEFAULT_PORTS.get(p.scheme):
        return f"{p.scheme}://{host}:{port}"
    return f"{p.scheme}://{host}"

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
_WS_ALL = re.compile(r".*")  # match every WebSocket URL for the SSRF route guard

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

    async def _launch(self, pw, proxy_port: int | None = None):
        """Launch Chromium with the OS sandbox ON by default; fail loudly if it can't and the
        sandbox wasn't explicitly disabled (never silently run unsandboxed). When ``proxy_port``
        is set, route ALL egress (incl. loopback) through the vetting proxy so Chromium never
        resolves hosts itself — closing the DNS-rebinding race."""
        use_sandbox = self.settings.chromium_sandbox
        args = list(_LAUNCH_ARGS) + ([] if use_sandbox else ["--no-sandbox"])
        if proxy_port:
            args += [f"--proxy-server=127.0.0.1:{proxy_port}", "--proxy-bypass-list=<-loopback>"]
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

    async def _start_proxy(self):
        """Start the vetting egress proxy unless SSRF protection is disabled (--allow-local)."""
        if not self.settings.block_private_networks:
            return None
        from ..proxy import VettingProxy

        p = VettingProxy(max_connections=self.settings.proxy_max_connections,
                         idle_timeout_s=self.settings.proxy_idle_timeout_s)
        await p.start()
        return p

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
        clipped: list[ClippedText] = []
        overflow_x = 0.0
        visual_tags: list[str] = []
        visual_elements: list[ElementBox] = []
        interaction_log: list[InteractionStep] = []

        proxy = await self._start_proxy()
        try:
            async with async_playwright() as pw:
                browser = await self._launch(pw, proxy.port if proxy else None)
                try:
                    for idx, vp in enumerate(spec.viewports):
                        page_result = await self._render_one(
                            browser, spec, resolved, vp, out_dir, idx
                        )
                        images.append(page_result["image"])
                        # DOM/CV signals are canonical from the first viewport.
                        if idx == 0:
                            dom_boxes = page_result["dom_boxes"]
                            contrast = page_result["contrast"]
                            broken = page_result["broken"]
                            clipped = page_result["clipped"]
                            console_errors = page_result["console_errors"]
                            failed = page_result["failed"]
                            overflow_x = page_result["overflow_x"]
                            visual_tags = page_result["visual_tags"]
                            visual_elements = page_result["visual_elements"]
                            interaction_log = page_result["interaction_log"]
                finally:
                    await browser.close()
        finally:
            if proxy:
                await proxy.stop()

        return RenderResult(
            images=images, dom_boxes=dom_boxes, contrast_samples=contrast,
            console_errors=console_errors, failed_responses=failed,
            broken_images=broken, clipped_text=clipped, overflow_x=overflow_x,
            visual_tags=visual_tags,
            visual_elements=visual_elements, interaction_log=interaction_log,
            source_type=resolved.kind,
        )

    async def _render_one(self, browser, spec, resolved, vp: Viewport, out_dir: Path, idx: int):
        vw, vh, dsf = self._clamp(vp, spec.device_scale or 1.0)
        vp = Viewport(width=vw, height=vh)
        context_kwargs: dict = {
            "viewport": {"width": vw, "height": vh},
            "device_scale_factor": dsf,
            "reduced_motion": "reduce" if spec.freeze else "no-preference",
            "accept_downloads": False,  # untrusted page can't trigger disk-filling downloads
        }
        state = self._load_storage_state(spec.storage_state_path)
        if state is not None:
            # In-memory dict form: AgentVision consumes the session read-only and never
            # re-serializes it, so no fresh credential file is written as a side effect.
            context_kwargs["storage_state"] = state
        http_credentials, auth_header, auth_origin = self._resolve_auth(spec, resolved)
        if http_credentials is not None:
            context_kwargs["http_credentials"] = http_credentials
        context = await browser.new_context(**context_kwargs)
        # Toggled ON only while interaction steps run: aborts non-GET requests so clicking
        # around a live authenticated app can't submit/delete/send by default.
        mutation_state = {"block_mutations": False, "blocked_count": 0}
        await self._install_guards(context, mutation_state,
                                   auth_header=auth_header, auth_origin=auth_origin)
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

        # A supplied session that lands on a login wall means it expired/invalid. Refuse to
        # silently grade the login page — raise a distinct signal (fail-closed).
        if spec.storage_state_path and await self._looks_like_login(page):
            url = page.url
            await context.close()
            raise AuthExpiredError(
                "storage_state was supplied but the page is a login wall (the session is "
                f"expired or invalid): {url}. Refresh the saved session and retry."
            )

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

        # Drive the page to the state worth grading (open a popup, hover a tooltip, click a
        # map heat-bin) BEFORE freeze/capture, so the revealed DOM is present for extraction
        # and appears in the screenshot. Read-only by default (non-GET requests blocked);
        # fail-closed (a bad step raises rather than grading the wrong state).
        interaction_log: list[InteractionStep] = []
        if spec.interactions:
            mutation_state["block_mutations"] = not spec.allow_mutations
            try:
                interaction_log = await self._run_interactions(page, spec, mutation_state)
            finally:
                mutation_state["block_mutations"] = False

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
            data = {"domBoxes": [], "contrast": [], "broken": [], "clipped": [], "overflowX": 0}

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
        clipped = [self._to_clip(c, dsf) for c in data.get("clipped", [])]
        # Stash overflow signal on the result via a synthetic dom box list is messy;
        # we attach it through the page result dict for the checks layer.
        result = {
            "image": RenderedImage(path=str(img_path), viewport=vp, width=iw, height=ih),
            "dom_boxes": dom_boxes, "contrast": contrast, "broken": broken,
            "clipped": clipped,
            "console_errors": console_errors, "failed": _dedupe_failed(failed),
            "overflow_x": float(data.get("overflowX", 0) or 0) * dsf,
            "visual_tags": list(visual_tags), "visual_elements": visual_elements,
            "interaction_log": interaction_log,
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
        proxy = await self._start_proxy()
        try:
            async with async_playwright() as pw:
                browser = await self._launch(pw, proxy.port if proxy else None)
                try:
                    vw, vh, dsf = self._clamp(vp, dsf)
                    context = await browser.new_context(
                        viewport={"width": vw, "height": vh}, device_scale_factor=dsf,
                        accept_downloads=False,
                    )
                    await self._install_guards(context)
                    page = await context.new_page()
                    context.on("page", lambda pg: asyncio.create_task(pg.close())
                               if pg is not page else None)
                    await self._navigate(page, resolved, spec.wait_for or self.settings.nav_wait)
                    if spec.settle_ms and spec.settle_ms > 0:
                        await page.wait_for_timeout(spec.settle_ms)
                    for i in range(frames):
                        try:
                            media_raw = await page.evaluate(_MEDIA_JS) or []
                        except Exception:  # noqa: BLE001
                            media_raw = []
                        img = out_dir / f"frame_{i}.png"
                        await page.screenshot(path=str(img), full_page=False)  # keep motion
                        with Image.open(img) as im:
                            iw, ih = im.size
                        out.append(Frame(
                            index=i, t_ms=i * interval_ms, image_path=str(img),
                            width=iw, height=ih, media=[_to_media(m) for m in media_raw],
                        ))
                        if i < frames - 1:
                            await page.wait_for_timeout(interval_ms)
                finally:
                    await browser.close()
        finally:
            if proxy:
                await proxy.stop()
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

    def _load_storage_state(self, path: str | None):
        """Load a Playwright storage_state JSON into memory for an authenticated context.

        Registers every cookie/localStorage value as a secret (so it can never appear in a log
        line) and logs only non-sensitive counts. Read-only: the state is never re-serialized.
        """
        if not path:
            return None
        p = Path(path)
        if not p.exists():
            raise RenderError(f"storage_state file not found: {path}")
        try:
            state = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError) as e:
            raise RenderError(f"storage_state is not valid JSON ({path}): {e}") from e
        if not isinstance(state, dict):
            raise RenderError(f"storage_state must be a JSON object: {path}")
        cookies = state.get("cookies") or []
        origins = state.get("origins") or []
        for c in cookies:
            if isinstance(c, dict) and c.get("value"):
                register_secret(str(c["value"]))
        for o in origins:
            for item in (o.get("localStorage") or []) if isinstance(o, dict) else []:
                if isinstance(item, dict) and item.get("value"):
                    register_secret(str(item["value"]))
        log.info("storage_state loaded: %d cookie(s), %d origin(s)", len(cookies), len(origins))
        return state

    def _resolve_auth(self, spec: RenderSpec, resolved: ResolvedSource):
        """Resolve origin-scoped auth from env vars (never inline). Returns
        ``(http_credentials_dict | None, auth_header | None, target_origin | None)``.

        Both secrets are read from the named env var, registered with the log scrubber, and
        never logged. Auth only applies to URL sources (there's no origin for inline HTML); the
        header is scoped to ``target_origin`` at the route layer so a Bearer token can't leak to
        a third-party subresource host.
        """
        header = creds = None
        origin = _origin_of(resolved.url) if resolved.kind == "url" else None
        if origin is None:
            if spec.auth_header_env or spec.http_credentials_env:
                log.warning("auth header/credentials ignored: they apply only to URL sources.")
            return None, None, None
        if spec.auth_header_env:
            val = os.environ.get(spec.auth_header_env)
            if not val:
                raise RenderError(
                    f"auth header env var '{spec.auth_header_env}' is not set.")
            register_secret(val)
            header = val
            log.info("auth header loaded from env; scoped to origin %s", origin)
        if spec.http_credentials_env:
            raw = os.environ.get(spec.http_credentials_env)
            if not raw or ":" not in raw:
                raise RenderError(
                    f"http credentials env var '{spec.http_credentials_env}' must be set to "
                    "'username:password'.")
            user, pw = raw.split(":", 1)
            register_secret(pw)
            # Playwright matches http_credentials.origin using a browser-style origin (default
            # ports omitted), so pass that form — else Basic auth would silently not be sent.
            creds = {"username": user, "password": pw,
                     "origin": _web_origin(resolved.url) or origin}
            log.info("http basic credentials loaded from env; scoped to origin %s", origin)
        return creds, header, origin

    async def _looks_like_login(self, page) -> bool:
        """Best-effort detection that a supplied session bounced to a login wall: a login-ish
        final URL, or a visible password field on the page."""
        url = (page.url or "").lower()
        if any(hint in url for hint in _LOGIN_URL_HINTS):
            return True
        try:
            return bool(await page.evaluate(
                "() => !!document.querySelector('input[type=password]')"))
        except Exception:  # noqa: BLE001
            return False

    async def _run_interactions(self, page, spec: RenderSpec, mutation_state: dict):
        """Execute the closed, ordered interaction vocabulary. Fail-closed: any step that
        errors raises InteractionError (the renderer never grades the pre-interaction state)."""
        cap = max(0, min(int(spec.step_timeout_ms), 30_000))  # hard ceiling per step
        out: list[InteractionStep] = []
        for i, step in enumerate(spec.interactions):
            before = mutation_state.get("blocked_count", 0)
            t0 = time.monotonic()
            try:
                detail = await self._do_step(page, step, cap)
            except InteractionError:
                raise
            except Exception as e:  # noqa: BLE001 — fail-closed on any Playwright error
                where = f" '{step.selector}'" if step.selector else ""
                raise InteractionError(
                    f"interaction step {i} ({step.type}{where}) failed: {e}"
                ) from e
            out.append(InteractionStep(
                index=i, type=step.type, selector=step.selector or "", ok=True, detail=detail,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                blocked_mutations=mutation_state.get("blocked_count", 0) - before,
            ))
        total_blocked = sum(s.blocked_mutations for s in out)
        if total_blocked:
            log.info("blocked %d non-GET request(s) during interactions (allow_mutations=%s)",
                     total_blocked, spec.allow_mutations)
        return out

    async def _do_step(self, page, step, cap_ms: int) -> str:
        """Map ONE interaction to exactly one Playwright call. No arbitrary code path exists."""
        t = step.type
        if t == "click":
            await page.click(step.selector, timeout=cap_ms)
            return step.selector
        if t == "hover":
            await page.hover(step.selector, timeout=cap_ms)
            return step.selector
        if t == "scroll_into_view":
            await page.locator(step.selector).scroll_into_view_if_needed(timeout=cap_ms)
            return step.selector
        if t == "wait_for":
            await page.locator(step.selector).wait_for(state="visible", timeout=cap_ms)
            return step.selector
        if t == "fill":
            await page.fill(step.selector, step.value or "", timeout=cap_ms)
            return f"{step.selector} = <literal>"
        if t == "fill_env":
            secret = os.environ.get(step.value or "")
            if secret is None:
                raise InteractionError(
                    f"fill_env: environment variable '{step.value}' is not set")
            register_secret(secret)
            await page.fill(step.selector, secret, timeout=cap_ms)
            return f"{step.selector} = <env>"  # never record the env var name or its value
        if t == "press":
            if step.selector:
                await page.press(step.selector, step.value, timeout=cap_ms)
            else:
                await page.keyboard.press(step.value)
            return f"press {step.value}"
        if t == "click_at":
            box = await page.locator(step.selector).bounding_box(timeout=cap_ms)
            if not box:
                raise InteractionError(
                    f"click_at: '{step.selector}' has no bounding box (not visible?)")
            cx = box["x"] + box["width"] * float(step.x)
            cy = box["y"] + box["height"] * float(step.y)
            await page.mouse.click(cx, cy)
            return f"{step.selector} @ ({cx:.0f},{cy:.0f})"
        if t == "wait_timeout":
            ms = max(0, min(int(step.ms or 0), cap_ms))
            await page.wait_for_timeout(ms)
            return f"{ms}ms"
        raise InteractionError(f"unknown interaction type: {t}")

    async def _install_guards(self, context, mutation_state: dict | None = None, *,
                              auth_header: str | None = None, auth_origin: str | None = None):
        """Browser-level defense-in-depth: block file:// and private-network subrequests, abort
        non-GET requests during interaction steps (read-only default), and — when an
        ``auth_header`` is supplied — inject it as ``Authorization`` **only on same-origin
        requests**, so a Bearer token can never leak to a third-party subresource host."""
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
            # Defense-in-depth in the browser (the vetting egress proxy is the primary control
            # and closes DNS rebinding): re-resolve the host at fetch time for every request
            # (navigation, subresource, redirect target) and abort internal/metadata targets.
            if block_private and not await host_is_safe(parsed.hostname, parsed.port):
                await route_obj.abort()
                return
            # Read-only guard: while interactions run, abort writes unless explicitly allowed.
            if mutation_state and mutation_state.get("block_mutations"):
                method = (route_obj.request.method or "GET").upper()
                if method not in ("GET", "HEAD", "OPTIONS"):
                    mutation_state["blocked_count"] = mutation_state.get("blocked_count", 0) + 1
                    await route_obj.abort()
                    return
            # Origin-scoped bearer/custom auth: attach the header ONLY to same-origin requests
            # so a token for the target app can't be exfiltrated to a third-party subresource.
            if auth_header and _origin_of(url) == auth_origin:
                headers = {**route_obj.request.headers, "authorization": auth_header}
                await route_obj.continue_(headers=headers)
                return
            await route_obj.continue_()

        await context.route("**/*", route)

        # WebSocket connections are NOT covered by context.route(), so a page could reach an
        # internal host via `new WebSocket("ws://10.0.0.5/")`. Intercept WS too: block internal
        # hosts (re-resolved), pass public ones through.
        if block_private:
            async def ws_route(ws):
                u = urlparse(ws.url)
                if await host_is_safe(u.hostname, u.port):
                    try:
                        ws.connect_to_server()
                    except Exception:  # noqa: BLE001
                        pass
                # else: do not connect — the internal WS handshake never happens (blocked)

            try:
                await context.route_web_socket(_WS_ALL, ws_route)
            except Exception:  # noqa: BLE001
                pass  # older Playwright without WS routing — context.route still covers http(s)

    @staticmethod
    def _to_box(b: dict, dsf: float) -> ElementBox:
        return ElementBox(
            tag=b.get("tag", ""), bbox=_img_bbox(b["x"], b["y"], b["w"], b["h"], dsf),
            text=b.get("text", ""), selector=b.get("selector", ""),
        )

    @staticmethod
    def _to_clip(c: dict, dsf: float) -> ClippedText:
        return ClippedText(
            bbox=_img_bbox(c["x"], c["y"], c["w"], c["h"], dsf),
            text=c.get("text", ""), selector=c.get("selector", ""), tag=c.get("tag", ""),
            kind=c.get("kind", "clipped"), overflow_px=float(c.get("overflow", 0) or 0) * dsf,
        )

    @staticmethod
    def _to_contrast(c: dict, dsf: float) -> ContrastSample:
        return ContrastSample(
            bbox=_img_bbox(c["x"], c["y"], c["w"], c["h"], dsf),
            ratio=c["ratio"], fg=c["fg"], bg=c["bg"], font_px=c["fontPx"],
            large_text=c["large"], passes_aa=c["aa"], passes_aaa=c["aaa"],
            confidence=c["confidence"], text=c.get("text", ""), selector=c.get("selector", ""),
        )


def _img_bbox(x: float, y: float, w: float, h: float, dsf: float) -> BBox:
    """Scale a doc-space rect to image px and clamp to the visible region. An element can sit
    partly off-screen (e.g. SVG text at negative x); the contract requires non-negative
    coordinates, so clip the off-screen left/top portion and keep the visible remainder."""
    x, y, w, h = x * dsf, y * dsf, w * dsf, h * dsf
    nx, ny = max(0.0, x), max(0.0, y)
    return BBox(x=nx, y=ny, width=max(1.0, w - (nx - x)), height=max(1.0, h - (ny - y)))


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
