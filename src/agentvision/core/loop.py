"""The visual feedback loop — the headline feature.

A ``LoopSession`` runs iterations of render -> perceive -> report -> diff-vs-previous, with
persisted per-iteration state. Progress/stuck is decided by **issue-set stability**, not by
SSIM: a real fix can barely move pixels and thrashing can move them a lot.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..config import Settings, load_settings
from ..models.diff import DiffResult
from ..models.report import Report, Verdict
from ..workspace import Workspace
from .analyze import analyze
from .diff import compute_diff


class IterationResult(BaseModel):
    index: int
    report: Report
    diff: DiffResult | None = None
    verdict: Verdict
    progressed: bool = False
    stuck: bool = False
    artifacts: dict[str, str] = Field(default_factory=dict)


class LoopSession:
    """Drive the visual feedback loop for one artifact across iterations.

    Agents call :meth:`iterate` after each fix attempt (optionally passing an updated
    ``source``). The session persists state under the workspace so it can be resumed.
    """

    def __init__(
        self,
        source: str,
        *,
        settings: Settings | None = None,
        backend: str | None = None,
        instructions: str | None = None,
        expected: str | None = None,
        source_type: str = "auto",
        session_id: str | None = None,
        stuck_threshold: int = 2,
    ):
        self.source = source
        self.settings = settings or load_settings()
        self.backend = backend
        self.instructions = instructions
        self.expected = expected
        self.source_type = source_type
        self.stuck_threshold = stuck_threshold
        self.ws = Workspace(self.settings)
        self.session_id = session_id or self.ws.new_session_id()
        self.history: list[IterationResult] = []
        self._signatures: list[frozenset] = []
        self._repeat_count = 0
        self.stop_reason: str | None = None

    @property
    def last_image(self) -> str | None:
        for it in reversed(self.history):
            if it.report.image_path:
                return it.report.image_path
        return None

    async def iterate(self, source: str | None = None) -> IterationResult:
        idx = len(self.history)
        src = source if source is not None else self.source
        if source is not None:
            self.source = source
        out_dir = self.ws.iter_dir(self.session_id, idx)

        prev_image = self.last_image
        report = await analyze(
            src, settings=self.settings, backend=self.backend,
            instructions=self.instructions, expected=self.expected,
            source_type=self.source_type, out_dir=out_dir,
        )

        diff = None
        if prev_image and report.image_path:
            diff = compute_diff(prev_image, report.image_path, out_dir / "diff.png")

        # Issue-set based progress / stuck detection.
        sig = report.issue_signature()
        progressed = bool(self._signatures and sig != self._signatures[-1])
        if self._signatures and sig == self._signatures[-1] and report.verdict != Verdict.PASS:
            self._repeat_count += 1
        else:
            self._repeat_count = 0
        self._signatures.append(sig)
        stuck = self._repeat_count >= (self.stuck_threshold - 1) and report.verdict != Verdict.PASS

        # Persist artifacts.
        (out_dir / "report.json").write_text(report.model_dump_json(indent=2))
        artifacts = {"report": str(out_dir / "report.json")}
        if report.image_path:
            artifacts["image"] = report.image_path
        if diff and diff.diff_image_path:
            artifacts["diff"] = diff.diff_image_path

        result = IterationResult(
            index=idx, report=report, diff=diff, verdict=report.verdict,
            progressed=progressed, stuck=stuck, artifacts=artifacts,
        )
        self.history.append(result)
        self.ws.write_session_meta(self.session_id, {
            "source_type": self.source_type, "backend": self.backend or "auto",
            "iterations": len(self.history),
            "last_verdict": report.verdict.value,
        })
        if report.verdict == Verdict.PASS:
            self.stop_reason = "pass"
        elif stuck:
            self.stop_reason = "stuck"
        return result

    async def run(self, max_iter: int = 5) -> list[IterationResult]:
        """Convenience: iterate the SAME source up to ``max_iter`` times.

        Useful for demonstrating stuck-detection on an unchanged artifact. Real agents
        drive :meth:`iterate` themselves, editing the source between calls.
        """
        for _ in range(max_iter):
            result = await self.iterate()
            if result.verdict == Verdict.PASS or result.stuck:
                break
        return self.history
