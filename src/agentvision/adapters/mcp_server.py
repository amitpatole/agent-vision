"""MCP server — gives any MCP-capable host (Cursor, Claude, …) the visual loop.

Tools return JSON (Report/DiffResult) plus an artifact path always; image-returning tools
hand back a downscaled image content block. Loop sessions persist in-process so
``loop_iterate`` continues a ``start_loop`` session.
"""

from __future__ import annotations

import io

from ..config import load_settings
from ..errors import MissingDependencyError

try:
    from mcp.server.fastmcp import FastMCP, Image
except ImportError:  # pragma: no cover
    FastMCP = None  # type: ignore
    Image = None  # type: ignore

_MAX_EDGE = 1400  # cap returned images so base64 doesn't blow up stdio/token budgets
_sessions: dict = {}


def _downscaled_png(path: str) -> bytes:
    from PIL import Image as PILImage

    with PILImage.open(path) as im:
        im = im.convert("RGB")
        if max(im.size) > _MAX_EDGE:
            scale = _MAX_EDGE / max(im.size)
            im = im.resize((int(im.width * scale), int(im.height * scale)))
        buf = io.BytesIO()
        im.save(buf, "PNG")
    return buf.getvalue()


def build_server():
    if FastMCP is None:
        raise MissingDependencyError("MCP server", pip_extra="mcp")

    mcp = FastMCP("agentvision")

    @mcp.tool()
    async def analyze_artifact(source: str, backend: str | None = None,
                               instructions: str | None = None,
                               expected: str | None = None,
                               full_page: bool = True) -> dict:
        """Render an artifact and return a structured visual Report (verdict + issues)."""
        from ..core import analyze

        settings = load_settings()
        report = await analyze(source, settings=settings, backend=backend,
                               instructions=instructions, expected=expected, full_page=full_page)
        return report.model_dump(mode="json")

    @mcp.tool()
    async def check_artifact(source: str, full_page: bool = True) -> dict:
        """Classic DOM/CV checks only (no LLM, no key)."""
        from ..core import check

        report = await check(source, settings=load_settings(), full_page=full_page)
        return report.model_dump(mode="json")

    @mcp.tool()
    async def render_artifact(source: str, full_page: bool = True, viewport: str | None = None):
        """Render an artifact and return the screenshot as an image."""
        from ..core import render
        from ..models.geometry import Viewport

        vps = None
        if viewport:
            w, h = viewport.lower().split("x")
            vps = [Viewport(width=int(w), height=int(h))]
        result = await render(source, settings=load_settings(), viewports=vps, full_page=full_page)
        if not result.primary:
            return {"error": "no image rendered"}
        return Image(data=_downscaled_png(result.primary.path), format="png")

    @mcp.tool()
    async def contact_sheet(source: str, breakpoints: str = "375,768,1280,1920"):
        """Render a responsive contact sheet across breakpoints, returned as an image."""
        from ..core.capture import contact_sheet as cs

        bps = [int(x) for x in breakpoints.split(",") if x.strip()]
        path, _ = await cs(source, settings=load_settings(), breakpoints=bps)
        return Image(data=_downscaled_png(path), format="png")

    @mcp.tool()
    def visual_diff(baseline_image: str, candidate_image: str) -> dict:
        """Compare two image files (SSIM + regions + narrative)."""
        from ..core import compute_diff

        return compute_diff(baseline_image, candidate_image).model_dump(mode="json")

    @mcp.tool()
    def ocr_artifact(image_path: str) -> dict:
        """Extract text + word boxes from an image file via Tesseract."""
        from ..ocr import get_ocr_backend

        backend = get_ocr_backend()
        if not backend.available():
            return {"error": "tesseract not available"}
        return backend.run(image_path).model_dump(mode="json")

    @mcp.tool()
    async def start_loop(source: str, backend: str | None = None,
                         instructions: str | None = None) -> dict:
        """Start a visual feedback loop session; returns session_id + first iteration."""
        from ..core.loop import LoopSession

        session = LoopSession(source, settings=load_settings(), backend=backend,
                              instructions=instructions)
        _sessions[session.session_id] = session
        result = await session.iterate()
        return {"session_id": session.session_id, "iteration": result.model_dump(mode="json")}

    @mcp.tool()
    async def loop_iterate(session_id: str, source: str | None = None) -> dict:
        """Continue a loop session after the agent edits the source."""
        session = _sessions.get(session_id)
        if session is None:
            return {"error": f"unknown session_id {session_id!r}"}
        result = await session.iterate(source)
        return {"session_id": session_id, "iteration": result.model_dump(mode="json"),
                "stop_reason": session.stop_reason}

    @mcp.tool()
    async def manage_baseline(source: str, name: str, action: str = "compare") -> dict:
        """action='set' stores a baseline; action='compare' regresses against it."""
        from ..core import regress, set_baseline

        settings = load_settings()
        if action == "set":
            return {"baseline": await set_baseline(source, name, settings=settings)}
        return (await regress(source, name, settings=settings)).model_dump(mode="json")

    @mcp.tool()
    async def doctor() -> dict:
        """Report rendering + backend readiness."""
        from ..backends.registry import available_backends
        from .doctor import _check_chromium

        ok, msg = await _check_chromium()
        return {"chromium_ok": ok, "chromium": msg,
                "available_backends": available_backends(load_settings())}

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
