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
              timeout: float | None = None, nav_wait: str | None = None,
              settle_ms: int | None = None, freeze: bool | None = None,
              allow_local: bool = False, render_timeout: float | None = None) -> Settings:
    overrides: dict = {}
    if backend:
        overrides["vision_backend"] = backend
    if full_page is not None:
        overrides["full_page"] = full_page
    if device_scale is not None:
        overrides["device_scale"] = device_scale
    if (timeout or render_timeout) is not None:
        overrides["render_timeout_s"] = render_timeout if render_timeout is not None else timeout
    if nav_wait:
        overrides["nav_wait"] = nav_wait
    if settle_ms is not None:
        overrides["settle_ms"] = settle_ms
    if freeze is not None:
        overrides["freeze_animations"] = freeze
    if allow_local:
        overrides["block_private_networks"] = False
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
    if report.conformance and report.conformance.claims:
        conf = report.conformance
        typer.secho(f"\n  intent match: {conf.satisfied}/{conf.total} requirement(s)",
                    fg=typer.colors.CYAN, bold=True)
        _mark = {"satisfied": ("✓", typer.colors.GREEN),
                 "violated": ("✗", typer.colors.RED),
                 "uncertain": ("?", typer.colors.YELLOW)}
        for c in conf.claims:
            sym, col = _mark.get(c.status.value, ("·", typer.colors.WHITE))
            typer.secho(f"    {sym} ", fg=col, nl=False)
            typer.secho(f"[{c.importance.value}] {c.text}", nl=False)
            typer.secho(f"  ({c.source.value})", fg=typer.colors.BRIGHT_BLACK)
    if report.image_path:
        typer.secho(f"\n  image: {report.image_path}", fg=typer.colors.BRIGHT_BLACK)
    typer.echo()


def _exit_for(report: Report) -> None:
    if report.verdict == Verdict.FAIL:
        raise typer.Exit(code=2)


def _emit(report: Report, json_out: bool, handoff: bool = False) -> None:
    """Print the full report, or the distilled eyes→brain handoff signal."""
    if handoff:
        typer.echo(report.to_handoff().model_dump_json(indent=2))
    else:
        _print_report(report, json_out)


def _run_report(coro, *, json_out: bool, handoff: bool, quiet: bool) -> None:
    """Run a report-producing coroutine and emit it.

    In ``--quiet`` (machine) mode ONLY the JSON object is written to stdout (logs stay on
    stderr), errors become a JSON ``{"error": ...}`` object, and exit codes are stable:
    0 = pass/warn, 2 = fail, 3 = error.
    """
    import json as _json

    from ..errors import AgentVisionError

    if quiet:
        import logging
        logging.getLogger("agentvision").setLevel(logging.ERROR)
        try:
            report = asyncio.run(coro)
        except AgentVisionError as e:
            typer.echo(_json.dumps({"error": str(e), "type": type(e).__name__}))
            raise typer.Exit(code=3) from e
        payload = (report.to_handoff().model_dump(mode="json") if handoff
                   else report.model_dump(mode="json"))
        typer.echo(_json.dumps(payload, indent=2))
        if report.verdict == Verdict.FAIL:
            raise typer.Exit(code=2)
        return
    report = asyncio.run(coro)
    _emit(report, json_out, handoff)
    _exit_for(report)


