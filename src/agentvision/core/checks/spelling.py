"""Spelling / garbled-text check.

Runs OCR words through a dictionary to flag misspellings and garbled text (e.g. diffusion-
mangled labels, typos in UI copy). Offline and deterministic; requires Tesseract (OCR) and
``pyspellchecker``. The vision-LLM backends provide a second, semantic layer.
"""

from __future__ import annotations

import re

from ...models.report import Confidence, Issue, IssueKind, IssueSource, Severity
from ...ocr.base import OcrResult

# Brand / technical terms that are correct but not in a standard dictionary.
WHITELIST = {
    "agentvision", "agent", "vision", "eyes", "ai", "github", "com", "amitpatole",
    "dom", "cv", "ocr", "wcag", "ssim", "llm", "llms", "api", "cli", "mcp", "rest",
    "pip", "png", "svg", "pdf", "html", "css", "json", "url", "repo", "uis", "ui",
    "ux", "playwright", "chromium", "tesseract", "ollama", "gemma", "gpt", "openai",
    "anthropic", "claude", "gemini", "headless", "self", "correcting", "screenshot",
    "favicon", "webpage", "config", "async", "init",
}


def check_spelling_from_ocr(ocr: OcrResult, *, min_len: int = 4) -> list[Issue]:
    try:
        from spellchecker import SpellChecker
    except ImportError:
        return []  # pyspellchecker not installed — skip silently
    if not ocr or not ocr.words:
        return []

    sp = SpellChecker()
    issues: list[Issue] = []
    seen: set[str] = set()
    for w in ocr.words:
        token = (w.text or "").strip()
        # Check each alphabetic segment (handles hyphenated/compound tokens).
        for seg in re.findall(r"[A-Za-z]+", token):
            if len(seg) < min_len:
                continue
            low = seg.lower()
            if low in WHITELIST or low in seen:
                continue
            # Skip short ALL-CAPS acronyms and mixed/camelCase identifiers.
            if seg.isupper() and len(seg) <= 5:
                continue
            if not (seg.islower() or seg.istitle() or seg.isupper()):
                continue
            if sp.known([low]):
                continue
            seen.add(low)
            suggestion = sp.correction(low)
            msg = f"Possible misspelling / garbled text: '{seg}'"
            if suggestion and suggestion != low:
                msg += f" — did you mean '{suggestion}'?"
            confident = w.confidence >= 0.85  # confident OCR + unknown word => real typo
            issues.append(Issue.make(
                IssueKind.TYPO,
                Severity.ERROR if confident else Severity.WARNING,
                msg,
                bbox=w.bbox, bbox_precise=True, source=IssueSource.OCR,
                confidence=Confidence.HIGH if confident else Confidence.LOW,
                detail={"word": seg, "in_token": token, "suggestion": suggestion,
                        "ocr_confidence": round(w.confidence, 2)},
            ))
    return issues
