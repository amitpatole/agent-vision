"""Temporal verification orchestration — `watch`: capture a sequence, judge it over time.

Deterministic media/pixel signals (the trustworthy half) + an optional time-aware vision
pass over the frames. Returns a normal :class:`Report` so it flows through the handoff and
any brain (e.g. Verel) exactly like a single-frame analysis.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from ..backends.base import AnalysisRequest
from ..backends.registry import select_backend
from ..config import Settings, load_settings
from ..models.geometry import Viewport
from ..models.intent import Brief
from ..models.report import (
    Confidence,
    Issue,
    IssueKind,
    IssueSource,
    Report,
    Severity,
    Verdict,
    verdict_from_issues,
)
from ..renderers import get_renderer
from ..renderers.base import Frame, RenderSpec
from ..sources import resolve_source
from ..workspace import Workspace
from .temporal import compute_temporal_checks, temporal_summary

_TEMPORAL_CAPABILITIES = [IssueKind.BLANK, IssueKind.OTHER, IssueKind.MISSING_ELEMENT]


def _frame_sheet(frames: list[Frame], out_dir: Path, *, max_edge: int) -> str:
    """Stitch frames into one labeled left-to-right contact sheet for the vision pass."""
    from PIL import Image, ImageDraw

    th = 360  # per-frame thumbnail height
    thumbs = []
    for f in frames:
        im = Image.open(f.image_path).convert("RGB")
        scale = th / im.height
        thumbs.append((f, im.resize((max(1, int(im.width * scale)), th))))
    gap, pad = 12, 24
    w = pad * 2 + sum(t.width for _, t in thumbs) + gap * (len(thumbs) - 1)
    sheet = Image.new("RGB", (w, th + pad * 2), "#0d1018")
    d = ImageDraw.Draw(sheet)
    x = pad
    for f, t in thumbs:
        sheet.paste(t, (x, pad))
        d.text((x + 4, 6), f"t={f.t_ms}ms", fill="#7fd3e6")
        x += t.width + gap
    p = out_dir / "frames_sheet.png"
    sheet.save(p)
    return str(p)


async def watch(
    source: str,
    *,
    settings: Settings | None = None,
    backend: str | None = None,
    frames: int | None = None,
    interval_ms: int | None = None,
    brief: Brief | None = None,
    instructions: str | None = None,
    use_vision: bool = True,
    source_type: str = "auto",
    out_dir: Path | None = None,
) -> Report:
    """Watch ``source`` over time and report temporal behavior (playback/loading/liveness)."""
    settings = settings or load_settings()
    # Clamp caller-supplied values so a single request can't hold a browser for a huge window.
    n = max(2, min(frames or settings.watch_frames, settings.watch_max_frames))
    interval = max(0, min(interval_ms or settings.watch_interval_ms, settings.watch_max_interval_ms))
    resolved = resolve_source(source, source_type, settings=settings)
    if out_dir is None:
        out_dir = Workspace(settings).tmp / uuid.uuid4().hex[:12]

    renderer = get_renderer(resolved.kind, settings)
    if not hasattr(renderer, "render_sequence"):
        # Static source (image/PDF): nothing temporal to capture — defer to single-frame analyze.
        from .analyze import analyze

        return await analyze(source, settings=settings, backend=backend, brief=brief,
                             instructions=instructions, source_type=source_type, out_dir=out_dir)

    spec = RenderSpec(
        source=source, source_type=resolved.kind,
        viewports=[Viewport(width=settings.default_viewport_width,
                            height=settings.default_viewport_height)],
        device_scale=settings.device_scale, settle_ms=settings.settle_ms,
    )
    frame_list = await renderer.render_sequence(spec, resolved, out_dir, frames=n, interval_ms=interval)
    if not frame_list:
        return Report(verdict=Verdict.FAIL, summary="Temporal capture produced no frames.",
                      backend="watch", capabilities=[])

    issues, signals = compute_temporal_checks(frame_list)

    backend_name = "watch"
    if use_vision:
        vision, _fallback = select_backend(settings, backend)
        if getattr(vision, "name", "local") != "local":
            sheet = _frame_sheet(frame_list, out_dir, max_edge=settings.vision_max_edge_px)
            t_instr = (
                f"These are {len(frame_list)} sequential frames captured over "
                f"{signals.get('window_ms', 0)}ms (labeled by time). Judge TEMPORAL behavior: "
                "is video/animation actually playing (content changes across frames)? did "
                "loading complete (frames stabilize)? is anything stalled, frozen, black, or "
                "flickering? Report concrete problems."
            )
            if instructions:
                t_instr = f"{instructions}\n{t_instr}"
            if brief and not brief.is_empty():
                t_instr += f"\nIntended behavior: {brief.text or '; '.join(c.text for c in brief.claims)}"
            req = AnalysisRequest(
                image_path=sheet, instructions=t_instr,
                extra_images=[f.image_path for f in frame_list][: settings.max_vision_tiles],
            )
            try:
                vrep = await vision.analyze(req)
                issues = issues + vrep.issues
                backend_name = f"watch+{vision.name}"
            except Exception:  # noqa: BLE001
                pass

    verdict = verdict_from_issues(issues)
    # A machine-readable temporal signal rides on a leading INFO issue's detail.
    issues.insert(0, Issue.make(
        IssueKind.OTHER, Severity.INFO, f"temporal: {temporal_summary(signals)}",
        source=IssueSource.CV, confidence=Confidence.HIGH, detail={"temporal": signals}))

    return Report(
        verdict=verdict, summary=f"Watched over {signals.get('window_ms', 0)}ms — "
        f"{temporal_summary(signals)}.",
        issues=issues, capabilities=_TEMPORAL_CAPABILITIES,  # type: ignore[arg-type]
        backend=backend_name, viewport=spec.viewports[0],
        device_scale=settings.device_scale, image_path=frame_list[-1].image_path,
    )
