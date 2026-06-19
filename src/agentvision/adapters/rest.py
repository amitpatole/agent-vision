"""REST service (FastAPI) — for non-MCP / networked / CI agents.

Security: API keys are read server-side only (never accepted in requests), and per-request
backend selection is limited to the server's allowlist (``rest_enabled_backends``). Loop
sessions are kept in-process; a multi-worker deployment needs shared storage or sticky
sessions (documented in docs/adapters.md).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from ..config import load_settings
from ..errors import AgentVisionError, MissingDependencyError

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse
    from pydantic import BaseModel
except ImportError:  # pragma: no cover
    FastAPI = None  # type: ignore


_sessions: dict = {}
_artifacts: dict[str, str] = {}


def _register_artifact(path: str | None) -> str | None:
    if not path:
        return None
    aid = uuid.uuid4().hex[:12]
    _artifacts[aid] = path
    return aid


def build_app():
    if FastAPI is None:
        raise MissingDependencyError("REST service", pip_extra="serve")

    from .. import __version__

    app = FastAPI(title="AgentVision", version=__version__)
    settings = load_settings()

    def _brief_from(body) -> object | None:
        from ..models.intent import Brief

        b = Brief.from_inputs(
            text=getattr(body, "brief", None),
            expect=getattr(body, "expect", None),
            reference_image=getattr(body, "reference", None),
        )
        return None if b.is_empty() else b

    class AnalyzeBody(BaseModel):
        source: str
        source_type: str = "auto"
        backend: str | None = None
        instructions: str | None = None
        expected: str | None = None
        brief: str | None = None
        expect: list[str] | None = None
        reference: str | None = None
        full_page: bool = True

    class ConformBody(BaseModel):
        source: str
        source_type: str = "auto"
        backend: str | None = None
        brief: str | None = None
        expect: list[str] | None = None
        reference: str | None = None
        full_page: bool = True

    class CheckBody(BaseModel):
        source: str
        source_type: str = "auto"
        full_page: bool = True

    class LoopBody(BaseModel):
        source: str
        backend: str | None = None
        instructions: str | None = None
        brief: str | None = None
        expect: list[str] | None = None
        reference: str | None = None

    class IterBody(BaseModel):
        source: str | None = None

    class BaselineBody(BaseModel):
        source: str
        name: str
        source_type: str = "auto"

    def _check_backend(name: str | None):
        if name and name not in settings.rest_enabled_backends:
            raise HTTPException(
                status_code=400,
                detail=f"Backend {name!r} not enabled on this server. "
                       f"Allowed: {settings.rest_enabled_backends}",
            )

    @app.get("/healthz")
    def healthz():
        from .. import __version__

        return {"status": "ok", "version": __version__}

    @app.post("/analyze")
    async def analyze_ep(body: AnalyzeBody):
        from ..core import analyze

        _check_backend(body.backend)
        try:
            report = await analyze(body.source, settings=settings, backend=body.backend,
                                   instructions=body.instructions, expected=body.expected,
                                   brief=_brief_from(body),
                                   source_type=body.source_type, full_page=body.full_page)
        except AgentVisionError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        data = report.model_dump(mode="json")
        data["artifact_id"] = _register_artifact(report.image_path)
        return data

    @app.post("/conform")
    async def conform_ep(body: ConformBody):
        from ..core import analyze

        _check_backend(body.backend)
        the_brief = _brief_from(body)
        if the_brief is None:
            raise HTTPException(status_code=400,
                                detail="Provide at least one of brief / expect / reference.")
        try:
            report = await analyze(body.source, settings=settings, backend=body.backend,
                                   brief=the_brief, source_type=body.source_type,
                                   full_page=body.full_page)
        except AgentVisionError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        data = report.model_dump(mode="json")
        data["artifact_id"] = _register_artifact(report.image_path)
        return data

    @app.post("/handoff")
    async def handoff_ep(body: AnalyzeBody):
        """Perceive + return the distilled eyes→brain handoff signal (verdict + next action)."""
        from ..core import analyze

        _check_backend(body.backend)
        try:
            report = await analyze(body.source, settings=settings, backend=body.backend,
                                   instructions=body.instructions, expected=body.expected,
                                   brief=_brief_from(body),
                                   source_type=body.source_type, full_page=body.full_page)
        except AgentVisionError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        data = report.to_handoff().model_dump(mode="json")
        data["artifact_id"] = _register_artifact(report.image_path)
        return data

    class WatchBody(BaseModel):
        source: str
        backend: str | None = None
        frames: int | None = None
        interval_ms: int | None = None
        brief: str | None = None
        expect: list[str] | None = None
        use_vision: bool = True

    @app.post("/watch")
    async def watch_ep(body: WatchBody):
        from ..core import watch

        _check_backend(body.backend)
        try:
            report = await watch(body.source, settings=settings, backend=body.backend,
                                 frames=body.frames, interval_ms=body.interval_ms,
                                 brief=_brief_from(body), use_vision=body.use_vision)
        except AgentVisionError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        data = report.model_dump(mode="json")
        data["artifact_id"] = _register_artifact(report.image_path)
        return data

    @app.post("/check")
    async def check_ep(body: CheckBody):
        from ..core import check

        report = await check(body.source, settings=settings, source_type=body.source_type,
                             full_page=body.full_page)
        data = report.model_dump(mode="json")
        data["artifact_id"] = _register_artifact(report.image_path)
        return data

    @app.post("/loop")
    async def loop_ep(body: LoopBody):
        from ..core.loop import LoopSession

        _check_backend(body.backend)
        session = LoopSession(body.source, settings=settings, backend=body.backend,
                             instructions=body.instructions, brief=_brief_from(body))
        _sessions[session.session_id] = session
        result = await session.iterate()
        return {"session_id": session.session_id,
                "iteration": result.model_dump(mode="json")}

    @app.post("/loop/{session_id}/iterate")
    async def loop_iter_ep(session_id: str, body: IterBody):
        session = _sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown session_id")
        result = await session.iterate(body.source)
        return {"session_id": session_id, "iteration": result.model_dump(mode="json"),
                "stop_reason": session.stop_reason}

    @app.post("/sheet")
    async def sheet_ep(body: CheckBody):
        from ..core.capture import contact_sheet

        path, _ = await contact_sheet(body.source, settings=settings,
                                      source_type=body.source_type)
        return {"artifact_id": _register_artifact(path)}

    @app.post("/baseline")
    async def baseline_ep(body: BaselineBody):
        from ..core import set_baseline

        path = await set_baseline(body.source, body.name, settings=settings,
                                  source_type=body.source_type)
        return {"name": body.name, "path": path}

    @app.get("/baseline/{name}")
    async def get_baseline(name: str):
        from ..core.baseline import _baseline_path

        p = _baseline_path(settings, name)
        if not p.exists():
            raise HTTPException(status_code=404, detail="no such baseline")
        return FileResponse(str(p))

    @app.get("/artifacts/{artifact_id}")
    def get_artifact(artifact_id: str):
        path = _artifacts.get(artifact_id)
        if not path or not Path(path).exists():
            raise HTTPException(status_code=404, detail="no such artifact")
        return FileResponse(path)

    return app


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(build_app(), host=host, port=port)


def main() -> None:
    serve()


if __name__ == "__main__":
    main()
