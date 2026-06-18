"""Local backend — offline, no API key, no egress.

It performs NO semantic critique. It packages the grounded DOM/CV/OCR findings (computed
upstream and passed as ``dom_hints``) into a Report. This is the honest fallback and the
privacy-preserving option, not an equivalent to the LLM backends.
"""

from __future__ import annotations

import time

from ..core.checks import CLASSIC_CAPABILITIES
from ..models.report import Report, verdict_from_issues
from .base import AnalysisRequest


class LocalBackend:
    name = "local"

    def available(self) -> bool:
        return True

    async def analyze(self, req: AnalysisRequest) -> Report:
        t0 = time.monotonic()
        issues = list(req.dom_hints)
        verdict = verdict_from_issues(issues)
        if issues:
            summary = (f"Heuristic structural analysis (no semantic critique): found "
                       f"{len(issues)} issue(s).")
        else:
            summary = ("Heuristic structural analysis (no semantic critique): no structural "
                       "defects detected. Note: the local backend cannot judge visual/semantic "
                       "correctness — use an LLM backend for that.")
        return Report(
            verdict=verdict, summary=summary, issues=issues,
            capabilities=[c for c in CLASSIC_CAPABILITIES],  # type: ignore[list-item]
            backend=self.name, model=None,
            viewport=req.viewport, device_scale=req.device_scale,
            image_path=req.image_path,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )
