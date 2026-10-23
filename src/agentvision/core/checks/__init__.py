"""Classic checks (no LLM): contrast, overflow, broken images, console, blank.

These produce coordinate-grounded :class:`Issue`s that both stand alone (``agentvision
check``) and ground the vision backend (fed as ``dom_hints``).
"""

from __future__ import annotations

from pathlib import Path

from ...models.report import Issue
from ...ocr.base import OcrResult
from ...renderers.base import RenderResult
from .contrast import check_contrast_dom
from .contrast_ocr import check_contrast_ocr
from .contrast_pixel import check_contrast_pixel
from .layout import (
    check_blank,
    check_broken_images,
    check_clipped_text,
    check_console,
    check_overflow,
    run_structural_checks,
)
from .spelling import check_spelling_from_ocr

# IssueKinds the classic-checks layer (and thus the local backend) can emit.
CLASSIC_CAPABILITIES = [
    "contrast", "overflow", "clipped", "overlap", "broken_image", "error_text", "typo",
    "blank", "other",
]


def _strip_format(text: str) -> str:
    """Drop Unicode format characters (soft hyphen, zero-width, bidi marks, variation
    selectors) so a word split by them reads as the word OCR sees."""
    import unicodedata

    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf"
                   and not ("\ufe00" <= ch <= "\ufe0f") and ch not in "\u034f\u180e")


def run_all_checks(
    render: RenderResult, image_path: str | Path | None, ocr: OcrResult | None = None,
    *, extra_words: frozenset[str] = frozenset(), spell_variants: bool = True,
) -> list[Issue]:
    issues: list[Issue] = []
    issues += check_contrast_dom(render)                  # solid-background samples (exact)
    issues += check_contrast_pixel(render, image_path)    # DOM text over a non-solid backdrop
    issues += run_structural_checks(render, image_path)
    if ocr is not None:
        # A live desktop capture is not an artifact whose text WE authored — it's full of
        # correctly-spelled proper nouns / identifiers / non-English UI copy (app names,
        # filenames, code tokens) that a plain dictionary flags as high-confidence "typos",
        # which would hard-FAIL a perfectly normal screen. Skip spell-check for desktop sources.
        if render.source_type != "desktop":
            # Only VISIBLE in-frame text (contrast samples), each with its glyph box: a hidden
            # or off-screen word can't launder a typo as an "OCR split".
            # Each visible line with ITS OWN words (from per-word rects in the page), so a word
            # elsewhere in the paragraph can't complete an OCR fragment on this line.
            dom_words = tuple(
                (frozenset(words), line, s.font_px)
                for s in render.contrast_samples
                if s.visible_frac >= 0.5 and s.text
                for line, words in zip(s.glyph_rects, s.line_words or [], strict=False)
                if words
            )
            import re as _re

            # Visible page text vocabulary (HTML sources): real typos are in it, OCR misreads
            # are not. None for raster inputs (no DOM), which keep confidence-based severity.
            page_vocab = None
            if render.contrast_samples or render.vocab_text:
                page_vocab = frozenset(
                    w.lower() for w in _re.findall(r"[A-Za-z]+", render.vocab_text or "")
                ) | frozenset(
                    w.lower() for s in render.contrast_samples if s.visible_frac >= 0.5
                    for w in _re.findall(r"[A-Za-z]+", _strip_format(s.text or ""))
                )
            issues += check_spelling_from_ocr(
                ocr, extra_words=extra_words, variants=spell_variants, dom_words=dom_words,
                page_vocab=page_vocab,
            )
        issues += check_contrast_ocr(render, image_path, ocr)  # text painted into a <canvas>
    return issues


__all__ = [
    "run_all_checks", "run_structural_checks", "check_contrast_dom", "check_contrast_pixel",
    "check_contrast_ocr", "check_overflow", "check_broken_images", "check_clipped_text",
    "check_console", "check_blank", "check_spelling_from_ocr", "CLASSIC_CAPABILITIES",
]
