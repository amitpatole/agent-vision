"""REST service (FastAPI) — for non-MCP / networked / CI agents.

Security: API keys are read server-side only (never accepted in requests), and per-request
backend selection is limited to the server's allowlist (``rest_enabled_backends``). Loop
sessions are kept in-process; a multi-worker deployment needs shared storage or sticky
sessions (documented in docs/adapters.md).
"""

from __future__ import annotations

import asyncio
import hmac
import uuid
from pathlib import Path

from pydantic import BaseModel  # base dependency — always present

from ..config import load_settings
from ..errors import AgentVisionError, MissingDependencyError, UnsafeSourceError
from ..logging import get_logger
from ..models.intent import Brief

try:
    from fastapi import Depends, FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse, JSONResponse
except ImportError:  # pragma: no cover
    FastAPI = None  # type: ignore


log = get_logger("rest")
_LOOPBACK = {"127.0.0.1", "::1", "localhost", "0:0:0:0:0:0:0:1"}

_sessions: dict = {}
_artifacts: dict[str, str] = {}


def _is_loopback(host: str) -> bool:
    return host in _LOOPBACK


# Request bodies must live at module scope: with `from __future__ import annotations`, FastAPI
# resolves the handler annotations from module globals — models nested in build_app() can't be
# resolved and the body is mis-read as a query param (422).
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


