# CLI reference

Every command supports `--help`. Most accept `--json` (full report) or `--handoff` (distilled signal); add `--quiet` for **machine mode** — only JSON on stdout, logs on stderr, with stable exit codes:

| Exit code | Meaning |
|---|---|
| `0` | `pass` or `warn` |
| `2` | `fail` |
| `3` | error (machine mode) |

```bash
agentvision <command> --help     # full flags for any command
```

## `agentvision demo`

Run the 60-second demo: broken page -> FAIL -> loop to fixed -> PASS (no API key).

## `agentvision analyze`

Render and analyze an artifact with a vision backend (+ DOM/CV grounding).

**Arguments:** `SOURCE`

| Option | Description | Default |
|---|---|---|
| `--backend` | anthropic\|openai\|gemini\|local |  |
| `--instructions` | Task context for the vision model. |  |
| `--expected` | What the artifact was supposed to look like. |  |
| `--brief` | The intended product — graded for intent match. |  |
| `--expect` | A required visual claim (repeatable; prefix 'should:'/'nice:'). |  |
| `--reference` | Reference/mockup image the render should match. |  |
| `--source-type` | auto\|html\|file\|url\|svg\|pdf\|image | `auto` |
| `--viewport` | WxH, e.g. 1280x800 |  |
| `--full-page` |  |  |
| `--wait-for` | CSS selector to wait for before capture (for client-rendered data). |  |
| `--settle-ms` | Quiet wait (ms) after load so client-rendered data can populate. |  |
| `--freeze` | Pause animations + rAF before capture (default on; needed for canvas/WebGL). |  |
| `--nav-wait` | load\|domcontentloaded\|networkidle (default load; networkidle is bounded). |  |
| `--render-timeout` | Max render seconds. |  |
| `--allow-local` | Allow localhost / LAN URLs. |  |
| `--no-ocr` | Disable OCR grounding. |  |
| `--json` | Emit JSON. |  |
| `--handoff` | Emit the eyes→brain handoff signal (JSON) for an agent/brain to act on. |  |
| `--quiet` | Machine mode: only JSON on stdout, logs on stderr, stable exit codes (0 pass/warn, 2 fail, 3 error). |  |

## `agentvision conform`

Grade an artifact against intent — does it match what you set out to build?

**Arguments:** `SOURCE`

| Option | Description | Default |
|---|---|---|
| `--brief` | Free-text description of the intended product. |  |
| `--expect` | A required visual claim (repeatable; prefix 'should:'/'nice:'). |  |
| `--reference` | Reference/mockup image the render should match. |  |
| `--backend` | anthropic\|openai\|gemini\|ollama\|local |  |
| `--source-type` |  | `auto` |
| `--viewport` | WxH |  |
| `--full-page` |  |  |
| `--wait-for` | CSS selector to wait for first. |  |
| `--settle-ms` | Quiet wait (ms) after load. |  |
| `--freeze` | Pause animations + rAF. |  |
| `--nav-wait` | load\|domcontentloaded\|networkidle. |  |
| `--render-timeout` | Max render seconds. |  |
| `--allow-local` | Allow localhost / LAN URLs. |  |
| `--json` |  |  |
| `--handoff` | Emit the eyes→brain handoff signal (JSON) for an agent/brain to act on. |  |
| `--quiet` | Machine mode: only JSON on stdout. |  |

## `agentvision check`

Classic DOM/CV checks only — no LLM, no API key, no egress.

**Arguments:** `SOURCE`

| Option | Description | Default |
|---|---|---|
| `--source-type` |  | `auto` |
| `--viewport` | WxH |  |
| `--full-page` |  | on |
| `--wait-for` | CSS selector to wait for first. |  |
| `--settle-ms` | Quiet wait (ms) after load. |  |
| `--freeze` | Pause animations + rAF. |  |
| `--nav-wait` | load\|domcontentloaded\|networkidle. |  |
| `--render-timeout` | Max render seconds. |  |
| `--allow-local` | Allow localhost / LAN URLs. |  |
| `--json` |  |  |
| `--handoff` | Emit the eyes→brain handoff signal (JSON) for an agent/brain to act on. |  |
| `--quiet` | Machine mode: only JSON on stdout. |  |

## `agentvision watch`

Watch an artifact over time — verify playback / loading / liveness, not just a glance.

**Arguments:** `SOURCE`

| Option | Description | Default |
|---|---|---|
| `--backend` | Vision backend for the time-aware pass. |  |
| `--frames` | How many frames to sample. |  |
| `--interval-ms` | Delay between frames (ms). |  |
| `--brief` | Intended behavior (e.g. 'the video plays'). |  |
| `--expect` | A required behavior (repeatable). |  |
| `--no-vision` | Deterministic signals only. |  |
| `--allow-local` | Allow localhost / LAN URLs. |  |
| `--nav-wait` | load\|domcontentloaded\|networkidle. |  |
| `--render-timeout` | Max seconds. |  |
| `--json` |  |  |
| `--handoff` | Emit the eyes→brain handoff signal. |  |
| `--quiet` | Machine mode: only JSON on stdout. |  |

