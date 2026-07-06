# Vision backends

AgentVision's analysis backend is pluggable. The same `Report` contract is produced by
each, via per-provider schema adapters.

| Backend | Install | Key | Notes |
|---|---|---|---|
| `local` | (base) | none | Structural/heuristic only. No egress. Always available. |
| `anthropic` | `[anthropic]` | `ANTHROPIC_API_KEY` | Default. Model `claude-haiku-4-5`. |
| `openai` | `[openai]` | `OPENAI_API_KEY` | Strict `json_schema` structured output. |
| `gemini` | `[gemini]` | `GOOGLE_API_KEY` | `response_schema` structured output. |
| `ollama` | `[openai]` | `OLLAMA_API_KEY` | OSS multimodal models via Ollama (local **or** Ollama Cloud). Default `gemma3:27b`. Tolerant JSON parsing. |

### Ollama

Use any multimodal Ollama model as the vision backend — great for OSS / self-hosted setups
and for Ollama Cloud (no local GPU needed):

```bash
export OLLAMA_API_KEY=...                       # or put the key in ~/.config/ollama/key
export AGENTVISION_OLLAMA_MODEL=gemma3:27b      # any multimodal model
export AGENTVISION_OLLAMA_BASE_URL=https://ollama.com/v1   # default; or http://localhost:11434/v1
agentvision analyze page.html --backend ollama
```

The key resolves from `OLLAMA_API_KEY`, falling back to `~/.config/ollama/key`.

## Selection

Precedence: explicit `--backend` → `AGENTVISION_VISION_BACKEND` → first available cloud
backend → `local`.

```bash
agentvision analyze page.html --backend openai
export AGENTVISION_VISION_BACKEND=gemini
```

## Models

Defaults are config-overridable:

```bash
export AGENTVISION_ANTHROPIC_MODEL=claude-sonnet-4-6   # or claude-opus-4-8
export AGENTVISION_OPENAI_MODEL=gpt-4o
export AGENTVISION_GEMINI_MODEL=gemini-2.0-flash
```

The Anthropic default is **Haiku** because `analyze` runs frequently inside the loop;
upgrade to Sonnet/Opus for harder visual judgments.

!!! note "Intent-checklist grading wants a stronger vision model"
    The small/cheap default models (e.g. OpenAI `gpt-4o-mini`) are tuned for the fast in-loop
    `analyze` pass, and on a **detailed intent checklist** they can produce *self-contradictory*
    findings on a clean artifact — passing "no clipped text" and then flagging clipped text on the
    same image, or calling a plainly light background "not light." When you grade against a
    `--brief`/`--expect` checklist (conformance), prefer a stronger model
    (`AGENTVISION_OPENAI_MODEL=gpt-4o`, `AGENTVISION_ANTHROPIC_MODEL=claude-sonnet-4-6`). AgentVision
    already suppresses a vision "missing"/intent claim that DOM/OCR **proves** is present, so the
    deterministic ground truth overrules a weak model where it can — but a purely visual judgment
    is only as reliable as the model making it.

## Fallback semantics

- **Missing key/dependency** for a requested cloud backend → falls back to `local` and
  adds a `warning` issue to the report (never silent).
- **Invalid key / quota exceeded** at call time → raises an error (no silent fallback) so
  you notice and fix it.

## The local backend (honest scope)

`local` performs **no semantic critique**. It packages grounded DOM/CV findings (contrast,
overflow, broken images, console errors, blank renders). Use it for fast/offline/CI runs
and as the privacy-preserving option; use an LLM backend when you need judgment about
whether the result actually looks right.

## Capabilities matrix

`Report.capabilities` lists which `IssueKind`s the producing backend can emit. The `local`
backend emits `contrast, overflow, broken_image, error_text, blank, overlap, other` — where
`contrast` includes text over a **non-solid background** (a `<canvas>` / raster map tile /
gradient / image), graded from the rendered pixels (worst-case sampling) rather than a
computed-style guess, **and** text painted *into* a `<canvas>` with no DOM node (via OCR +
pixels, advisory). For PowerPoint sources it also detects clipped/truncated text, off-slide
shapes, and overlapping boxes **offline** (no key, no egress; see [the `check`
command](cli.md#offline-powerpoint-slide-inspection)).
LLM backends can emit any kind (layout, missing_element, overlap, clipped, …).