class WatchBody(BaseModel):
    source: str
    backend: str | None = None
    frames: int | None = None
    interval_ms: int | None = None
    brief: str | None = None
    expect: list[str] | None = None
    use_vision: bool = True


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

    # Service hardening: a remote caller must not read host files via a bare-path source, and
    # Office conversion (LibreOffice) is too large an attack surface to expose to remote input.
    settings = load_settings(allow_local_files=False, allow_office_render=False)

    def _auth(request: Request):
        """Bearer-token auth (constant-time). Zero-config on loopback; required once a token
        is set. Binding a non-loopback host without a token is refused in serve()."""
        if request.url.path == "/healthz":
            return
        token = settings.api_token
        if not token:
            return
        provided = request.headers.get("authorization", "")
        if not hmac.compare_digest(provided, f"Bearer {token}"):
            raise HTTPException(status_code=401, detail="Unauthorized")

    app = FastAPI(title="AgentVision", version=__version__, dependencies=[Depends(_auth)])

    # Bound the work an attacker can trigger: cap request bodies and the number of concurrent
    # renders (each render spawns a browser / heavy decode).
    _render_sem = asyncio.Semaphore(settings.max_concurrent_renders)

    @app.middleware("http")
    async def _limit_body(request: Request, call_next):
        cap = settings.max_request_bytes
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > cap:
            return JSONResponse({"detail": "Request body too large."}, status_code=413)
        # Also enforce on the stream itself — a chunked request (no Content-Length) would
        # otherwise bypass the header check and buffer unbounded.
        total = 0
        chunks: list[bytes] = []
        async for chunk in request.stream():
            total += len(chunk)
            if total > cap:
                return JSONResponse({"detail": "Request body too large."}, status_code=413)
            chunks.append(chunk)
        body = b"".join(chunks)

        async def _replay():
            return {"type": "http.request", "body": body, "more_body": False}

        request._body = body            # cache so downstream .json()/.body() use the read bytes
        request._receive = _replay      # and so the handler can still receive it
        return await call_next(request)

    async def _render_slot():
        async with _render_sem:
            yield

    def _http_error(e: Exception) -> HTTPException:
        # Safety messages are intentionally non-sensitive (no IPs/paths) — return them; for
        # everything else return a generic message and log the detail server-side only.
        if isinstance(e, UnsafeSourceError):
            return HTTPException(status_code=400, detail=str(e))
        log.warning("request failed: %s: %s", type(e).__name__, e)
        return HTTPException(status_code=400, detail="Could not render or analyze the source.")

    def _brief_from(body) -> Brief | None:
        b = Brief.from_inputs(
            text=getattr(body, "brief", None),
            expect=getattr(body, "expect", None),
            reference_image=getattr(body, "reference", None),
        )
        return None if b.is_empty() else b

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
    async def analyze_ep(body: AnalyzeBody, _slot=Depends(_render_slot)):
        from ..core import analyze

        _check_backend(body.backend)
        try:
            report = await analyze(body.source, settings=settings, backend=body.backend,
                                   instructions=body.instructions, expected=body.expected,
                                   brief=_brief_from(body),
                                   source_type=body.source_type, full_page=body.full_page)
        except AgentVisionError as e:
            raise _http_error(e) from e
        data = report.model_dump(mode="json")
        data["artifact_id"] = _register_artifact(report.image_path)
        return data

    @app.post("/conform")
    async def conform_ep(body: ConformBody, _slot=Depends(_render_slot)):
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
            raise _http_error(e) from e
        data = report.model_dump(mode="json")
        data["artifact_id"] = _register_artifact(report.image_path)
        return data

    @app.post("/handoff")
    async def handoff_ep(body: AnalyzeBody, _slot=Depends(_render_slot)):
        """Perceive + return the distilled eyes→brain handoff signal (verdict + next action)."""
        from ..core import analyze

        _check_backend(body.backend)
        try:
            report = await analyze(body.source, settings=settings, backend=body.backend,
                                   instructions=body.instructions, expected=body.expected,
                                   brief=_brief_from(body),
                                   source_type=body.source_type, full_page=body.full_page)
        except AgentVisionError as e:
            raise _http_error(e) from e
        data = report.to_handoff().model_dump(mode="json")
        data["artifact_id"] = _register_artifact(report.image_path)
        return data

    @app.post("/watch")
    async def watch_ep(body: WatchBody, _slot=Depends(_render_slot)):
        from ..core import watch

        _check_backend(body.backend)
        try:
            report = await watch(body.source, settings=settings, backend=body.backend,
                                 frames=body.frames, interval_ms=body.interval_ms,
                                 brief=_brief_from(body), use_vision=body.use_vision)
        except AgentVisionError as e:
            raise _http_error(e) from e
        data = report.model_dump(mode="json")
        data["artifact_id"] = _register_artifact(report.image_path)
        return data

    @app.post("/check")
    async def check_ep(body: CheckBody, _slot=Depends(_render_slot)):
        from ..core import check

        try:
            report = await check(body.source, settings=settings, source_type=body.source_type,
                                 full_page=body.full_page)
        except AgentVisionError as e:
            raise _http_error(e) from e
        data = report.model_dump(mode="json")
        data["artifact_id"] = _register_artifact(report.image_path)
        return data

    @app.post("/loop")
    async def loop_ep(body: LoopBody, _slot=Depends(_render_slot)):
        from ..core.loop import LoopSession

        _check_backend(body.backend)
        session = LoopSession(body.source, settings=settings, backend=body.backend,
                             instructions=body.instructions, brief=_brief_from(body))
        try:
            result = await session.iterate()
        except AgentVisionError as e:
            raise _http_error(e) from e
        _sessions[session.session_id] = session
        return {"session_id": session.session_id,
                "iteration": result.model_dump(mode="json")}

    @app.post("/loop/{session_id}/iterate")
    async def loop_iter_ep(session_id: str, body: IterBody, _slot=Depends(_render_slot)):
        session = _sessions.get(session_id)
        if session is None:
            # Fail loud, not silent: behind multiple workers/replicas a loop started on one
            # worker 404s here unless requests are sticky-routed by session_id. Name the cause
            # and the fixes rather than leaving a swarm to debug a bare "unknown session_id".
            raise HTTPException(
                status_code=404,
                detail=(
                    "Unknown session_id. Loop sessions live in the worker process that "
                    "created them; behind multiple workers/replicas this 404s unless requests "
                    "are sticky-routed by session_id. Fixes: run loops on a single replica, "
                    "enable sticky sessions, or keep the loop client-side (library LoopSession) "
                    "and call only the stateless endpoints. "
                    "See https://amitpatole.github.io/agent-vision/scaling/."
                ),
            )
        try:
            result = await session.iterate(body.source)
        except AgentVisionError as e:
            raise _http_error(e) from e
        return {"session_id": session_id, "iteration": result.model_dump(mode="json"),
                "stop_reason": session.stop_reason}

    @app.post("/sheet")
    async def sheet_ep(body: CheckBody, _slot=Depends(_render_slot)):
        from ..core.capture import contact_sheet

        try:
            path, _ = await contact_sheet(body.source, settings=settings,
                                          source_type=body.source_type)
        except AgentVisionError as e:
            raise _http_error(e) from e
        return {"artifact_id": _register_artifact(path)}

    @app.post("/baseline")
    async def baseline_ep(body: BaselineBody, _slot=Depends(_render_slot)):
        from ..core import set_baseline

        try:
            path = await set_baseline(body.source, body.name, settings=settings,
                                      source_type=body.source_type)
        except AgentVisionError as e:
            raise _http_error(e) from e
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
    # Fail closed: never expose a routable interface without a token.
    if not _is_loopback(host) and not load_settings().api_token:
        raise SystemExit(
            f"Refusing to bind non-loopback host {host!r} without auth. Set AGENTVISION_API_TOKEN "
            "to expose the service (clients send 'Authorization: Bearer <token>'), or bind 127.0.0.1."
        )
    import uvicorn

    uvicorn.run(build_app(), host=host, port=port)


def main() -> None:
    serve()


if __name__ == "__main__":
    main()
