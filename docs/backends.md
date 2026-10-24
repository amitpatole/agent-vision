# Vision backends

AgentVision's analysis backend is pluggable. The same `Report` contract is produced by
each, via per-provider schema adapters.

| Backend | Install | Key | Notes |
|---|---|---|---|
| `local` | (base) | none | Structural/heuristic only. No egress. Always available. |
| `anthropic` | `[anthropic]` | `ANTHROPIC_API_KEY` | Default. Model `claude-haiku-4-5`. |
| `openai` | `[openai]` | `OPENAI_API_KEY` | Strict `json_schema` structured output. Default `gpt-5.4-mini`. |
| `gemini` | `[gemini]` | `GOOGLE_API_KEY` | `response_schema` structured output. Default `gemini-3.5-flash-lite`. |
| `ollama` | `[openai]` | cloud: `OLLAMA_API_KEY` · self-hosted: none | OSS multimodal models via Ollama (self-hosted **or** Ollama Cloud). Default `kimi-k2.7-code`. Tolerant JSON parsing; an unparseable or cut-off reply grades WARN, never PASS. |

### Ollama

Use any multimodal Ollama model as the vision backend. Two deployment shapes, chosen by
`AGENTVISION_OLLAMA_BASE_URL`:

**Self-hosted (no key, no egress off your network).** Point the base URL at your own Ollama
server. No API key is needed:

```bash
export AGENTVISION_OLLAMA_BASE_URL=http://localhost:11434/v1   # or a LAN GPU box
export AGENTVISION_OLLAMA_MODEL=qwen2.5vl:7b                    # any vision-capable model
agentvision analyze page.html --backend ollama
```

**Ollama Cloud.** The default base URL is `https://ollama.com/v1`, which needs a key from
`OLLAMA_API_KEY` or `~/.config/ollama/key`:

```bash
export OLLAMA_API_KEY=...
agentvision analyze page.html --backend ollama
```

**The cloud key only ever goes to `https://ollama.com`.** The key from `OLLAMA_API_KEY` or the
key file is never sent to any other host, and never over plain `http`. Lookalike hosts such as
`ollama.com.evil.net` count as other hosts. If you put an auth proxy in front of a self-hosted
server, give it its own key in `AGENTVISION_OLLAMA_SELF_HOSTED_KEY`.

**Malformed replies fail closed.** Small local models sometimes reply with prose instead of
JSON. Such a reply adds a WARNING issue ("semantic grade is missing"), so it can never grade as
a clean PASS. The [pilot benchmark](pilot.md#benchmark) reports how often each model does this.

**Thinking models need headroom.** Many cloud models reason before they answer, and the
reasoning comes out of the same completion budget. Each call allows 8192 tokens
(`AGENTVISION_OLLAMA_MAX_TOKENS`). At the old fixed 2048, `kimi-k2.7-code` was cut off mid-JSON
on busy pages. A reply that stops at the limit adds a WARNING that says so and names the
setting to raise.

**Which model.** On Ollama Cloud the default `kimi-k2.7-code` flagged every defect and passed
every clean page over three benchmark runs. For a self-hosted 12 GB GPU, `qwen2.5vl:7b` is the
measured pick. Both are in the [pilot guide](pilot.md#benchmark), along with every other
vision model on the Ollama Cloud subscription.

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
export AGENTVISION_OPENAI_MODEL=gpt-5.5
export AGENTVISION_GEMINI_MODEL=gemini-3.5-flash-lite
```

The OpenAI and Gemini defaults are the models that led their provider in the
[pilot benchmark](pilot.md#hosted-providers) over three runs. Each call allows 8192 completion
tokens (`AGENTVISION_OPENAI_MAX_TOKENS`, `AGENTVISION_GEMINI_MAX_TOKENS`), because newer models
reason before they answer and that comes out of the same budget. A reply cut off at the limit
raises an error naming the setting to raise.

The Anthropic default is **Haiku** because `analyze` runs frequently inside the loop;
upgrade to Sonnet/Opus for harder visual judgments.

!!! note "Intent-checklist grading wants a stronger vision model"
    Small, cheap models are tuned for the fast in-loop
    `analyze` pass, and on a **detailed intent checklist** they can produce *self-contradictory*
    findings on a clean artifact — passing "no clipped text" and then flagging clipped text on the
    same image, or calling a plainly light background "not light." When you grade against a
    `--brief`/`--expect` checklist (conformance), prefer a stronger model
    (`AGENTVISION_OPENAI_MODEL=gpt-5.5`, `AGENTVISION_ANTHROPIC_MODEL=claude-sonnet-4-6`). AgentVision
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
