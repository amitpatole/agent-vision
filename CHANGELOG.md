# Changelog

All notable changes to AgentVision are documented here.

## [0.3.0] — 2026-06-19

### Added — intent-grounded conformance ("match the thought, not just avoid defects")
AgentVision was a *defect detector* — it caught overflow/contrast/typos but never asked
*"does this match what the agent set out to build?"* A typo-free, well-laid-out artifact
showing the **wrong content** would PASS. This release closes that gap.

- **`Brief`** (the *intended product*) as a first-class input, from any of three sources
  (combinable): a free-text **brief** the eyes turn into a checklist
  (`backend.complete_text`), an **explicit checklist** (`--expect "must: …"`, deterministic),
  and a **reference image** the render should match (passed as a second image to the vision
  backend; structural-diff-friendly).
- **New `intent_mismatch` issue kind** + a **`Report.conformance`** summary grading every
  requirement `satisfied | violated | uncertain`, with a score and `matches_intent()`.
- **Verdict gating**: a violated `must` ⇒ FAIL; a violated `should` / uncertain `must` ⇒
  WARN — so the loop now terminates on *"matches intent"*, not merely *"defect-free"*.
- **Deterministic OCR text-presence grading** for quoted-text requirements — model-
  independent ground truth, and the only conformance signal the offline `local` backend
  trusts (it reports `uncertain` for non-text claims rather than a false PASS).
- **Generative loop** (`GenerativeLoopSession`, `agentvision generate`): for AI-generated
  artifacts (diffusion infographics, etc.) the "fix" is a better **prompt** — generate →
  perceive → grade-vs-intent → **refine prompt** → regenerate, until it matches the brief.
  The image generator is a **pluggable hook** you supply (`module:function`); AgentVision
  never bundles an image-gen dependency.
- Surfaced everywhere: CLI (`conform`, `generate`, and `--brief/--expect/--reference` on
  `analyze`/`loop`), MCP (`conform_artifact`, intent params on `analyze_artifact`/
  `start_loop`), and REST (`POST /conform`, intent fields on `/analyze` + `/loop`).
- `complete_text` added to every vision backend (text-only completion) for checklist
  extraction and prompt refinement; `local` returns `""` (honest: no semantic intent).

### Added — eyes→brain handoff path
The eyes are only the *afferent* half of perception; the **brain** (your agent's reasoning/
memory/planning) decides and acts. AgentVision now names that boundary and gives any brain a
clean, provider-agnostic handoff — it perceives and hands off, it does not decide for you.

- **`Handoff`** signal (`report.to_handoff()`): a distilled `{perceived, next_action
  (done|revise|review), matches_intent, summary, todo[], open_questions[]}` an agent acts on
  directly — defects + unmet `must`s as a prioritized work-list, and what perception couldn't
  confirm surfaced (never dropped) as open questions.
- Surfaced as CLI `--handoff` (on `analyze`/`conform`/`check`), the MCP `perceive_handoff`
  tool, REST `POST /handoff`, a `handoff` on every loop `IterationResult`, and a `handoff.json`
  written per loop iteration.
- New doc [docs/handoff.md](docs/handoff.md): the anatomy, the contract, and a
  provider-agnostic recipe for wiring perception into any agent loop or memory/brain system —
  with [Verel](https://github.com/amitpatole/verel) as the reference brain (it consumes
  AgentVision as its Eyes organ and compounds verified perceptions, incl. intent conformance,
  into memory).

### Fixed
- The backend-fallback notice issue now carries `detail={"fallback": true}`, so a consuming
  brain's sense adapter can keep it for provenance yet exclude it from gating (this honors the
  contract Verel's `verel.senses.sight` already documents and tests).

## [0.2.0] — 2026-06-18

### Added
- **Spelling / garbled-text detection** (new `typo` issue kind): an offline, deterministic
  OCR + dictionary check flags misspellings and garbled text (e.g. diffusion-mangled labels,
  typo'd UI copy) with precise boxes; the vision-LLM prompt also now explicitly checks for
  typos, duplicated, and nonsensical text. Requires Tesseract + `pyspellchecker` (in the
  `[ocr]` extra). Note: a *weak* vision model may miss typos a strong one (or the OCR check)
  catches — run the OCR check for a deterministic guarantee.
- **Ollama vision backend** (`--backend ollama`): use any multimodal Ollama model (local or
  Ollama Cloud) as the perception backend — the OSS/self-hosted option. Default
  `gemma3:27b`; key from `OLLAMA_API_KEY` or `~/.config/ollama/key`; base URL configurable.
- **Key-file fallback** for every backend: keys resolve from the conventional env var or
  `~/.config/<Provider>/key` (`Anthropic`, `OpenAI`, `Google`, `ollama`).
- Launch infographic in `media/` — including one **designed by `qwen3-coder:480b` and
  self-corrected through AgentVision's own render→see→fix loop** (vision via `gemma3:27b`).

## [0.1.0] — 2026-06-18

Initial release — "Eyes for AI Agents".

### Added
- **Core engine** (async): `render`, `analyze`, `check`, `diff`, `contact_sheet`,
  baselines/`regress`, and the `LoopSession` visual feedback loop.
- **Trustworthy grounding**: DOM geometry, computed-style WCAG contrast (with a
  `confidence` flag), broken-image + console/network/4xx capture, and a blank-render
  check. Coordinates normalized to image pixels (scroll-offset aware).
- **Renderers**: async Playwright (HTML/URL/SVG) with SSRF + `file://` guards and a hard
  render timeout; PDF (pdf2image) and image renderers.
- **Vision backends**: `local` (offline, no key), `anthropic` (default), `openai`,
  `gemini`, behind one pluggable interface with per-provider schema adapters and explicit
  fallback semantics.
- **OCR**: Tesseract backend (text + word boxes).
- **Adapters**: CLI (`agentvision`), MCP server (`agentvision-mcp`), REST service
  (`agentvision-serve`), a Claude Code Skill, and integration recipes (Cursor, Aider,
  generic agent contract).
- **Loop semantics**: progress/stuck detection by issue-set stability (not SSIM).
- `agentvision doctor` (real Chromium launch + `ldd` missing-lib enumeration) and a
  zero-key `agentvision demo`.
- Docs, examples, Dockerfile, and CI.
