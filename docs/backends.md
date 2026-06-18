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
backend emits `contrast, overflow, broken_image, error_text, blank, other`; LLM backends
can emit any kind (layout, missing_element, overlap, clipped, …).
