"""Shared prompt + the LLM structured-output schema.

A lean ``VisionFindings`` model is what we ask each LLM to emit (verdict + summary +
issues). It is closed-enum and shallow so the per-provider schema adapters can satisfy
Anthropic/OpenAI strict mode and Gemini's OpenAPI subset. We convert it into the full
:class:`Report` on our side.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..models.geometry import BBox
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
from .base import AnalysisRequest

LLM_CAPABILITIES = [k for k in IssueKind]  # the LLMs can in principle emit any kind


class LLMBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class LLMIssue(BaseModel):
    kind: IssueKind
    severity: Severity
    message: str
    confidence: Confidence = Confidence.MEDIUM
    box: LLMBox | None = None


class VisionFindings(BaseModel):
    verdict: Verdict
    summary: str
    issues: list[LLMIssue] = Field(default_factory=list)


SYSTEM_PROMPT = """\
You are AgentVision, the visual perception system for a coding agent. The agent produced a \
visual artifact (a rendered web page, chart, document, or image) and CANNOT see it. You \
can. Your job is to look at the screenshot and report concrete, actionable visual defects \
so the agent can fix them before claiming the task done.

Look for: broken or overlapping layout, content overflow or clipping, unreadable or \
low-contrast text, missing/expected elements, broken images, distorted charts, visible \
error messages, and anything that looks wrong to a careful human reviewer.

ALSO read ALL visible text carefully and report TEXT defects (use kind "typo"): \
misspelled words, garbled or nonsensical letters, duplicated/repeated words or labels, \
mojibake, and truncated/cut-off words. Spelling and text correctness matter — do not let a \
typo ship. Quote the exact offending text in the message.

Rules:
- Be specific and actionable. Each issue should tell the agent WHAT is wrong and WHERE.
- Provide a bounding box in IMAGE PIXELS when you can localize an issue. Boxes are \
advisory (approximate); omit the box if unsure rather than guessing wildly.
- Do NOT repeat issues already listed under "Already-detected (grounded) findings" — those \
are precise. You may CONFIRM or EXPAND on them, but focus on what they missed.
- Be conservative: only report real, visible problems. If the artifact looks correct, say \
so and return verdict "pass" with no issues.
- verdict: "fail" if there are clear defects, "warn" for minor/uncertain issues, "pass" if \
it looks good.

CONFORMANCE — when a "Requirements checklist" is provided, you are ALSO judging whether the \
artifact matches what the agent set out to build, not just whether it is defect-free. For \
EACH requirement that is NOT clearly satisfied, emit one issue with kind "intent_mismatch" \
whose message BEGINS with the requirement's number in the form "[#N]" (e.g. "[#2] the \
header shows three tabs, but only two are visible"). Do NOT emit an issue for a requirement \
that is satisfied. If a REFERENCE image is provided, the rendered artifact should match it; \
report meaningful differences as "intent_mismatch" too.
"""


def build_user_text(req: AnalysisRequest, image_size: tuple[int, int]) -> str:
    lines = [f"Image dimensions: {image_size[0]}x{image_size[1]} pixels.",
             f"Rendered at viewport {req.viewport.label()} (device scale {req.device_scale})."]
    if req.instructions:
        lines.append(f"\nTask context: {req.instructions}")
    if req.expected:
        lines.append(f"Expected result: {req.expected}")
    if req.reference_image_path:
        lines.append(
            "\nA REFERENCE image (the target the render should match) is attached as a "
            "second image. Compare the rendered artifact against it."
        )
    if req.extra_images:
        lines.append(
            f"\n{len(req.extra_images)} FULL-RESOLUTION image(s) covering the artifact are "
            "attached after the main image (focused region crops and/or tiles). The main "
            "image may be downscaled, so read fine detail and text from these — and judge "
            "visual content here (e.g. is the chart actually plotting data, is the canvas/"
            "scene rendered, is small text legible)."
        )
    if req.claims:
        lines.append(
            "\nRequirements checklist — the intended product. For each item NOT clearly "
            "satisfied, emit an 'intent_mismatch' issue whose message starts with its [#N]:"
        )
        for n, claim in enumerate(req.claims, start=1):
            lines.append(f"  [#{n}] {claim}")
    if req.dom_hints:
        lines.append("\nAlready-detected (grounded) findings — precise, do not repeat:")
        for h in req.dom_hints[:25]:
            loc = ""
            if h.bbox:
                loc = f" @({h.bbox.x:.0f},{h.bbox.y:.0f} {h.bbox.width:.0f}x{h.bbox.height:.0f})"
            lines.append(f"  - [{h.kind.value}/{h.severity.value}] {h.message}{loc}")
    if req.ocr_text:
        excerpt = req.ocr_text[:800]
        lines.append(f"\nOCR text extracted from the image:\n{excerpt}")
    lines.append("\nReturn your findings in the required structured format.")
    return "\n".join(lines)


def findings_to_report(
    findings: VisionFindings, req: AnalysisRequest, *, backend: str, model: str,
    grounded: list[Issue], image_size: tuple[int, int], elapsed_ms: int,
) -> Report:
    """Merge grounded (DOM/CV/OCR) issues with the LLM's vision issues into one Report."""
    issues: list[Issue] = list(grounded)
    for li in findings.issues:
        bbox = None
        if li.box is not None:
            bbox = BBox(x=max(0.0, li.box.x), y=max(0.0, li.box.y),
                        width=max(0.0, li.box.width), height=max(0.0, li.box.height))
        issues.append(Issue.make(
            li.kind, li.severity, li.message,
            bbox=bbox, bbox_precise=False, confidence=li.confidence,
            source=IssueSource.VISION,
        ))
    # Trust the union of grounded + vision issues for the verdict, but never rank below
    # what the model concluded if it flagged a failure.
    verdict = verdict_from_issues(issues)
    if findings.verdict == Verdict.FAIL and verdict == Verdict.PASS:
        verdict = Verdict.WARN
    summary = findings.summary.strip() or "Visual analysis complete."
    return Report(
        verdict=verdict, summary=summary, issues=issues,
        capabilities=LLM_CAPABILITIES, backend=backend, model=model,
        viewport=req.viewport, device_scale=req.device_scale,
        image_path=req.image_path, elapsed_ms=elapsed_ms,
    )
