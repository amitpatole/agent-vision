"""Spelling / garbled-text check.

Runs OCR words through a dictionary to flag misspellings and garbled text (e.g. diffusion-
mangled labels, typos in UI copy). Offline and deterministic; requires Tesseract (OCR) and
``pyspellchecker``. The vision-LLM backends provide a second, semantic layer.

The dictionary is US English, so by default a word is also accepted when its **Commonwealth
variant** maps to a known US spelling (colour/color, centre/center, organise/organize,
catalogue/catalog, defence/defense, travelled/traveled). Operators add house vocabulary
(show, talent and brand names) via ``spell_allow_words`` / ``spell_allow_file``.
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
    # Common media / news navigation and product words missing from the base dictionary.
    "tech", "podcast", "podcasts", "livestream", "livestreams", "esports", "vlog", "vlogs",
    "streamer", "streamers", "biz", "newsletter", "newsletters", "rewatch", "binge",
    "inbox", "signup", "login", "logout", "apps", "smartphone", "smartphones", "hashtag",
    "hashtags", "selfie", "selfies", "wifi", "paywall", "livestreamed", "covid", "lockdown",
    "lockdowns", "crypto", "bitcoin", "influencer", "influencers", "ebook", "ebooks", "webinar",
    "webinars", "autoplay", "playlist", "playlists", "online", "app", "website", "websites",
    "email", "emails", "homepage", "username", "unsubscribe", "subscribers",
    "intro", "intros", "outro", "admin", "admins", "faq", "faqs", "emoji", "emojis",
    "dropdown", "tooltip", "tooltips", "navbar", "popup", "popups", "analytics", "workflow",
    "workflows", "fintech", "ecommerce", "preorder", "preorders", "dashboard", "dashboards",
    "checkout", "wishlist", "chatbot", "podcaster", "vlogger", "fullscreen",
    "viewport", "localhost", "kubectl", "frontend", "backend", "devops", "npm",
    "javascript", "typescript", "apis", "sdk", "sdks", "urls", "https", "http",
}

# Cost bounds: pyspellchecker's correction() is edit-distance-2 search, ~1 s for a 10-letter
# unknown word and ~20 s for 45 letters. An attacker page full of long gibberish must not pin
# the grader, so suggestions are skipped for long words, capped, and time-boxed.
_MAX_SUGGEST_LEN = 12
_MAX_SUGGESTIONS = 30
_MAX_TYPO_ISSUES = 50
_SPELL_BUDGET_S = 3.0


# Commonwealth -> US spelling rewrites, tried only for a word the dictionary does not know.
_VARIANT_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # -our only as a suffix (colour, harbour, favourite, honourable) — never mid-word, so a
    # typo like "fourm" is not rewritten to "form" and masked.
    # Only known British -our stems (a generic "-our" rewrite would accept "histoury",
    # "victoury", "doctour"), with their real derived endings.
    (re.compile(r"^(col|flav|fav|hon|harb|hum|lab|neighb|behavi|rum|sav|vap|vig|arm|endeav|od"
                r"|parl|rig|savi|splend|tum|val|clam|cand|ard|glam|dol|cal)our"
                r"(?=(s|ed|ing|ite|ites|itism|able|ably|er|ers|ful|hood|hoods|less|ist|ists|ism"
                r"|ly|y|al|ally|some|side|ways|is(e|es|ed|ing|ation))?$)"), r"\1or"),
    # -re only for known British -re stems: a generic "-re -> -er" rewrite would accept
    # transposition typos ("lagre" -> lager, "nevre" -> never).
    (re.compile(r"^(cent|epicent|theat|amphitheat|met|kilomet|centimet|millimet|lit|millilit"
                r"|fib|calib|sab|somb|spect|lust|meag|och|mit|scept|manoeuv|goit)re(s|d)?$"),
     r"\1er\2"),
    # -ise only after a 3+ letter stem: "sise"/"bise" must not become "size"/"bize".
    (re.compile(r"(?<=[a-z]{3})is(e|es|ed|ing|ation|ations|er|ers)$"), r"iz\1"),  # organise
    (re.compile(r"ys(e|es|ed|ing)$"), r"yz\1"),                    # analyse, paralysed
    (re.compile(r"ogue(s)?$"), r"og\1"),                          # catalogue, dialogue
    (re.compile(r"^(def|off|lic|pret)ence(s)?$"), r"\1ense\2"),     # defence, licence
    # Doubled l after a SINGLE vowel following a consonant (travelled, cancelling); not after
    # a vowel pair ("feelling", "dealling") or an i-e stem ("smilling"). "fuelled" is listed.
    (re.compile(r"(?<=[^aeiou][aeou])ll(ed|ing|er|ers)$"), r"l\1"),
    (re.compile(r"^(an|encyclop|pal|arch)ae"), r"\1e"),            # anaemia, palaeontology
    (re.compile(r"^programme(s|d)?$"), r"program\1"),
)


# British forms no suffix rule reaches (whole words, with simple plural/derived endings).
_BRITISH_WORDS = {
    "jewellery": "jewelry", "cheque": "check", "cheques": "checks", "aluminium": "aluminum", "pyjamas": "pajamas", "manoeuvre": "maneuver",
    "manoeuvres": "maneuvers", "sceptical": "skeptical", "sceptic": "skeptic", "draught": "draft", "draughts": "drafts",
    "aeroplane": "airplane", "aeroplanes": "airplanes", "tyre": "tire", "tyres": "tires",
    "storey": "story", "storeys": "stories", "grey": "gray", "plough": "plow",
    "whilst": "while", "amongst": "among", "programme": "program", "practise": "practice",
    "licence": "license", "offence": "offense", "defence": "defense", "towards": "toward",
    "learnt": "learned", "spelt": "spelled", "fuelled": "fueled", "fuelling": "fueling", "travellers": "travelers", "jewellers": "jewelers",
}


def _variant_candidates(low: str) -> set[str]:
    out: set[str] = set()
    if low in _BRITISH_WORDS:
        out.add(_BRITISH_WORDS[low])
    combined = low
    for pat, rep in _VARIANT_RULES:
        alt = pat.sub(rep, low)
        if alt != low:
            out.add(alt)
        combined = pat.sub(rep, combined)
    if combined != low:
        out.add(combined)                                          # e.g. colourised
    return out


def _split_kind(low: str, word, ocr_words, dom_words: tuple, sp) -> str | None:
    """How an unknown OCR word relates to the page's own visible text.

    "skip": an OCR split — a dictionary word on the same visible line completes it AND the
    missing piece is itself an adjacent OCR token ("A" + "greement"). "soft": a dictionary
    word on the same visible line, at a similar size, completes it (likely a split whose piece
    OCR dropped; reported as a WARNING, never silently). None: an ordinary unknown word.
    A tiny decoy, a hidden word, a non-word or a word elsewhere in the paragraph matches none.
    """
    b = word.bbox
    cx, cy = b.x + b.width / 2, b.y + b.height / 2
    best = None
    for words, line, font_px in dom_words:
        if not (line.x - 4 <= cx <= line.x + line.width + 4
                and line.y - 4 <= cy <= line.y + line.height + 4):
            continue
        if low in words:
            return None  # the page itself contains the fragment as a word: a real break
        if font_px and not (0.4 * font_px <= b.height <= 2.5 * font_px):
            continue  # a decoy at a different size is not this text
        for d in words:
            if d == low or len(d) - len(low) > 2 or not sp.known([d]):
                continue
            if d.endswith(low):
                missing = d[: len(d) - len(low)]
            elif d.startswith(low):
                missing = d[len(low):]
            else:
                continue
            for o in ocr_words:
                if o is word or (o.text or "").strip().lower().strip(".,:;!?") != missing:
                    continue
                ob = o.bbox
                same_line = abs((ob.y + ob.height / 2) - cy) <= 0.6 * max(b.height, 1)
                gap = max(ob.x - (b.x + b.width), b.x - (ob.x + ob.width))
                if same_line and gap <= max(b.height, 4):
                    return "skip"
            best = "soft"
    return best


def check_spelling_from_ocr(
    ocr: OcrResult, *, min_len: int = 4, extra_words: frozenset[str] = frozenset(),
    variants: bool = True, dom_words: tuple = (), page_vocab: frozenset[str] | None = None,
) -> list[Issue]:
    """``dom_words``: ``(words, line_bbox, font_px)`` from VISIBLE in-frame text lines, used to
    recognise OCR word splits (see :func:`_split_kind`)."""
    try:
        from spellchecker import SpellChecker
    except ImportError:
        return []  # pyspellchecker not installed — skip silently
    if not ocr or not ocr.words:
        return []

    import time

    sp = SpellChecker()
    issues: list[Issue] = []
    seen: set[str] = set()
    t0 = time.monotonic()
    suggested = 0
    for w in ocr.words:
        token = (w.text or "").strip()
        # URLs, emails and @handles are not prose.
        if "://" in token or "@" in token or token.lower().startswith("www."):
            continue
        # Check each alphabetic segment (handles hyphenated/compound tokens).
        for seg in re.findall(r"[A-Za-z]+", token):
            if len(seg) < min_len:
                continue
            low = seg.lower()
            if low in WHITELIST or low in extra_words or low in seen:
                continue
            # Skip short ALL-CAPS acronyms and mixed/camelCase identifiers.
            if seg.isupper() and len(seg) <= 5:
                continue
            if not (seg.islower() or seg.istitle() or seg.isupper()):
                continue
            if sp.known([low]):
                continue
            if variants and sp.known(_variant_candidates(low)):
                continue
            # OCR split a word ("Agreement" read as "A greement"): a fragment of a longer word
            # that the page's own text contains is an OCR artifact, not a typo.
            split = _split_kind(low, w, ocr.words, dom_words, sp) if dom_words else None
            if split == "skip":
                continue
            seen.add(low)
            if len(issues) >= _MAX_TYPO_ISSUES:
                return issues
            suggestion = None
            if (len(low) <= _MAX_SUGGEST_LEN and suggested < _MAX_SUGGESTIONS
                    and time.monotonic() - t0 < _SPELL_BUDGET_S):
                suggested += 1
                suggestion = sp.correction(low)
            msg = f"Possible misspelling / garbled text: '{seg}'"
            if suggestion and suggestion != low:
                msg += f" — did you mean '{suggestion}'?"
            confident = w.confidence >= 0.85  # confident OCR + unknown word => real typo
            # On a page with DOM text, a real typo is IN the page's own visible text. An
            # unknown word OCR produced that the page doesn't contain is an OCR misread
            # ("reserved" read as "resen"): a WARNING, never a page FAIL.
            if page_vocab is not None and low not in page_vocab:
                confident = False
            # Capitalised unknown words are overwhelmingly names in news copy (bylines, people,
            # places, teams): ~11% of common news names sit one edit from a dictionary word
            # (Starmer, Haaland), so they are WARNINGs. Lowercase unknowns stay ERRORs.
            if seg.istitle() or seg.isupper() or split == "soft":
                confident = False
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