def _build_brief(brief: str | None, expect: list[str] | None, reference: str | None):
    """Assemble a Brief from CLI inputs, or None if no intent was supplied."""
    from ..models.intent import Brief

    b = Brief.from_inputs(text=brief, expect=expect, reference_image=reference)
    return None if b.is_empty() else b


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
    brief: str = typer.Option(None, help="The intended product — graded for intent match."),
    expect: list[str] = typer.Option(None, "--expect", help="A required visual claim "
                                      "(repeatable; prefix 'should:'/'nice:')."),
    reference: str = typer.Option(None, help="Reference/mockup image the render should match."),
    source_type: str = typer.Option("auto", help="auto|html|file|url|svg|pdf|image"),
    viewport: str = typer.Option(None, help="WxH, e.g. 1280x800"),
    full_page: bool = typer.Option(False, "--full-page/--viewport-only"),
    wait_for: str = typer.Option(None, "--wait-for", help="CSS selector to wait for before "
                                 "capture (for client-rendered data)."),
    settle_ms: int = typer.Option(None, "--settle-ms", help="Quiet wait (ms) after load so "
                                  "client-rendered data can populate."),
    freeze: bool = typer.Option(None, "--freeze/--no-freeze", help="Pause animations + rAF "
                                "before capture (default on; needed for canvas/WebGL)."),
    nav_wait: str = typer.Option(None, "--nav-wait", help="load|domcontentloaded|networkidle "
                                 "(default load; networkidle is bounded)."),
    render_timeout: float = typer.Option(None, "--render-timeout", help="Max render seconds."),
    allow_local: bool = typer.Option(False, "--allow-local", help="Allow localhost / LAN URLs."),
    no_ocr: bool = typer.Option(False, "--no-ocr", help="Disable OCR grounding."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON."),
    handoff: bool = typer.Option(False, "--handoff", help="Emit the eyes→brain handoff "
                                 "signal (JSON) for an agent/brain to act on."),
    quiet: bool = typer.Option(False, "--quiet", help="Machine mode: only JSON on stdout, "
                               "logs on stderr, stable exit codes (0 pass/warn, 2 fail, 3 error)."),
):
    """Render and analyze an artifact with a vision backend (+ DOM/CV grounding).

    Pass --brief/--expect/--reference to also grade *intent conformance*.
    """
    from ..core import analyze as do_analyze

    settings = _settings(backend=backend, full_page=full_page, viewport=viewport,
                         nav_wait=nav_wait, settle_ms=settle_ms, freeze=freeze,
                         allow_local=allow_local, render_timeout=render_timeout)
    _run_report(do_analyze(
        source, settings=settings, backend=backend, instructions=instructions,
        expected=expected, brief=_build_brief(brief, expect, reference),
        use_ocr=not no_ocr, source_type=source_type, full_page=full_page, wait_for=wait_for,
    ), json_out=json_out, handoff=handoff, quiet=quiet)


@app.command()
def conform(
    source: str = typer.Argument(..., help="HTML/file/URL/SVG/PDF/image, or inline HTML."),
    brief: str = typer.Option(None, help="Free-text description of the intended product."),
    expect: list[str] = typer.Option(None, "--expect", help="A required visual claim "
                                      "(repeatable; prefix 'should:'/'nice:')."),
    reference: str = typer.Option(None, help="Reference/mockup image the render should match."),
    backend: str = typer.Option(None, help="anthropic|openai|gemini|ollama|local"),
    source_type: str = typer.Option("auto"),
    viewport: str = typer.Option(None, help="WxH"),
    full_page: bool = typer.Option(False, "--full-page/--viewport-only"),
    wait_for: str = typer.Option(None, "--wait-for", help="CSS selector to wait for first."),
    settle_ms: int = typer.Option(None, "--settle-ms", help="Quiet wait (ms) after load."),
    freeze: bool = typer.Option(None, "--freeze/--no-freeze", help="Pause animations + rAF."),
    nav_wait: str = typer.Option(None, "--nav-wait", help="load|domcontentloaded|networkidle."),
    render_timeout: float = typer.Option(None, "--render-timeout", help="Max render seconds."),
    allow_local: bool = typer.Option(False, "--allow-local", help="Allow localhost / LAN URLs."),
    json_out: bool = typer.Option(False, "--json"),
    handoff: bool = typer.Option(False, "--handoff", help="Emit the eyes→brain handoff "
                                 "signal (JSON) for an agent/brain to act on."),
    quiet: bool = typer.Option(False, "--quiet", help="Machine mode: only JSON on stdout."),
):
    """Grade an artifact against intent — does it match what you set out to build?"""
    from ..core import analyze as do_analyze

    the_brief = _build_brief(brief, expect, reference)
    if the_brief is None:
        typer.secho("Provide at least one of --brief / --expect / --reference.",
                    fg=typer.colors.RED)
        raise typer.Exit(code=1)
    settings = _settings(backend=backend, full_page=full_page, viewport=viewport,
                         nav_wait=nav_wait, settle_ms=settle_ms, freeze=freeze,
                         allow_local=allow_local, render_timeout=render_timeout)
    _run_report(do_analyze(
        source, settings=settings, backend=backend, brief=the_brief,
        source_type=source_type, full_page=full_page, wait_for=wait_for,
    ), json_out=json_out, handoff=handoff, quiet=quiet)


