# Changelog

All notable changes to AgentVision are documented here.

## [0.10.0] — 2026-06-29

### Added — ephemeral `--no-cache` mode (confidential inputs)

Render/analyze without persisting anything to the on-disk cache: a throwaway temp dir
(0700, wiped on exit) holds all renders/sessions, so a confidential file is never written
to `~/.cache/agentvision`. Available as the `--no-cache` flag on source commands (analyze,
conform, check, render, ocr, loop, sheet, watch), `AGENTVISION_EPHEMERAL=true`, or the
`agentvision.ephemeral_cache(settings)` context manager for library use.

### Added — offline PPTX slide inspection (deterministic, no LLM, no egress)

PowerPoint decks were rasterized to a flat image, so offline AgentVision was blind to
slide-structure defects. New `core/checks/slides.py` reads the OOXML for *where* text and
tables are, then reads the *rendered pixels* in those regions:

- **Unreadable text** — bimodal (Otsu) pixel contrast inside each text box catches
  dark-on-dark / stacked-background cases that XML colors get wrong (`< 3:1` → error,
  `3–4.5:1` → warning). Runs in `agentvision check` (no key, no upload).
- **Off-slide / clipped** content and **overlapping** text boxes (OOXML geometry).

Honest limits offline: text over a *photo* and render-time table overflow still need the
vision backend on the slide image (egress); this is the no-key floor. Confidential decks
can be inspected fully locally.

### Security — fix path traversal (CodeQL `py/path-injection`, 5 HIGH)

Untrusted data (REST URL path params, agent-supplied source specs) could widen a filesystem
path beyond its intended directory. New `agentvision.pathsafe` confines every sink via
`os.path.commonpath`: `GET /baseline/{name}` and `/artifacts/{id}` validate the segment and
fail closed to 404; baseline writes validate+confine the name and copy source; `sources.py`
file:// and bare-path reads resolve under an optional `file_root` (default: unrestricted for
trusted CLI). Regression tests per sink; e.g. `GET /baseline/..%2f..%2fetc%2fpasswd` → 404.

### Added — clipped/truncated-text check (deterministic, no LLM)

A new structural check (`IssueKind.CLIPPED`) catches text that is **cut off** — the class of
defect a real-world dogfood (a skill-radar SVG chart) showed the eyes were missing:

- **SVG `<text>` clipped by its viewport** (ERROR/high): a label whose rendered rect extends
  beyond the `<svg>` it lives in is cut off (the outermost SVG clips by default). Catches both
  "truncated mid-word" (overflows the right edge) and a leading glyph at negative x (clipped on
  the left). Detected in-page via `getBoundingClientRect` vs the viewport element — no LLM, no
  egress, precise and DOM-grounded.
- **DOM text truncated by a hard clip** (WARNING/medium): an element whose content overflows its
  box under `overflow:hidden/clip` with **no ellipsis** (an ellipsis is treated as intentional).
- **Bug fix:** an element positioned partly off-screen (e.g. SVG text at negative x) previously
  crashed `check` on the contract's non-negative `BBox`; geometry is now clamped to the visible
  region in all converters.
- New `ClippedText` render signal + `clipped` added to the local backend's capabilities.
  Regression tests pin the check, the bbox clamp, and an end-to-end render of an
  overflowing-`viewBox` SVG. 159 tests pass; ruff clean.

### Fixed
- `agentvision conform` crashed (`AttributeError: 'str' object has no attribute 'value'`) after
  the 0.9.0 agentsensory migration — `ClaimResult.source` is a plain `str` now. Renders cleanly;
  regression-pinned.

### Docs
- New front-door pages mirroring the Verel docs set: **Try it yourself**, **5-minute tutorial**,
  **Use cases**, **Real-world scenarios** (all with real captured output).
- New **Swarms & scaling** page — "eyes as a service" topologies, the stateless/stateful split,
  the in-process loop-session caveat + mitigations; `/loop/{id}/iterate` now fails loud on a
  cross-worker session miss. Foregrounded the multi-agent story in the README + index.
- Documented the REST **auth token** (generate/export/use) across scaling/examples/cli/config —
  it was referenced as `$TOKEN` but never explained.

## [0.9.1] — 2026-06-23 — version-string sync

