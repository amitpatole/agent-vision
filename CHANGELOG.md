# Changelog

All notable changes to AgentVision are documented here.

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
