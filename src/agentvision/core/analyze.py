"""Analysis orchestration: render -> grounded checks -> (OCR) -> vision backend -> Report.

Also exposes ``check`` (the classic, no-LLM path).
"""

from __future__ import annotations

from pathlib import Path

from ..backends.base import AnalysisRequest
from ..backends.registry import select_backend
from ..config import Settings, load_settings
from ..logging import get_logger
from ..models.geometry import Viewport
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
from ..renderers.base import RenderResult
from .checks import CLASSIC_CAPABILITIES, run_all_checks
from .render import render

log = get_logger("analyze")


async def _render_and_ground(
    source: str, settings: Settings, *, source_type: str, viewport: Viewport | None,
    full_page: bool | None, wait_for: str | None, use_ocr: bool, out_dir: Path | None,
) -> tuple[RenderResult, list[Issue], str | None]:
    vps = [viewport] if viewport else None
    render_result = await render(
        source, settings=settings, source_type=source_type, viewports=vps,
        full_page=full_page, wait_for=wait_for, out_dir=out_dir,
    )
    primary = render_result.primary
    image_path = primary.path if primary else None
    grounded = run_all_checks(render_result, image_path)

    ocr_text = None
    if use_ocr and image_path:
        try:
            from ..ocr import get_ocr_backend

            ocr = get_ocr_backend()
            if ocr.available():
                ocr_text = ocr.run(image_path).text or None
        except Exception as e:  # noqa: BLE001
            log.debug("OCR skipped: %s", e)
    return render_result, grounded, ocr_text


async def analyze(
    source: str,
    *,
    settings: Settings | None = None,
    backend: str | None = None,
    instructions: str | None = None,
    expected: str | None = None,
    use_ocr: bool = True,
    source_type: str = "auto",
    viewport: Viewport | None = None,
    full_page: bool | None = None,
    wait_for: str | None = None,
    out_dir: Path | None = None,
) -> Report:
    """Full visual analysis: structural grounding + vision-backend critique."""
    settings = settings or load_settings()
    render_result, grounded, ocr_text = await _render_and_ground(
        source, settings, source_type=source_type, viewport=viewport,
        full_page=full_page, wait_for=wait_for, use_ocr=use_ocr, out_dir=out_dir,
    )
    primary = render_result.primary
    if primary is None:
        return Report(verdict=Verdict.FAIL, summary="Render produced no image.",
                      backend="none", capabilities=[])

    vision, fallback_warning = select_backend(settings, backend)
    req = AnalysisRequest(
        image_path=primary.path, viewport=primary.viewport,
        device_scale=settings.device_scale, instructions=instructions,
        expected=expected, ocr_text=ocr_text, dom_hints=grounded,
    )
    report = await vision.analyze(req)

    if fallback_warning:
        report.issues.insert(0, Issue.make(
            IssueKind.OTHER, Severity.WARNING, fallback_warning,
            source=IssueSource.CV, confidence=Confidence.LOW,
        ))
        if report.verdict == Verdict.PASS:
            report.verdict = Verdict.WARN
    return report


async def check(
    source: str,
    *,
    settings: Settings | None = None,
    source_type: str = "auto",
    viewport: Viewport | None = None,
    full_page: bool | None = None,
    wait_for: str | None = None,
    use_ocr: bool = False,
    out_dir: Path | None = None,
) -> Report:
    """Classic checks only — no LLM, no API key, no egress."""
    settings = settings or load_settings()
    render_result, grounded, _ = await _render_and_ground(
        source, settings, source_type=source_type, viewport=viewport,
        full_page=full_page, wait_for=wait_for, use_ocr=use_ocr, out_dir=out_dir,
    )
    primary = render_result.primary
    return Report(
        verdict=verdict_from_issues(grounded),
        summary=(f"Structural checks found {len(grounded)} issue(s)." if grounded
                 else "Structural checks passed (no DOM/CV defects detected)."),
        issues=grounded,
        capabilities=CLASSIC_CAPABILITIES,  # type: ignore[arg-type]
        backend="checks",
        viewport=primary.viewport if primary else Viewport(),
        device_scale=settings.device_scale,
        image_path=primary.path if primary else None,
    )