@app.command()
def check(
    source: str = typer.Argument(...),
    source_type: str = typer.Option("auto"),
    viewport: str = typer.Option(None, help="WxH"),
    full_page: bool = typer.Option(True, "--full-page/--viewport-only"),
    wait_for: str = typer.Option(None, "--wait-for", help="CSS selector to wait for first."),
    settle_ms: int = typer.Option(None, "--settle-ms", help="Quiet wait (ms) after load."),
    freeze: bool = typer.Option(None, "--freeze/--no-freeze", help="Pause animations + rAF."),
    nav_wait: str = typer.Option(None, "--nav-wait", help="load|domcontentloaded|networkidle."),
    render_timeout: float = typer.Option(None, "--render-timeout", help="Max render seconds."),
    allow_local: bool = typer.Option(False, "--allow-local", help="Allow localhost / LAN URLs."),
    json_out: bool = typer.Option(False, "--json"),
    handoff: bool = typer.Option(False, "--handoff", help="Emit the eyes→brain handoff "
                                 "signal (JSON) for an agent/brain to act on."),
    quiet: bool = typer.Option(False, "--quiet", help="Machine mode: only JSON on stdout."),
):
    """Classic DOM/CV checks only — no LLM, no API key, no egress."""
    from ..core import check as do_check

    settings = _settings(full_page=full_page, viewport=viewport, nav_wait=nav_wait,
                         settle_ms=settle_ms, freeze=freeze, allow_local=allow_local,
                         render_timeout=render_timeout)
    _run_report(do_check(source, settings=settings, source_type=source_type,
                         full_page=full_page, wait_for=wait_for),
                json_out=json_out, handoff=handoff, quiet=quiet)