## `agentvision loop`

Run the visual feedback loop (re-renders the source up to --max-iter times).

**Arguments:** `SOURCE`

| Option | Description | Default |
|---|---|---|
| `--backend` |  |  |
| `--max-iter` |  | `3` |
| `--instructions` |  |  |
| `--brief` | The intended product — graded for intent match. |  |
| `--expect` | A required visual claim (repeatable; prefix 'should:'/'nice:'). |  |
| `--reference` | Reference/mockup image the render should match. |  |
| `--nav-wait` | load\|domcontentloaded\|networkidle. |  |
| `--settle-ms` | Quiet wait (ms) after load. |  |
| `--freeze` | Pause animations + rAF. |  |
| `--render-timeout` | Max render seconds. |  |
| `--allow-local` | Allow localhost / LAN URLs. |  |
| `--json` |  |  |

## `agentvision generate`

Generative loop: generate → see → grade vs intent → refine prompt → regenerate.

| Option | Description | Default |
|---|---|---|
| `--generator` | Generator hook as 'module:function' — a callable (prompt:str)->image_path. |  |
| `--brief` | Free-text description of what to generate. |  |
| `--expect` | A required visual claim (repeatable; prefix 'should:'/'nice:'). |  |
| `--reference` | Reference/mockup image the output should match. |  |
| `--backend` | Vision backend used to perceive + refine. |  |
| `--max-iter` |  | `4` |
| `-o`, `--out` |  | `agentvision-generated.png` |
| `--json` |  |  |

## `agentvision render`

Render an artifact to a PNG.

**Arguments:** `SOURCE`

| Option | Description | Default |
|---|---|---|
| `-o`, `--out` |  | `agentvision-render.png` |
| `--source-type` |  | `auto` |
| `--viewport` | WxH |  |
| `--full-page` |  | on |
| `--wait-for` | CSS selector to wait for first. |  |
| `--settle-ms` | Quiet wait (ms) after load. |  |
| `--freeze` | Pause animations + rAF. |  |
| `--nav-wait` | load\|domcontentloaded\|networkidle. |  |
| `--render-timeout` | Max render seconds. |  |
| `--allow-local` | Allow localhost / LAN URLs. |  |

## `agentvision diff`

Compare two images (SSIM + annotated diff).

**Arguments:** `BASELINE`, `CANDIDATE`

| Option | Description | Default |
|---|---|---|
| `-o`, `--out` |  | `agentvision-diff.png` |
| `--threshold` | Min SSIM to pass. | `0.98` |
| `--json` |  |  |

## `agentvision ocr`

Extract text (+ word boxes) from an artifact via Tesseract.

**Arguments:** `SOURCE`

| Option | Description | Default |
|---|---|---|
| `--source-type` |  | `auto` |
| `--json` |  |  |

## `agentvision sheet`

Render a responsive contact sheet across breakpoints.

**Arguments:** `SOURCE`

| Option | Description | Default |
|---|---|---|
| `--breakpoints` | Comma-separated widths. | `375,768,1280,1920` |
| `-o`, `--out` |  | `agentvision-sheet.png` |

## `agentvision baseline`

Capture and store a named baseline for regression.

**Arguments:** `SOURCE`

| Option | Description | Default |
|---|---|---|
| `--name` | Baseline name. |  |
| `--source-type` |  | `auto` |

## `agentvision regress`

Render a source and compare it to a named baseline.

**Arguments:** `SOURCE`

| Option | Description | Default |
|---|---|---|
| `--name` |  |  |
| `-o`, `--out` |  | `agentvision-regress.png` |
| `--threshold` |  | `0.98` |
| `--json` |  |  |

## `agentvision doctor`

Diagnose rendering + backend readiness.

| Option | Description | Default |
|---|---|---|
| `--fix` | Install the Chromium browser. |  |

## `agentvision serve`

Start the REST service.

| Option | Description | Default |
|---|---|---|
| `--host` | Interface to bind | `127.0.0.1` |
| `--port` | Port to listen on | `8000` |

**Auth token.** Loopback (`127.0.0.1`) is zero-config. Binding any other host **requires** a
token — the server refuses to start without one — which is a secret *you* generate (there's no
default):

```bash
export AGENTVISION_API_TOKEN=$(openssl rand -hex 32)   # any high-entropy string
agentvision serve --host 0.0.0.0 --port 8000
```

Clients send it as `Authorization: Bearer <token>` (compared in constant time). See
[Swarms & scaling](scaling.md) for multi-agent deployment and [Security](security.md) for the
full model.

## `agentvision version`

Print the AgentVision version.

