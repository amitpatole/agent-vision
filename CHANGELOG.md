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

## [0.5.0] — 2026-06-19

### Added — full-coverage vision (the eyes see everything, from pixels alone)
Generalizes focused crops beyond DOM-known elements. The model is sent a *downscaled* whole
image for layout (to avoid the "lazy on a huge image" failure), which loses fine detail —
small text, a chart's data, a thumbnail. Now, whenever the rendered artifact is larger than
the model-friendly edge, AgentVision also attaches **full-resolution tiles covering it**, so
no region is lost to downscaling.

- **Pixel-based and source-agnostic** (`core/tiling.py`): operates on the rendered screenshot
  alone, with zero DOM dependency — so it works uniformly for HTML, a **flat image**, a
  **PDF page**, a `<canvas>`/WebGL surface, or an `<iframe>`. Anything the eyes can render is
  now fully visible to them, not just elements the DOM enumerates.
- Bounded and content-aware: near-uniform (blank) tiles are skipped; when there are more
  content tiles than `max_vision_tiles` (default 6) the most content-rich are kept. Tiles
  share the `extra_images` budget with the visual-region crops from 0.4.0.
- Applies to **any vision analyze** (not only intent grading), and is the better fix for the
  original "lazy/hallucinated on large/dense images" problem: overview + full detail.
- Config: `vision_full_coverage` (default on), `max_vision_tiles`.

## [0.4.0] — 2026-06-19

### Added — focused full-res crops for visual intent claims
The last residual from the field report (#10): a downscaled full page can't be judged for
*visual* content (is the chart actually plotting? is the canvas/scene rendered?). Now when a
brief mentions a visual (chart / canvas / 3D scene / image / …) and the page has matching
sizable elements, AgentVision sends the vision model **focused full-resolution crops** of
those regions alongside the (downscaled) whole page — real visual judgment, not just "is it
there?".

- Renderer reports visual element geometry (`RenderResult.visual_elements`); the analyzer
  crops the full-res screenshot to the largest matching regions (`max_visual_crops`, default 3)
  and attaches them via the new `AnalysisRequest.extra_images` (a general multi-image context
  path, supported by all cloud backends and downscaled per-crop to `vision_max_edge_px`).
- Gated by intent + relevance: only fires when grading a brief whose text/claims name a
  visual and the page actually has such an element, and only on a vision backend
  (`crop_visual_claims`, default on). No extra cost on text-only or no-key runs.

## [0.3.2] — 2026-06-19

### Fixed — v0.3.1 retest residuals (canvas/WebGL visual path)
Two residual findings from re-grading the live WebGL dashboard, both on the vision path for
**visual (non-text) elements**:

- **Freeze no longer blanks canvas/WebGL scenes that build inside `requestAnimationFrame`.**
  Freeze is now *canvas-aware*: CSS animations/transitions are still paused, but when a
  `<canvas>` is present rAF is left running and the renderer waits `canvas_settle_ms`
  (default 1500) so the scene draws before capture ("settle-then-freeze"). Heavy scenes can
  still raise `--settle-ms`. (Static pages keep the full rAF freeze.)
- **Vision "missing" claims about visual elements are overruled by the DOM.** The renderer
  reports sizable `canvas`/`svg`/`img`/`video` elements (`RenderResult.visual_tags`); a vision
  `missing_element`/`intent_mismatch` that names a visual (canvas, chart, 3D scene, image…)
  is suppressed when the matching element is actually present — so a downscaled/blurry full
  page no longer false-fails a chart or canvas that demonstrably exists.

## [0.3.1] — 2026-06-19

### Fixed / changed — live-dashboard field report (live-dashboard)
Hardening from grading a live, continuously-polling WebGL dashboard. The biggest wins:
don't default to `networkidle`, settle/freeze before capture, and never let a vision
"missing" claim survive when DOM/OCR proves the element is present.

- **`nav_wait` default is now `load`** (was `networkidle`). Polling/websocket pages never
  go idle and used to hang to `RenderTimeout`. When `networkidle` *is* requested it is now
  **bounded** (≤5s) and falls through instead of blocking. `--nav-wait` is a CLI flag.
- **Settle + freeze before capture.** A short post-load settle (`settle_ms`, default 400)
  lets client-rendered data populate (fixes false "blank/missing" on the shell-then-fill
  frame); `freeze_animations` (default on) pauses CSS animations + the `requestAnimationFrame`
  loop and the screenshot uses `animations="disabled"`, so canvas/WebGL/animation-heavy pages
  (incl. **`--full-page`**) capture deterministically instead of timing out. `--settle-ms`,
  `--freeze/--no-freeze`, and `--wait-for <selector>` are CLI flags.
- **Vision claims cross-checked against DOM/OCR ground truth.** An advisory vision
  `missing_element` / `intent_mismatch` finding is suppressed when the quoted element text is
  actually present in the DOM/OCR — killing the false-fail class entirely.
- **Intent text claims grade against DOM *and* OCR**, so `--expect 'must: "…"'` is
  deterministic even with no OCR/no key (the text is read from the DOM).
- **Oversized screenshots are downscaled** before the vision LLM (`vision_max_edge_px`,
  default 2000) — large/dense images made models return lazy/generic critiques.
- **`--allow-local`** CLI flag for localhost / LAN dev servers (clearer than the env var),
  and the `UnsafeSourceError` now names it.
- **`--quiet` machine mode**: only the JSON object on stdout (logs on stderr), errors as a
  JSON `{"error": …}`, stable exit codes (0 pass/warn, 2 fail, 3 error).
- **Default `render_timeout_s` raised to 60s** and exposed as `--render-timeout`.

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
