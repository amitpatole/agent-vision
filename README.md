# AgentVision — Eyes for AI Agents 👁️

> Coding agents are **blind**. They write a UI, a chart, an SVG, a PDF — and never *see*
> the rendered result. They reason from source code and stdout, then declare success while
> the button overflows, the legend is clipped, the contrast fails, or an image 404s.
> **AgentVision gives agents eyes.**

AgentVision is a provider-agnostic framework that closes the visual feedback loop for AI
coding agents:

```
render → perceive → report → (agent fixes) → re-render → diff
```

It is **not** human-reviewed visual regression (Percy/Applitools/Argos) and **not** browser
automation (browser-use/Playwright). It is a **machine-graded visual critique loop an agent
consumes to self-correct before claiming done** — with a verdict (`pass`/`warn`/`fail`) and
actionable, coordinate-grounded issues.

## The 60-second pitch

```bash
pip install "agentvision[render]"
playwright install chromium     # see `agentvision doctor` if Chromium won't launch
agentvision demo                # no API key required
```

`agentvision demo` renders a deliberately broken page, prints a **FAIL** report (overflow +
low-contrast + a 404 image — all DOM/CV-grounded, no LLM key needed), then loops against the
fixed version and prints *"what changed: 3 issues resolved → PASS."* That command *is* the
product.

## What makes it trustworthy

Findings are grounded in sources we can actually trust:

- **DOM geometry** (`getBoundingClientRect` + scroll offset) — precise element boxes.
- **Computed-style contrast** (`getComputedStyle`) — real WCAG ratios, with a `confidence`
  flag (it degrades honestly over gradients/images/pseudo-elements rather than lying).
- **OCR word boxes** (Tesseract) — precise text locations.
- **Console / network / 4xx capture** — the #1 "looks fine in code, broken live" cause.

A vision LLM (Claude/OpenAI/Gemini) adds semantic critique on top. Its pixel boxes are
treated as **advisory** (`bbox_precise: false`), never marketed as pixel-accurate.

## Many faces, one core

| Surface | Who it's for |
|---|---|
| **Library** (`import agentvision`) | Python apps, custom harnesses |
| **CLI** (`agentvision …`) | Any agent that can run a shell command; CI |
| **Claude Code Skill** | Claude agents — auto-invokes the loop *before claiming done* |
| **MCP server** (`agentvision-mcp`) | Cursor, Claude, any MCP-capable host |
| **REST service** (`agentvision-serve`) | Non-MCP / networked / CI agents |
| **Integration recipes** | Cursor rules, Aider, generic "agent contract" |

> ⚠️ "Provider-agnostic" describes the **API surface**, not behavior. The framework can't
> *force* a non-Claude agent into the loop — it gives every agent the *means*. The Claude
> Code Skill is the one surface that makes an agent use it proactively; MCP is the
> first-class cross-host path; the recipes cover the rest.

## Vision backends

Pluggable and selectable via `--backend` / `AGENTVISION_VISION_BACKEND`:

- **`anthropic`** (default model `claude-haiku-4-5`, upgradable to Sonnet/Opus)
- **`openai`**, **`gemini`**
- **`local`** — CV/OCR heuristics only, **no API key, no egress** (great for CI / air-gapped)

## Install

```bash
pip install "agentvision[all]"          # everything
pip install "agentvision[render]"       # just rendering + the no-key local loop
pip install "agentvision[render,anthropic]"  # + Claude analysis
```

System dependencies (Chromium, Tesseract, poppler) and a `doctor` that checks them:

```bash
agentvision doctor          # attempts a real Chromium launch; lists every missing lib
agentvision doctor --fix    # installs the Chromium browser binary
```

On a bare RHEL/CentOS box, `playwright install-deps` does **not** work (apt-only). See
[docs/quickstart.md](docs/quickstart.md) for the `dnf` line, or use the bundled
**Dockerfile** which bakes the deps in.

## Usage

```bash
# Analyze a file/URL/HTML string and print a structured report
agentvision analyze ./index.html --backend local --json

# Run the self-correcting loop
agentvision loop ./dashboard.html --max-iter 3

# Responsive contact sheet across breakpoints
agentvision sheet ./index.html --breakpoints 375,768,1280,1920

# Visual regression against a named baseline
agentvision baseline ./index.html --name home
agentvision regress  ./index.html --name home
```

Library:

```python
import asyncio
from agentvision import load_settings
from agentvision.core.loop import LoopSession

async def main():
    settings = load_settings(vision_backend="local")
    session = LoopSession("examples/broken_layout.html", settings=settings)
    result = await session.iterate()
    print(result.report.verdict, [i.message for i in result.report.issues])

asyncio.run(main())
```

## Documentation

- [Quickstart](docs/quickstart.md) · [The Loop](docs/the-loop.md) ·
  [Backends](docs/backends.md) · [Adapters](docs/adapters.md) ·
  [Integrations](docs/integrations.md) · [Vision](docs/VISION.md)

## What we do **not** claim (honesty)

- Pixel-accurate *vision-model* bounding boxes (they're advisory).
- WCAG verdicts on rasterized non-HTML (heuristic only).
- Bit-reproducible screenshots / deterministic LLM reports.
- Uniform provider-agnostic *behavior* (only the API surface is uniform).

## License

MIT © Amit Patole
