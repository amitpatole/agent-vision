"""Named baselines + visual regression.

Caveat (honest): Chromium screenshots are not bit-stable across environments. Regression
is most reliable when baseline and candidate are captured on the same machine/Chromium
revision with animations disabled and a fixed device_scale/viewport.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from ..config import Settings, load_settings
from ..errors import AgentVisionError
from ..models.diff import DiffResult
from ..pathsafe import confine, under
from ..workspace import Workspace
from .diff import compute_diff
from .render import render


def _baselines_dir(settings: Settings) -> Path:
    d = Path(settings.cache_dir) / "baselines"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _baseline_path(settings: Settings, name: str) -> Path:
    # Validate `name` as a single component and confine under the baselines dir: a name like
    # "../../etc/passwd" is rejected (traversal blocked), not silently rewritten.
    return under(_baselines_dir(settings), name, suffix=".png")


async def set_baseline(
    source: str, name: str, *, settings: Settings | None = None, source_type: str = "auto",
) -> str:
    settings = settings or load_settings()
    result = await render(source, settings=settings, source_type=source_type)
    if not result.primary:
        raise AgentVisionError("Render produced no image; cannot set baseline.")
    dest = _baseline_path(settings, name)
    _copy(result.primary.path, dest, settings=settings)
    return str(dest)


async def regress(
    source: str, name: str, *, settings: Settings | None = None, source_type: str = "auto",
    out_path: str | Path | None = None,
) -> DiffResult:
    settings = settings or load_settings()
    baseline = _baseline_path(settings, name)
    if not baseline.exists():
        raise AgentVisionError(
            f"No baseline named {name!r}. Create one with: agentvision baseline <source> --name {name}"
        )
    result = await render(source, settings=settings, source_type=source_type)
    if not result.primary:
        raise AgentVisionError("Render produced no image; cannot run regression.")
    if out_path is None:
        ws = Workspace(settings)
        out_path = ws.tmp / f"regress_{uuid.uuid4().hex[:8]}.png"
    return compute_diff(baseline, result.primary.path, out_path)


def _copy(src: str | Path, dest: Path, *, settings: Settings) -> None:
    import shutil

    # Confine the source under the workspace cache (where renders are written) before copying,
    # so a tainted src can't read an arbitrary host file. dest is already confined by
    # _baseline_path.
    safe_src = confine(settings.cache_dir, src)
    shutil.copyfile(safe_src, dest)
