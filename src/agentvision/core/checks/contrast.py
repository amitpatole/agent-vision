"""WCAG contrast checks from computed-style samples.

DOM computed-style contrast is exact over solid backgrounds (emitted high-confidence) and
honestly degraded over gradients/images/opacity (emitted low-confidence, never a hard
FAIL). Pixel-based contrast on non-HTML rasters is a separate, clearly-labeled heuristic.
"""

from __future__ import annotations

from ...models.report import Confidence, Issue, IssueKind, IssueSource, Severity
from ...renderers.base import RenderResult


def check_contrast_dom(render: RenderResult) -> list[Issue]:
    issues: list[Issue] = []
    for s in render.contrast_samples:
        if s.passes_aa:
            continue
        low = s.confidence == "low"
        snippet = (s.text[:40] + "…") if len(s.text) > 40 else s.text
        msg = (
            f"Low contrast (ratio {s.ratio:.2f}, needs "
            f"{'3.0' if s.large_text else '4.5'} for AA) on text '{snippet}' "
            f"[{s.fg} on {s.bg}]"
        )
        if low:
            msg += " (background not solid — verify manually)"
        issues.append(Issue.make(
            IssueKind.CONTRAST,
            Severity.WARNING if low else Severity.ERROR,
            msg,
            bbox=s.bbox, bbox_precise=True, source=IssueSource.DOM,
            confidence=Confidence.LOW if low else Confidence.HIGH,
            detail={"ratio": s.ratio, "fg": s.fg, "bg": s.bg, "selector": s.selector,
                    "wcag": "AA-fail", "large_text": s.large_text},
        ))
    return issues
