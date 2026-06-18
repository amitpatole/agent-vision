"""AgentVision CLI (Typer). The primary face; every other adapter mirrors it.

All commands support ``--json`` for agent/CI consumption and exit non-zero on a FAIL
verdict.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer

from .. import __version__
from ..config import Settings, load_settings
from ..models.geometry import Viewport
from ..models.report import Report, Verdict

app = typer.Typer(
    add_completion=False,
    help="AgentVision — eyes for AI agents. Render, see, and self-correct visual output.",
    no_args_is_help=True,
)

_VERDICT_COLOR = {Verdict.PASS: typer.colors.GREEN, Verdict.WARN: typer.colors.YELLOW,
                  Verdict.FAIL: typer.colors.RED}
_SEV_COLOR = {"info": typer.colors.BLUE, "warning": typer.colors.YELLOW,
              "error": typer.colors.RED, "critical": typer.colors.BRIGHT_RED}


def _parse_viewport(s: str | None) -> Viewport | None:
    if not s:
        return None
    try:
        w, h = s.lower().split("x")
        return Viewport(width=int(w), height=int(h))
    except ValueError as e:
        raise typer.BadParameter("viewport must be WxH, e.g. 1280x800") from e


def _settings(backend: str | None = None, full_page: bool | None = None,
              viewport: str | None = None, device_scale: float | None = None,
              timeout: float | None = None) -> Settings:
    overrides: dict = {}
    if backend:
        overrides["vision_backend"] = backend
    if full_page is not None:
        overrides["full_page"] = full_page
    if device_scale is not None:
        overrides["device_scale"] = device_scale
    if timeout is not None:
        overrides["render_timeout_s"] = timeout
    vp = _parse_viewport(viewport)
    if vp:
        overrides["default_viewport_width"] = vp.width
        overrides["default_viewport_height"] = vp.height
    return load_settings(**overrides)


def _print_report(report: Report, as_json: bool) -> None:
    if as_json:
        typer.echo(report.model_dump_json(indent=2))
        return
    color = _VERDICT_COLOR.get(report.verdict, typer.colors.WHITE)
    typer.secho(f"\n  {report.verdict.value.upper()}", fg=color, bold=True, nl=False)
    typer.secho(f"  ({report.backend}{'/' + report.model if report.model else ''})",
                fg=typer.colors.BRIGHT_BLACK)
    typer.echo(f"  {report.summary}\n")
    if not report.issues:
        typer.secho("  No issues.\n", fg=typer.colors.GREEN)
    for i in report.issues:
        sev = _SEV_COLOR.get(i.severity.value, typer.colors.WHITE)
        loc = ""
        if i.bbox:
            mark = "" if i.bbox_precise else "~"
            loc = f" @{mark}({i.bbox.x:.0f},{i.bbox.y:.0f})"
        typer.secho(f"  • [{i.kind.value}]", fg=sev, nl=False)
        typer.secho(f" {i.message}", nl=False)
        typer.secho(f"{loc} ({i.source.value}/{i.confidence.value})",
                    fg=typer.colors.BRIGHT_BLACK)
    if report.image_path:
        typer.secho(f"\n  image: {report.image_path}", fg=typer.colors.BRIGHT_BLACK)
    typer.echo()


def _exit_for(report: Report) -> None:
    if report.verdict == Verdict.FAIL:
        raise typer.Exit(code=2)


# --------------------------------------------------------------------------- commands

@app.command()
def version():
    """Print the AgentVision version."""
    typer.echo(__version__)


@app.command()
def analyze(
    source: str = typer.Argument(..., help="HTML/file/URL/SVG/PDF/image, or inline HTML."),
    backend: str = typer.Option(None, help="anthropic|openai|gemini|local"),
    instructions: str = typer.Option(None, help="Task context for the vision model."),
    expected: str = typer.Option(None, help="What the artifact was supposed to look like."),
    source_type: str = typer.Option("auto", help="auto|html|file|url|svg|pdf|image"),
    viewport: str = typer.Option(None, help="WxH, e.g. 1280x800"),
    full_page: bool = typer.Option(False, "--full-page/--viewport-only"),
    no_ocr: bool = typer.Option(False, "--no-ocr", help="Disable OCR grounding."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON."),
):
    """Render and analyze an artifact with a vision backend (+ DOM/CV grounding)."""
    from ..core import analyze as do_analyze

    settings = _settings(backend=backend, full_page=full_page, viewport=viewport)
    report = asyncio.run(do_analyze(
        source, settings=settings, backend=backend, instructions=instructions,
        expected=expected, use_ocr=not no_ocr, source_type=source_type, full_page=full_page,
    ))
    _print_report(report, json_out)
    _exit_for(report)


@app.command()
def check(
    source: str = typer.Argument(...),
    source_type: str = typer.Option("auto"),
    viewport: str = typer.Option(None, help="WxH"),
    full_page: bool = typer.Option(True, "--full-page/--viewport-only"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Classic DOM/CV checks only — no LLM, no API key, no egress."""
    from ..core import check as do_check

    settings = _settings(full_page=full_page, viewport=viewport)
    report = asyncio.run(do_check(source, settings=settings, source_type=source_type,
                                  full_page=full_page))
    _print_report(report, json_out)
    _exit_for(report)


@app.command()
def render(
    source: str = typer.Argument(...),
    out: str = typer.Option("agentvision-render.png", "-o", "--out"),
    source_type: str = typer.Option("auto"),
    viewport: str = typer.Option(None, help="WxH"),
    full_page: bool = typer.Option(True, "--full-page/--viewport-only"),
):
    """Render an artifact to a PNG."""
    from ..core import render as do_render

    settings = _settings(full_page=full_page, viewport=viewport)
    result = asyncio.run(do_render(source, settings=settings, source_type=source_type,
                                   full_page=full_page))
    if not result.primary:
        typer.secho("Render produced no image.", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    import shutil

    shutil.copyfile(result.primary.path, out)
    typer.secho(f"Rendered {result.primary.width}x{result.primary.height} -> {out}",
                fg=typer.colors.GREEN)


@app.command()
def diff(
    baseline: str = typer.Argument(..., help="Baseline image path."),
    candidate: str = typer.Argument(..., help="Candidate image path."),
    out: str = typer.Option("agentvision-diff.png", "-o", "--out"),
    threshold: float = typer.Option(0.98, help="Min SSIM to pass."),
    json_out: bool = typer.Option(False, "--json"),
):
    """Compare two images (SSIM + annotated diff)."""
    from ..core import compute_diff

    result = compute_diff(baseline, candidate, out)
    if json_out:
        typer.echo(result.model_dump_json(indent=2))
    else:
        typer.echo(f"SSIM {result.ssim:.4f} | changed {result.changed_ratio*100:.2f}% | "
                   f"{len(result.regions)} region(s)")
        typer.echo(result.narrative)
        if result.diff_image_path:
            typer.secho(f"diff image: {result.diff_image_path}", fg=typer.colors.BRIGHT_BLACK)
    if result.ssim < threshold:
        raise typer.Exit(code=2)


@app.command()
def ocr(
    source: str = typer.Argument(...),
    source_type: str = typer.Option("auto"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Extract text (+ word boxes) from an artifact via Tesseract."""
    from ..core import render as do_render
    from ..ocr import get_ocr_backend

    backend = get_ocr_backend()
    if not backend.available():
        typer.secho("Tesseract not available. Install: tesseract-ocr + tesseract-ocr-eng",
                    fg=typer.colors.RED)
        raise typer.Exit(code=1)
    settings = _settings(full_page=True)
    result = asyncio.run(do_render(source, settings=settings, source_type=source_type,
                                   full_page=True))
    if not result.primary:
        raise typer.Exit(code=1)
    res = backend.run(result.primary.path)
    if json_out:
        typer.echo(res.model_dump_json(indent=2))
    else:
        typer.echo(res.text)


@app.command()
def loop(
    source: str = typer.Argument(...),
    backend: str = typer.Option(None),
    max_iter: int = typer.Option(3, "--max-iter"),
    instructions: str = typer.Option(None),
    json_out: bool = typer.Option(False, "--json"),
):
    """Run the visual feedback loop (re-renders the source up to --max-iter times).

    Agents instead drive the loop programmatically, editing the source between iterations.
    """
    from ..core.loop import LoopSession

    settings = _settings(backend=backend, full_page=True)
    session = LoopSession(source, settings=settings, backend=backend, instructions=instructions)
    history = asyncio.run(session.run(max_iter=max_iter))
    if json_out:
        import json as _json

        typer.echo(_json.dumps([h.model_dump(mode="json") for h in history], indent=2))
    else:
        for h in history:
            tag = "PASS" if h.verdict == Verdict.PASS else ("STUCK" if h.stuck else h.verdict.value.upper())
            typer.secho(f"iter {h.index}: {tag} — {len(h.report.issues)} issue(s)",
                        fg=_VERDICT_COLOR.get(h.verdict))
            if h.diff:
                typer.secho(f"   Δ {h.diff.narrative}", fg=typer.colors.BRIGHT_BLACK)
        typer.echo(f"\nstop reason: {session.stop_reason or 'max-iter'}")
    last = history[-1] if history else None
    if last and last.verdict == Verdict.FAIL:
        raise typer.Exit(code=2)


@app.command()
def sheet(
    source: str = typer.Argument(...),
    breakpoints: str = typer.Option("375,768,1280,1920", help="Comma-separated widths."),
    out: str = typer.Option("agentvision-sheet.png", "-o", "--out"),
):
    """Render a responsive contact sheet across breakpoints."""
    from ..core.capture import contact_sheet

    bps = [int(x) for x in breakpoints.split(",") if x.strip()]
    settings = _settings()
    path, _ = asyncio.run(contact_sheet(source, settings=settings, breakpoints=bps, out_path=out))
    typer.secho(f"Contact sheet -> {path}", fg=typer.colors.GREEN)


@app.command()
def baseline(
    source: str = typer.Argument(...),
    name: str = typer.Option(..., "--name", help="Baseline name."),
    source_type: str = typer.Option("auto"),
):
    """Capture and store a named baseline for regression."""
    from ..core import set_baseline

    settings = _settings()
    path = asyncio.run(set_baseline(source, name, settings=settings, source_type=source_type))
    typer.secho(f"Baseline '{name}' saved -> {path}", fg=typer.colors.GREEN)


@app.command()
def regress(
    source: str = typer.Argument(...),
    name: str = typer.Option(..., "--name"),
    out: str = typer.Option("agentvision-regress.png", "-o", "--out"),
    threshold: float = typer.Option(0.98),
    json_out: bool = typer.Option(False, "--json"),
):
    """Render a source and compare it to a named baseline."""
    from ..core import regress as do_regress

    settings = _settings()
    result = asyncio.run(do_regress(source, name, settings=settings, out_path=out))
    if json_out:
        typer.echo(result.model_dump_json(indent=2))
    else:
        typer.echo(f"SSIM {result.ssim:.4f} vs baseline '{name}' — {result.narrative}")
    if result.ssim < threshold:
        typer.secho("Regression detected.", fg=typer.colors.RED)
        raise typer.Exit(code=2)


@app.command()
def demo():
    """Run the 60-second demo: broken page -> FAIL -> loop to fixed -> PASS (no API key)."""
    import tempfile

    from ..core.loop import LoopSession
    from ._demo_assets import BROKEN_HTML, FIXED_HTML

    settings = _settings(backend="local", full_page=True)
    typer.secho("AgentVision demo — giving an agent eyes (local backend, no API key)\n",
                fg=typer.colors.CYAN, bold=True)
    with tempfile.TemporaryDirectory() as td:
        broken = Path(td) / "broken.html"
        fixed = Path(td) / "fixed.html"
        broken.write_text(BROKEN_HTML)
        fixed.write_text(FIXED_HTML)

        session = LoopSession(str(broken), settings=settings, backend="local")
        typer.secho("1) The agent renders its page and looks at it:", bold=True)
        it0 = asyncio.run(session.iterate())
        _print_report(it0.report, False)

        typer.secho("2) The agent fixes the issues and looks again:", bold=True)
        it1 = asyncio.run(session.iterate(str(fixed)))
        _print_report(it1.report, False)
        if it1.diff:
            typer.secho(f"   what changed: {it1.diff.narrative}", fg=typer.colors.BRIGHT_BLACK)

        if it0.verdict == Verdict.FAIL and it1.verdict == Verdict.PASS:
            typer.secho("\n✓ The agent SAW the problems and fixed them — FAIL → PASS.",
                        fg=typer.colors.GREEN, bold=True)
            typer.secho("  That is the whole point: eyes for AI agents.\n", fg=typer.colors.GREEN)
        else:
            typer.secho("\nDemo did not reach the expected FAIL→PASS arc.",
                        fg=typer.colors.YELLOW)


@app.command()
def doctor(fix: bool = typer.Option(False, "--fix", help="Install the Chromium browser.")):
    """Diagnose rendering + backend readiness."""
    from .doctor import run_doctor

    ok = asyncio.run(run_doctor(fix=fix))
    raise typer.Exit(code=0 if ok else 1)


@app.command()
def serve(host: str = typer.Option("127.0.0.1"), port: int = typer.Option(8000)):
    """Start the REST service."""
    from .rest import serve as do_serve

    do_serve(host=host, port=port)


def main() -> None:
    app()


if __name__ == "__main__":
    sys.exit(app())
