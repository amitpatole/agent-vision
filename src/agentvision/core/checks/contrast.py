"""WCAG contrast checks from computed-style samples.

DOM computed-style contrast is exact over solid backgrounds — those are graded here as a hard
AA fail. Over a gradient/image/opacity/``<canvas>`` the computed ``background-color`` isn't the
real backdrop, so the sample is emitted ``confidence == "low"`` and handed to
[`check_contrast_pixel`](contrast_pixel.py), which measures the actual rendered pixels instead
of guessing. This function therefore owns **solid-background** samples only.
"""

from __future__ import annotations

from ...models.report import Confidence, Issue, IssueKind, IssueSource, Severity
from ...renderers.base import RenderResult


def check_contrast_dom(render: RenderResult) -> list[Issue]:
    issues: list[Issue] = []
    for s in render.contrast_samples:
        if s.passes_aa:
            continue
        if s.confidence == "low":
            # Non-solid background: computed-style contrast is unreliable here. Ceded to the
            # pixel check (real-bitmap grading) so we don't emit a confident-but-wrong ratio.
            continue
        snippet = (s.text[:40] + "…") if len(s.text) > 40 else s.text
        issues.append(Issue.make(
            IssueKind.CONTRAST,
            Severity.ERROR,
            f"Low contrast (ratio {s.ratio:.2f}, needs "
            f"{'3.0' if s.large_text else '4.5'} for AA) on text '{snippet}' "
            f"[{s.fg} on {s.bg}]",
            bbox=s.bbox, bbox_precise=True, source=IssueSource.DOM,
            confidence=Confidence.HIGH,
            detail={"ratio": s.ratio, "fg": s.fg, "bg": s.bg, "selector": s.selector,
                    "wcag": "AA-fail", "large_text": s.large_text},
        ))
    return issues
