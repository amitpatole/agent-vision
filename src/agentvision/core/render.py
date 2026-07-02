"""Rendering orchestration: source -> RenderResult."""

from __future__ import annotations

import uuid
from pathlib import Path

from ..config import Settings, load_settings
from ..logging import get_logger
from ..models.geometry import Viewport
from ..renderers import get_renderer
from ..renderers.base import RenderResult, RenderSpec
from ..sources import resolve_source
from ..workspace import Workspace

log = get_logger("render")


def _viewports(settings: Settings, viewports: list[Viewport] | None) -> list[Viewport]:
    if viewports:
        return viewports
    return [Viewport(width=settings.default_viewport_width,
                     height=settings.default_viewport_height)]


async def render(
    source: str,
    *,
    settings: Settings | None = None,
    source_type: str = "auto",
    viewports: list[Viewport] | None = None,
    full_page: bool | None = None,
    wait_for: str | None = None,
    device_scale: float | None = None,
    settle_ms: int | None = None,
    freeze: bool | None = None,
    out_dir: Path | None = None,
) -> RenderResult:
    """Render ``source`` and return image(s) plus trustworthy DOM/CV signals."""
    settings = settings or load_settings()
    resolved = resolve_source(source, source_type, settings=settings)
    # Authenticated renders carry live session cookies + real user data. Guarantee they never
    # persist to the shared on-disk cache: require ephemeral mode (the CLI forces --no-cache
    # when a session is supplied; a library caller must opt in). Fail loud rather than leak.
    _auth = settings.storage_state or settings.auth_header_env or settings.http_credentials_env
    if _auth and not settings.ephemeral:
        log.warning(
            "an auth credential is set but ephemeral mode is off — authenticated captures could "
            "persist to the cache. Wrap with ephemeral_cache(settings) (or pass --no-cache)."
        )
    interactions = list(settings.interactions[: settings.max_interactions])
    if len(settings.interactions) > settings.max_interactions:
        log.warning("interactions truncated to the first %d of %d (max_interactions).",
                    settings.max_interactions, len(settings.interactions))
    spec = RenderSpec(
        source=source,
        source_type=resolved.kind,
        viewports=_viewports(settings, viewports),
        full_page=settings.full_page if full_page is None else full_page,
        wait_for=wait_for,
        device_scale=settings.device_scale if device_scale is None else device_scale,
        settle_ms=settings.settle_ms if settle_ms is None else settle_ms,
        freeze=settings.freeze_animations if freeze is None else freeze,
        storage_state_path=str(settings.storage_state) if settings.storage_state else None,
        auth_header_env=settings.auth_header_env,
        http_credentials_env=settings.http_credentials_env,
        interactions=interactions,
        allow_mutations=settings.allow_mutations,
        step_timeout_ms=settings.interaction_step_timeout_ms,
    )
    if out_dir is None:
        ws = Workspace(settings)
        out_dir = ws.tmp / uuid.uuid4().hex[:12]
    renderer = get_renderer(resolved.kind, settings)
    return await renderer.render(spec, resolved, out_dir)