@app.command()
def render(
    source: str = typer.Argument(...),
    out: str = typer.Option("agentvision-render.png", "-o", "--out"),
    source_type: str = typer.Option("auto"),
    viewport: str = typer.Option(None, help="WxH"),
    full_page: bool = typer.Option(True, "--full-page/--viewport-only"),
    wait_for: str = typer.Option(None, "--wait-for", help="CSS selector to wait for first."),
    settle_ms: int = typer.Option(None, "--settle-ms", help="Quiet wait (ms) after load."),
    freeze: bool = typer.Option(None, "--freeze/--no-freeze", help="Pause animations + rAF."),
    nav_wait: str = typer.Option(None, "--nav-wait", help="load|domcontentloaded|networkidle."),
    render_timeout: float = typer.Option(None, "--render-timeout", help="Max render seconds."),
    allow_local: bool = typer.Option(False, "--allow-local", help="Allow localhost / LAN URLs."),
):
    """Render an artifact to a PNG."""
    from ..core import render as do_render

    settings = _settings(full_page=full_page, viewport=viewport, nav_wait=nav_wait,
                         settle_ms=settle_ms, freeze=freeze, allow_local=allow_local,
                         render_timeout=render_timeout)
    result = asyncio.run(do_render(source, settings=settings, source_type=source_type,
                                   full_page=full_page, wait_for=wait_for))
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
    brief: str = typer.Option(None, help="The intended product — graded for intent match."),
    expect: list[str] = typer.Option(None, "--expect", help="A required visual claim "
                                      "(repeatable; prefix 'should:'/'nice:')."),
    reference: str = typer.Option(None, help="Reference/mockup image the render should match."),
    nav_wait: str = typer.Option(None, "--nav-wait", help="load|domcontentloaded|networkidle."),
    settle_ms: int = typer.Option(None, "--settle-ms", help="Quiet wait (ms) after load."),
    freeze: bool = typer.Option(None, "--freeze/--no-freeze", help="Pause animations + rAF."),
    render_timeout: float = typer.Option(None, "--render-timeout", help="Max render seconds."),
    allow_local: bool = typer.Option(False, "--allow-local", help="Allow localhost / LAN URLs."),
    json_out: bool = typer.Option(False, "--json"),
):
    """Run the visual feedback loop (re-renders the source up to --max-iter times).

    Agents instead drive the loop programmatically, editing the source between iterations.
    With --brief/--expect/--reference the loop is conformance-aware (matches intent, not just
    defect-free).
    """
    from ..core.loop import LoopSession

    settings = _settings(backend=backend, full_page=True, nav_wait=nav_wait,
                         settle_ms=settle_ms, freeze=freeze, allow_local=allow_local,
                         render_timeout=render_timeout)
    session = LoopSession(source, settings=settings, backend=backend, instructions=instructions,
                          brief=_build_brief(brief, expect, reference))
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
def generate(
    generator: str = typer.Option(..., "--generator", help="Generator hook as 'module:function' "
                                  "— a callable (prompt:str)->image_path."),
    brief: str = typer.Option(None, help="Free-text description of what to generate."),
    expect: list[str] = typer.Option(None, "--expect", help="A required visual claim "
                                      "(repeatable; prefix 'should:'/'nice:')."),
    reference: str = typer.Option(None, help="Reference/mockup image the output should match."),
    backend: str = typer.Option(None, help="Vision backend used to perceive + refine."),
    max_iter: int = typer.Option(4, "--max-iter"),
    out: str = typer.Option("agentvision-generated.png", "-o", "--out"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Generative loop: generate → see → grade vs intent → refine prompt → regenerate.

    The generator is YOUR callable, e.g. ``mypkg.gen:make_image``; AgentVision never bundles
    an image-gen dependency. Closes the loop for AI images/infographics until they match the
    brief.
    """
    import importlib

    from ..core.generate import GenerativeLoopSession

    the_brief = _build_brief(brief, expect, reference)
    if the_brief is None:
        typer.secho("Provide at least one of --brief / --expect / --reference.",
                    fg=typer.colors.RED)
        raise typer.Exit(code=1)
    try:
        mod_name, _, fn_name = generator.partition(":")
        fn = getattr(importlib.import_module(mod_name), fn_name)
    except (ImportError, AttributeError, ValueError) as e:
        typer.secho(f"Could not load generator '{generator}': {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from e

    settings = _settings(backend=backend)
    session = GenerativeLoopSession(the_brief, fn, settings=settings, backend=backend)
    history = asyncio.run(session.run(max_iter=max_iter))
    if json_out:
        import json as _json

        typer.echo(_json.dumps([h.model_dump(mode="json") for h in history], indent=2))
    else:
        for h in history:
            tag = "PASS" if h.verdict == Verdict.PASS else ("STUCK" if h.stuck
                                                            else h.verdict.value.upper())
            conf = h.report.conformance
            score = f" — intent {conf.satisfied}/{conf.total}" if conf and conf.claims else ""
            typer.secho(f"gen {h.index}: {tag}{score}", fg=_VERDICT_COLOR.get(h.verdict))
        typer.echo(f"\nstop reason: {session.stop_reason or 'max-iter'}")
    last = history[-1] if history else None
    if last and last.artifact:
        import shutil

        try:
            shutil.copyfile(last.artifact, out)
            typer.secho(f"final artifact -> {out}", fg=typer.colors.GREEN)
        except OSError:
            typer.secho(f"final artifact: {last.artifact}", fg=typer.colors.BRIGHT_BLACK)
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
