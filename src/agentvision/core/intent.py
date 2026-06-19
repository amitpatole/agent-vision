"""Intent-grounded conformance.

Turns *the thought* (a :class:`~agentvision.models.intent.Brief`) into a checklist, grades
the render against it, and gates the verdict so PASS means **"matches what I set out to
build"**, not merely "defect-free".

Three signals, in increasing trust:
* **vision** — the backend emits ``intent_mismatch`` issues citing ``[#N]`` for unmet items;
* **OCR text-presence** — deterministic, model-independent ground truth for quoted-text
  requirements (and the *only* conformance signal the offline ``local`` backend has);
* **verdict gate** — a violated ``must`` fails regardless of how the model scored it.
"""

from __future__ import annotations

import re

from ..logging import get_logger
from ..models.intent import Brief, IntentClaim
from ..models.report import (
    ClaimResult,
    ClaimStatus,
    Confidence,
    Conformance,
    Importance,
    Issue,
    IssueKind,
    IssueSource,
    Severity,
    Verdict,
)

log = get_logger("intent")

_CLAIM_REF = re.compile(r"\[#(\d+)\]")
# Quoted exact text in a claim: requires the quoted span to contain a word character
# (so stray/contraction apostrophes don't register as a quote).
_QUOTED = re.compile(r"[\"“”'']([^\"“”'']*\w[^\"“”'']*)[\"“”'']")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")

_EXTRACT_SYSTEM = (
    "You convert a visual brief into a checklist of concrete, individually checkable visual "
    "requirements for a rendered artifact. Output ONE requirement per line — no numbering, "
    "no preamble, no blank lines. Each line states a single observable property (text that "
    "must appear, layout, element counts, colors, theme). When the brief names exact text, "
    "put it in quotes. Prefix optional items with 'should:' and nice-to-haves with 'nice:'; "
    "mandatory items need no prefix. Keep each line under 16 words."
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


async def derive_claims(
    brief: Brief, *, backend, max_claims: int = 12
) -> list[IntentClaim]:
    """Explicit claims ∪ claims the eyes extract from the free-text brief."""
    claims: list[IntentClaim] = list(brief.claims)
    if brief.text:
        seen = {_norm(c.text) for c in claims}
        for c in await _extract_claims_llm(brief.text, backend=backend, limit=max_claims):
            if _norm(c.text) not in seen:
                claims.append(c)
                seen.add(_norm(c.text))
    return claims[:max_claims] if max_claims else claims


async def _extract_claims_llm(text: str, *, backend, limit: int) -> list[IntentClaim]:
    try:
        out = await backend.complete_text(
            _EXTRACT_SYSTEM, f"Brief:\n{text}\n\nReturn the requirements, one per line."
        )
    except Exception as e:  # noqa: BLE001
        log.debug("claim extraction failed (%s); using explicit claims only", e)
        return []
    claims: list[IntentClaim] = []
    for line in (out or "").splitlines():
        line = _BULLET.sub("", line).strip()
        if len(line) < 3:
            continue
        claims.append(IntentClaim.parse(line))
        if len(claims) >= limit:
            break
    return claims


def check_claims_ocr(
    claims: list[IntentClaim], ocr_text: str | None
) -> dict[int, ClaimResult]:
    """Deterministically grade quoted-text requirements against OCR'd text.

    Only claims that quote exact text are decided here (model-independent ground truth);
    everything else is left to the vision backend.
    """
    results: dict[int, ClaimResult] = {}
    if not ocr_text:
        return results
    hay = _norm(ocr_text)
    for i, claim in enumerate(claims):
        quoted = _QUOTED.findall(claim.text)
        if not quoted:
            continue
        missing = [q for q in quoted if _norm(q) not in hay]
        results[i] = ClaimResult(
            text=claim.text,
            importance=claim.importance,
            status=ClaimStatus.SATISFIED if not missing else ClaimStatus.VIOLATED,
            confidence=Confidence.HIGH,
            source=IssueSource.OCR,
            evidence=("required text found in the render" if not missing
                      else f"required text not found in the render: {missing}"),
        )
    return results


def build_conformance(
    claims: list[IntentClaim],
    issues: list[Issue],
    ocr_results: dict[int, ClaimResult],
    *,
    semantic_graded: bool,
) -> Conformance:
    """Fuse vision ``intent_mismatch`` issues + OCR results into per-claim grades.

    ``semantic_graded`` is False when no vision backend actually looked for mismatches
    (e.g. the offline ``local`` backend). In that case an un-flagged, non-OCR claim is
    ``uncertain`` — never silently ``satisfied`` — so we don't claim coverage we lack.
    """
    flagged: dict[int, Issue] = {}
    for iss in issues:
        if iss.kind != IssueKind.INTENT_MISMATCH:
            continue
        m = _CLAIM_REF.search(iss.message)
        if m:
            flagged.setdefault(int(m.group(1)) - 1, iss)

    out: list[ClaimResult] = []
    for i, claim in enumerate(claims):
        if i in ocr_results:
            out.append(ocr_results[i])
        elif i in flagged:
            iss = flagged[i]
            status = (ClaimStatus.UNCERTAIN if iss.confidence == Confidence.LOW
                      else ClaimStatus.VIOLATED)
            out.append(ClaimResult(
                text=claim.text, importance=claim.importance, status=status,
                confidence=iss.confidence, source=IssueSource.VISION, evidence=iss.message,
            ))
        elif semantic_graded:
            out.append(ClaimResult(
                text=claim.text, importance=claim.importance,
                status=ClaimStatus.SATISFIED, confidence=Confidence.MEDIUM,
                source=IssueSource.VISION, evidence="no mismatch reported",
            ))
        else:
            out.append(ClaimResult(
                text=claim.text, importance=claim.importance,
                status=ClaimStatus.UNCERTAIN, confidence=Confidence.LOW,
                source=IssueSource.CV,
                evidence="not graded — the offline backend cannot judge visual intent",
            ))
    return Conformance(claims=out)


def ocr_violation_issues(ocr_results: dict[int, ClaimResult]) -> list[Issue]:
    """Surface deterministically-failed text requirements as first-class issues."""
    out: list[Issue] = []
    for idx, res in ocr_results.items():
        if res.status != ClaimStatus.VIOLATED:
            continue
        sev = Severity.ERROR if res.importance == Importance.MUST else Severity.WARNING
        out.append(Issue.make(
            IssueKind.INTENT_MISMATCH, sev, f"[#{idx + 1}] {res.evidence}",
            confidence=Confidence.HIGH, source=IssueSource.OCR,
            detail={"claim": res.text, "importance": res.importance.value},
        ))
    return out


def gate_verdict(verdict: Verdict, conformance: Conformance | None) -> Verdict:
    """A violated ``must`` ⇒ FAIL; a violated ``should`` / uncertain ``must`` ⇒ at least WARN."""
    if conformance is None or not conformance.claims:
        return verdict
    must_violated = any(
        c.importance == Importance.MUST and c.status == ClaimStatus.VIOLATED
        for c in conformance.claims
    )
    soft = any(
        (c.importance == Importance.SHOULD and c.status == ClaimStatus.VIOLATED)
        or (c.importance == Importance.MUST and c.status == ClaimStatus.UNCERTAIN)
        for c in conformance.claims
    )
    if must_violated:
        return Verdict.FAIL
    if soft and verdict == Verdict.PASS:
        return Verdict.WARN
    return verdict
