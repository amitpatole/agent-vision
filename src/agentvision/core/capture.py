"""Multi-viewport capture + responsive contact sheet."""

from __future__ import annotations

import uuid
from pathlib import Path

from ..config import Settings, load_settings
from ..models.geometry import Viewport
from ..renderers.base import RenderResult
from ..workspace import Workspace
from .render import render

DEFAULT_BREAKPOINTS = [375, 768, 1280, 1920]


async def contact_sheet(
    source: str,
    *,
    settings: Settings | None = None,
    breakpoints: list[int] | None = None,
    source_type: str = "auto",
    out_path: str | Path | None = None,
    panel_width: int = 360,
) -> tuple[str, RenderResult]:
    """Render ``source`` at several widths and stitch a labeled side-by-side sheet."""
    from PIL import Image, ImageDraw

    settings = settings or load_settings()
    breakpoints = breakpoints or DEFAULT_BREAKPOINTS
    viewports = [Viewport(width=w, height=settings.default_viewport_height) for w in breakpoints]
    result = await render(source, settings=settings, source_type=source_type,
                          viewports=viewports, full_page=True)

    label_h = 28
    panels = []
    for img in result.images:
        with Image.open(img.path) as im:
            im = im.convert("RGB")
            scale = panel_width / im.width
            ph = max(1, int(im.height * scale))
            resized = im.resize((panel_width, ph))
        panels.append((img.viewport.width, resized))

    if not panels:
        raise ValueError("No panels rendered for contact sheet.")
    max_h = max(p.height for _, p in panels) + label_h
    total_w = panel_width * len(panels) + 10 * (len(panels) + 1)
    sheet = Image.new("RGB", (total_w, max_h + 10), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    x = 10
    for width, panel in panels:
        draw.text((x, 6), f"{width}px wide", fill=(20, 20, 20))
        sheet.paste(panel, (x, label_h))
        x += panel_width + 10

    if out_path is None:
        ws = Workspace(settings)
        out_path = ws.tmp / f"sheet_{uuid.uuid4().hex[:8]}.png"
    out_path = str(out_path)
    sheet.save(out_path, "PNG")
    return out_path, result