0.9.0 shipped the agentsensory adoption but the code `__version__` still read `0.8.0`
(`pyproject`/package metadata were already correct).

- **Fix**: `agentvision.__version__` now reads `0.9.1`, matching `pyproject.toml` and the
  published wheel metadata.
- **Drift guard**: a new test pins `importlib.metadata.version("agentvision") == __version__`
  so the string can never silently fall out of sync with the release metadata again.
- No runtime/behavior change; the package is otherwise identical to 0.9.0. 151 tests pass;
  ruff + mypy clean.

## [0.9.0] — 2026-06-23 — built on the shared agentsensory contract

AgentVision is the **eyes** of the eyes/ears/brain trio, and this release makes that literal:
the verdict/report/intent models are no longer a bundled copy — they come from the shared
**`agentsensory`** contract (now on PyPI), so every organ speaks one `Report`/`Handoff` language.

- **Adopt `agentsensory>=0.1`** as the single source of truth for the contract. `Report`,
  `Issue`, `IssueKind`, `IssueSource`, `Severity`, `Confidence`, `Verdict`, `Brief`,
  `IntentClaim`, `Conformance`, `ClaimResult`, `Handoff`, `NextAction`, `BBox`, `Viewport`
  are now **re-exported** from `agentvision` — the public import surface is byte-for-byte
  identical, so existing `from agentvision import Report` code keeps working unchanged.
- **Why it matters**: a `Report` graded by the eyes drops straight onto the same verdict bus
  the brain (Verel) and the other senses consume — no per-organ translation, no contract drift.
  This is the eyes half of the trio standardizing on the shared sensing contract.
- Models that were AgentVision-local (`report.py`, `intent.py`, `handoff.py`, `geometry.py`)
  shrink to thin re-export shims over `agentsensory` (~354 lines of duplicated model code
  removed). Vision-specific grounding (bbox/span) is unchanged.
- Verel (eyes → brain) integration re-verified against the shared contract: `Report`
  round-trips and the sight-adapter suite passes. 151 tests pass; ruff + mypy clean.

## [0.8.0] — 2026-06-22 — Office & multi-page document support

Render and analyze **documents**, not just web pages and images.

- **Office / OpenDocument support**: `.docx .doc .pptx .ppt .xlsx .xls .odt .odp .ods .rtf`
  are converted to PDF via **LibreOffice headless** and rasterized like a native PDF. Point
  any command (`render/analyze/check/loop/…`) at one — detection is automatic.
- **Multi-page rendering**: the PDF renderer is generalized from first-page-only to **up to
  `document_max_pages` pages** (default 30). Every page is saved (`page_NNN.png`) and stacked
  into a single composite (`document.png`) that becomes the `primary` image, so the analyze
  pipeline's tiling sees the *whole* document/deck with no other changes. The composite is
  scaled to stay under the decompression-bomb pixel cap.
