"""The generative conformance loop — eyes for *generative* artifacts.

For a hand-written page the agent fixes code between iterations. For a **generated** artifact
(a diffusion infographic, an AI image) the "fix" is a better *prompt*. This loop closes that
gap: ``generate → perceive → grade-vs-intent → refine-prompt → regenerate`` until the output
matches the brief (or we run out of iterations / stop making progress).

``generator`` is a user-supplied callable ``(prompt: str) -> image_path`` (sync or async).
AgentVision never ships an image-gen dependency — it only calls your hook — so the loop stays
provider-agnostic (DALL·E, gpt-image, Qwen-Image, a local SD, anything).
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from pydantic import BaseModel

from ..config import Settings, load_settings
from ..models.intent import Brief
from ..models.report import ClaimStatus, IssueKind, Report, Severity, Verdict
from .analyze import analyze

GeneratorFn = Callable[[str], str | Awaitable[str]]

_REFINE_SYSTEM = (
    "You refine the text prompt given to an image/artifact generator so its next output "
    "better matches the requirements. You are given the current prompt and the visual "
    "problems found in the last output. Return ONLY the improved generation prompt — no "
    "commentary, no preamble. Keep what worked, fix what failed, and be specific and "
    "concrete (exact text, counts, layout, colors)."
)


class GenerationStep(BaseModel):
    index: int
    prompt: str
    report: Report
    verdict: Verdict
    artifact: str | None = None
    progressed: bool = False
    stuck: bool = False


class GenerativeLoopSession:
    """Drive generate → perceive → refine until the output matches the brief."""

    def __init__(
        self,
        brief: Brief,
        generator: GeneratorFn,
        *,
        settings: Settings | None = None,
        backend: str | None = None,
        source_type: str = "image",
        stuck_threshold: int = 2,
    ):
        if brief.is_empty():
            raise ValueError("GenerativeLoopSession needs a non-empty Brief to grade against.")
        self.brief = brief
        self.generator = generator
        self.settings = settings or load_settings()
        self.backend = backend
        self.source_type = source_type
        self.stuck_threshold = stuck_threshold
        self.history: list[GenerationStep] = []
        self.stop_reason: str | None = None
        self._signatures: list[frozenset] = []
        self._repeat = 0

    def _initial_prompt(self) -> str:
        if self.brief.text:
            return self.brief.text
        return "Create an artifact meeting these requirements: " + "; ".join(
            c.text for c in self.brief.claims
        )

    async def _call_generator(self, prompt: str) -> str:
        out = self.generator(prompt)
        if inspect.isawaitable(out):
            out = await out
        return out

    async def _refine(self, prompt: str, report: Report) -> str | None:
        from ..backends.registry import select_backend

        vision, _ = select_backend(self.settings, self.backend)
        problems = self._problem_list(report)
        try:
            improved = await vision.complete_text(
                _REFINE_SYSTEM,
                f"Current generation prompt:\n{prompt}\n\n"
                f"Problems found in the output:\n{problems}\n\n"
                "Return the improved generation prompt.",
            )
        except Exception:  # noqa: BLE001
            return None
        improved = (improved or "").strip()
        return improved or None

    @staticmethod
    def _problem_list(report: Report) -> str:
        lines: list[str] = []
        if report.conformance:
            for c in report.conformance.claims:
                if c.status != ClaimStatus.SATISFIED:
                    lines.append(f"- unmet requirement: {c.text} ({c.evidence})")
        for i in report.issues:
            if i.kind == IssueKind.INTENT_MISMATCH:
                continue  # already covered by the conformance list
            if i.severity in (Severity.ERROR, Severity.CRITICAL, Severity.WARNING):
                lines.append(f"- {i.kind.value}: {i.message}")
        return "\n".join(lines) or "- (no specific problems parsed; improve overall fidelity)"

    async def run(self, max_iter: int = 4) -> list[GenerationStep]:
        prompt = self._initial_prompt()
        for idx in range(max_iter):
            artifact = await self._call_generator(prompt)
            report = await analyze(
                artifact, settings=self.settings, backend=self.backend,
                brief=self.brief, source_type=self.source_type,
            )
            sig = report.issue_signature()
            progressed = bool(self._signatures and sig != self._signatures[-1])
            if self._signatures and sig == self._signatures[-1] and report.verdict != Verdict.PASS:
                self._repeat += 1
            else:
                self._repeat = 0
            self._signatures.append(sig)
            stuck = self._repeat >= (self.stuck_threshold - 1) and report.verdict != Verdict.PASS

            self.history.append(GenerationStep(
                index=idx, prompt=prompt, report=report, verdict=report.verdict,
                artifact=artifact, progressed=progressed, stuck=stuck,
            ))

            if report.verdict == Verdict.PASS:
                self.stop_reason = "matched intent"
                break
            if stuck:
                self.stop_reason = "stuck"
                break
            if idx == max_iter - 1:
                self.stop_reason = "max-iter"
                break
            refined = await self._refine(prompt, report)
            if not refined:
                self.stop_reason = "cannot refine (no LLM backend available)"
                break
            prompt = refined
        return self.history
