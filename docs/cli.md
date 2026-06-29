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

!!! tip "Confidential inputs — `--no-cache`"
    Add `--no-cache` to any source command (`analyze`, `conform`, `check`, `render`, `ocr`,
    `loop`, `watch`, `sheet`) to render into a throwaway temp dir that's **wiped when the command
    exits** — nothing is written to `~/.cache/agentvision`. Use it for confidential or sensitive
    artifacts. Equivalent to `AGENTVISION_EPHEMERAL=true`, or the `ephemeral_cache()` context
    manager in the [Python API](api.md).

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
| `--no-cache` | Ephemeral: render in a throwaway temp dir wiped on exit — nothing persists to the on-disk cache (use for confidential inputs). |  |
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
| `--no-cache` | Ephemeral: throwaway temp dir wiped on exit; nothing persists to the cache (confidential inputs). |  |
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

Classic DOM/CV checks only — no LLM, no API key, no egress. For a `.pptx` source this also
runs the **offline slide inspector** (contrast, clipped/truncated text, off-slide and
overlapping shapes — see below).

**Arguments:** `SOURCE`

| Option | Description | Default |
|---|---|---|
| `--source-type` |  | `auto` |
| `--no-cache` | Ephemeral: throwaway temp dir wiped on exit; nothing persists to the cache (confidential inputs). |  |
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

### Offline PowerPoint slide inspection

When the source is a `.pptx`, `check` adds a **fully offline** structural pass over the deck —
no API key, no egress — on top of the per-page raster checks. It parses the slide geometry and
the rendered pixels of each slide to catch problems that are easy to ship and hard to spot:

- **Unreadable text** — low text-to-background contrast (e.g. dark-on-dark), measured as a WCAG
  contrast ratio on the **rendered** pixels (so it catches stacked/photo backgrounds, not just
  the declared theme color). `< 3.0` → error, `3.0–4.5` → warning.
- **Clipped / truncated text** — text that overflows its shape's box.
- **Off-slide shapes** — content placed partly or wholly outside the slide bounds.
- **Overlapping shapes** — text boxes that collide.

Each finding is tagged `[slide N]` so you know exactly which slide to open:

```bash
agentvision check deck.pptx --quiet            # offline; exit 2 on FAIL
agentvision check confidential-deck.pptx --no-cache   # + never touch the on-disk cache
```

!!! note "What offline can and can't see"
    The slide inspector is deterministic and key-free, so it's safe for confidential decks. It
    reads structure + rendered pixels; it does **not** make a semantic judgment ("does this
    slide make sense?"). For that, add a vision backend (`analyze`/`conform`) — which sends the
    rendered slide to a provider, so don't use it on confidential material.

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
| `--no-cache` | Ephemeral: throwaway temp dir wiped on exit; nothing persists to the cache (confidential inputs). |  |
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
| `--no-cache` | Ephemeral: throwaway temp dir wiped on exit; nothing persists to the cache (confidential inputs). |  |
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
| `--no-cache` | Ephemeral: throwaway temp dir wiped on exit; nothing persists to the cache (confidential inputs). |  |

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
| `--no-cache` | Ephemeral: throwaway temp dir wiped on exit; nothing persists to the cache (confidential inputs). |  |
| `--json` |  |  |

## `agentvision sheet`

Render a responsive contact sheet across breakpoints.

**Arguments:** `SOURCE`

| Option | Description | Default |
|---|---|---|
| `--breakpoints` | Comma-separated widths. | `375,768,1280,1920` |
| `-o`, `--out` |  | `agentvision-sheet.png` |
| `--no-cache` | Ephemeral: throwaway temp dir wiped on exit; nothing persists to the cache (confidential inputs). |  |

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