- **Hardened conversion** (LibreOffice on untrusted input): argv form (no shell), input passed
  as an absolute path so a `-`-leading filename can't become a flag, byte cap, isolated
  throwaway user profile per conversion (`--convert-to` doesn't run macros), and a hard
  timeout with process-group kill. **Gated off by default on the REST service**
  (`allow_office_render=False`).
- `agentvision doctor` now reports LibreOffice availability. New settings: `document_max_pages`,
  `document_max_page_px`, `document_raster_dpi`, `max_document_bytes`,
  `document_convert_timeout_s`, `soffice_path`, `allow_office_render`.
- Verel (eyes → brain) integration re-verified — `Report` contract unchanged; a live
  `perceive()` round-trips an Office document through the new path.
- +16 office tests (detection, gate, byte cap, missing-dep, argv hardening, multi-page
  composite, real `.docx`/`.rtf` e2e); 150 tests pass; ruff + mypy clean.

## [0.7.3] — 2026-06-22 — proxy load test, docs, CI

No runtime code changes (the package is identical to 0.7.2); this release bundles the
verification, documentation, and CI work that landed on top of the 0.7.x security series.

- **Proxy load/stress test**: 120 concurrent requests through the vetting proxy under a
  connection cap — asserts nothing hangs, every request gets a clean `200`/`503` (no resets),
  the cap holds, and the proxy keeps serving after the burst.
- **Docs**: new **Security** page on the docs site (threat model + the full hardening list:
  SSRF, vetting egress proxy / DNS-rebinding closure, renderer isolation, decompression-bomb
  caps, HTTP-service hardening, secret scrubbing) plus the egress-deny deployment backstop.
- **CI**: opt CI runners out of the Chromium OS sandbox via the documented
  `AGENTVISION_CHROMIUM_SANDBOX=false` trusted-environment escape hatch (bare GitHub runners
  have no usable user namespaces, and the renderer correctly fails closed there). The secure
  default (sandbox on, fail-closed) is unchanged for real users.
- Verel (eyes → brain) integration verified unchanged: `Report` contract intact, Verel's
  sight-adapter suite passes, and a live `perceive()` round-trips through the hardened renderer.
- 134 tests pass; ruff clean.

## [0.7.2] — 2026-06-22 — proxy hardening

- The vetting egress proxy now **bounds the work a page can drive through it**: a per-render
  cap on concurrent upstream connections (`proxy_max_connections`, default 64 → 503 over the
  cap) and an **idle timeout** on every proxied/tunnelled socket (`proxy_idle_timeout_s`,
  default 30s) so a slowloris / hung upstream can't pin connections.
- Added an end-to-end browser test of the full chain (browser → route guard → proxy →
  upstream): pins to the vetted IP with `Host` preserved, and **backstops a rebinding-fooled
  route guard** (proxy blocks the internal target even if the in-browser check was tricked).
- +4 proxy tests (cap, idle, 2 e2e); ruff + mypy clean; 133 tests pass.

## [0.7.1] — 2026-06-22 — DNS-rebinding closed (vetting egress proxy)

Follow-up to the 0.7.0 security release: the one documented residual (the DNS-rebinding
sub-millisecond race) is now closed.

- **Vetting egress proxy** (`agentvision/proxy.py`): Chromium launches with `--proxy-server`
  (+ `--proxy-bypass-list=<-loopback>`) pointing at a local proxy that resolves each host
  ONCE, vets the IP, and connects to that exact IP — for plain HTTP (absolute-form), HTTPS/WSS
  (CONNECT), and WS. Chromium never resolves a host itself, so there is no second lookup to
  rebind; the `Host` header / TLS SNI are preserved (the earlier IP-rewrite attempt couldn't).
  Runs only when SSRF protection is on (skipped under `--allow-local`).
- SECURITY.md updated; added a recommended network-level egress-deny deployment note (defense
  in depth) and verified the proxy pins + preserves Host + blocks internal (incl. CONNECT).
- +3 proxy regression tests; ruff + mypy clean; 129 tests pass.

## [0.7.0] — 2026-06-22 — security hardening release

A full audit → fix → verify → red-team pass across three surfaces (network/input, renderer
sandboxing, image/secret handling). Every fix ships with a regression test and was run as a
live exploit against the fixed code. See [SECURITY.md](SECURITY.md).

### Fixed — SSRF (the headline surface)
- The renderer route guard now **re-resolves every request's host at fetch time** (navigation,
  subresources, redirect targets) and intercepts **WebSocket** connections (`route_web_socket`)
  — previously only literal-IP hosts were checked and `ws://` wasn't covered, so attacker HTML
  could reach cloud metadata / LAN by hostname or WebSocket.
- One policy (`netguard.py`): blocks private/loopback/link-local/reserved/multicast/unspecified
  + **CGNAT (100.64/10)** + cloud-metadata; normalizes **IPv4-mapped IPv6**; fails closed.
- Non-`http(s)` schemes default-denied; `file://` allowed only for top-level navigation, never
  subresources; bare local-file sources gated (`allow_local_files`, off for the service).
- SSRF errors no longer disclose the resolved IP (oracle).

### Fixed — renderer isolation
- Chromium **OS sandbox ON by default** (`chromium_sandbox`); `--no-sandbox` only when
  explicitly disabled, with a loud failure instead of a silent unsandboxed downgrade.
- Viewport/`device_scale`/full-page capture clamped (OOM bound); downloads disabled; pop-ups
  closed; `watch` frames/interval clamped.

### Fixed — untrusted bytes
- Decompression-bomb guard (`imageguard.py`): byte + pixel caps before any decode at every
  attacker-reachable site; PIL bomb guard armed. PDF byte/size/timeout bounds; OCR timeout.

### Fixed — the HTTP service
- Token auth (constant-time); **refuses a non-loopback bind without `AGENTVISION_API_TOKEN`**;
  request-body cap (incl. chunked streams); concurrent-render semaphore; generic (non-leaky)
  errors; refuses local-file sources. (Also fixed FastAPI 422 from body models nested in
  `build_app`.)

### Fixed — secrets
- Value-based log scrubbing (resolved keys/token registered + redacted); no default/hardcoded
  secret anywhere.

### Changed defaults (action may be required)
- The Chromium sandbox is now ON — bare/CI hosts without user namespaces must containerize or
  set `AGENTVISION_CHROMIUM_SANDBOX=false`.
- `agentvision serve` refuses a non-loopback `--host` unless `AGENTVISION_API_TOKEN` is set.
- The REST service refuses local-file sources.

### Known residual
- A sub-millisecond **DNS-rebinding race** between the fetch-time check and Chromium's own
  connect is not fully closed (needs a vetting egress proxy). Run egress-restricted for a hard
  guarantee — see SECURITY.md.

## [0.6.1] — 2026-06-19

### Added — developer adoption (workflows + agents)
Frictionless on-ramps for the two places developers use AgentVision — their CI/dev workflow
and their agents. (No library code change; this release ships the tooling/docs so a pinned
`@v0.6.1` action ref and `pip install` line up.)

- **Reusable GitHub Action** (`action.yml`): one step installs AgentVision + Chromium and runs
  `check`/`analyze`/`conform`/`watch`, failing the build on a FAIL verdict. Inputs are passed
  via the environment (injection-safe).
- **pre-commit hooks** (`.pre-commit-hooks.yaml`): `agentvision-check` / `agentvision-analyze`
  as commit gates (with the Chromium-binary caveat documented).
- **Refreshed agent contract** (`integrations/agent-contract.md`) covering the full loop:
  check/analyze, `conform` (intent), `watch` (temporal), `--handoff`, `--quiet` + exit codes.
- **`docs/integrations.md`** reframed as *workflow + agents* with a new "In your CI / workflow"
  section (Action, pre-commit, raw CLI gate).

## [0.6.0] — 2026-06-19

### Added — temporal verification (`watch`): eyes that watch, not just glance
Everything before this was single-frame. But streaming correctness is *temporal* — does the
video actually play, does the buffering spinner clear, do captions appear, does the live tile
update, does a transition finish. `agentvision watch` samples a sequence of frames over time
and judges behavior across them. For streaming UIs, video players, live dashboards, and any
animated/canvas surface.

- **Deterministic, trustworthy signals** (no LLM): per-`<video>` playback read from the media
  element itself — `currentTime` advancing ⇒ playing; not advancing while unpaused ⇒ **stall/
  buffering** (error); `readyState`/`videoWidth` ⇒ has decoded frames; `textTracks` ⇒ captions
  present/active. Plus pixel **liveness** (is it changing?), **stabilization** (loading→loaded
  converged?), and **black/blank-frame** detection.
- **Time-aware vision pass**: frames are stitched into a labeled contact sheet (+ sent as
  full-res frames) with a temporal prompt, so the model judges playback/loading/transition.
- Returns a normal `Report` (flows through `--handoff` and any brain/Verel); the machine-
  readable temporal signal rides on the leading issue's `detail.temporal`. Findings reuse
  existing `IssueKind`s (tagged `temporal`) so the verdict-bus contract stays stable.
- Surfaced as CLI `agentvision watch` (`--frames`, `--interval-ms`, `--brief/--expect`,
  `--no-vision`, `--quiet`), MCP `watch_artifact`, REST `POST /watch`, and `agentvision.watch`.
- Config: `watch_frames` (5), `watch_interval_ms` (600). Static sources (image/PDF) degrade
  gracefully to single-frame `analyze`. See [docs/use-cases/streaming.md](docs/use-cases/streaming.md).

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

### Fixed / changed — live-dashboard field report
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
