# AgentVision — Eyes for AI Agents 👁️

<p align="center">
  <img src="docs/banner.png" alt="AgentVision — Eyes for AI Agents: render, see, report, fix — before claiming done" width="100%">
</p>

> **Problem:** AI coding agents are *blind* — they write a UI, chart, SVG or PDF and never *see* the result, shipping breakage they can't perceive.  
> **Result:** AgentVision gives them eyes — render → see → report → fix — catching overflow, low contrast, broken images and typos.  
> So your agent **self-corrects before it claims done.**

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

**Full-coverage vision.** On a large artifact the model gets a downscaled overview *plus*
full-resolution tiles covering it, so fine detail and small text aren't lost to downscaling.
It's pixel-based and source-agnostic — the same coverage applies to HTML, a flat image, or a
PDF page, not just elements the DOM enumerates.

## Match the intent, not just avoid defects

A typo-free, well-laid-out artifact can still be **the wrong thing** — an infographic that
shows the wrong stages, a page missing the panel you asked for, a generated image that
ignored half the prompt. Give AgentVision the **intent** and it grades the render against it,
so **PASS means "matches what I set out to build,"** not merely "defect-free":

```bash
# Does the render match the thought? (text claims grade deterministically via OCR)
agentvision conform ./infographic.png \
  --brief "launch infographic for AgentVision" \
  --expect 'must: title reads "AgentVision"' \
  --expect 'should: shows 4 stages left to right'
```

For **AI-generated** artifacts the fix is a better *prompt*, not code — so the generative loop
**generate → see → grade vs intent → refine prompt → regenerate** runs until it matches. The
image generator is a hook you supply; AgentVision never bundles an image-gen dependency:

```bash
agentvision generate --generator mypkg.gen:make_image \
  --brief "minimalist infographic, dark background, no typos" --max-iter 4 -o final.png
```

See [docs/conformance.md](docs/conformance.md). Express intent three ways — a free-text
**brief** (eyes extract the checklist), an **explicit checklist** (`--expect`, deterministic),
or a **reference image** (`--reference`). Claims are `must:` / `should:` / `nice:`.

## Eyes → brain: the handoff

In anatomy the eyes are only the *afferent* half — the retina perceives, the optic nerve
carries the signal to the brain, the brain decides, the hand acts, the eyes look again.
AgentVision is that afferent pathway for an agent: it perceives and hands a clean signal back
to **the brain** (whatever does your reasoning/planning/memory) — it deliberately doesn't
decide for you. Any perception call distills to a **`Handoff`**:

```bash
agentvision analyze ./page.html --handoff
```
```jsonc
{ "perceived": "fail", "next_action": "revise", "matches_intent": false,
  "todo": ["[overflow] hero text overflows on the right",
           "[intent/must] a \"Checkout\" button is visible"],
  "open_questions": ["Verify: uses the brand's dark theme"] }
```

`next_action` (`done` / `revise` / `review`) drives the brain's loop; `todo` is the work-list;
`open_questions` is what perception couldn't confirm (never dropped). Available as
`report.to_handoff()`, the MCP `perceive_handoff` tool, `POST /handoff`, and a `handoff.json`
per loop iteration — provider- and brain-agnostic. See [docs/handoff.md](docs/handoff.md).

## Eyes & Brain — AgentVision × Verel

AgentVision is the **eyes**. It pairs with **[Verel](https://github.com/amitpatole/verel)**,
the **brain** — an agent framework where *nothing is "done" until a grader returns a verdict.*
The eyes perceive and grade intent; the brain decides with attestation and **compounds only
verified work** into memory; then the eyes look again.

<p align="center">
  <img src="docs/unified-architecture.png" alt="Eyes & Brain — AgentVision perceives and grades intent; Verel decides and compounds verified work into memory" width="100%">
</p>

They ship and version independently (`pip install agentvision`, `pip install verel`) yet work
in sync: AgentVision plugs into Verel as its `verel.senses` perception organ — mapped onto a
unified verdict bus (vision *alongside* tests, lint and types), with intent conformance
recorded in the brain's memory each iteration. AgentVision stays brain-agnostic; Verel is the
reference brain. See [docs/handoff.md](docs/handoff.md).

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

**Live pages, SPAs & dashboards** (polling, websockets, canvas/WebGL):

```bash
# localhost dev server, wait for the data to render, freeze animation, machine output
agentvision analyze http://localhost:5173 --allow-local \
  --wait-for "#dashboard" --settle-ms 800 --quiet
```

**Streaming / video / over-time behavior** — watch, don't just glance:

```bash
# Is the video actually playing? Did loading finish? Are captions on?
agentvision watch https://app.example.com/player --frames 6 --interval-ms 500 \
  --expect 'must: the video is playing'
```

`watch` reads deterministic `<video>` state (currentTime/readyState/captions) + pixel
liveness/stall/black-frame detection, then adds a time-aware vision pass. See
[docs/use-cases/streaming.md](docs/use-cases/streaming.md).

`--nav-wait` defaults to `load` (polling pages never go idle); `--freeze` (default on) pauses
animations + `requestAnimationFrame` so canvas/WebGL pages capture without hanging; `--quiet`
prints only JSON (logs to stderr, exit codes 0 pass/warn · 2 fail · 3 error).

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

## Drop it into your workflow & your agents

```yaml
# CI gate (GitHub Action): fails the build on a visual FAIL verdict
- uses: amitpatole/agent-vision@v0.6.0
  with: { source: dist/index.html, command: check, args: --full-page }
```

- **CI / pre-commit / Makefile** — shell out; exit codes `0 pass/warn · 2 fail · 3 error`,
  `--quiet` for JSON-only output. Reusable **GitHub Action** + **pre-commit hook** included.
- **Your agents** — drop [`integrations/agent-contract.md`](integrations/agent-contract.md)
  into the system prompt, use the **Claude Code Skill**, or the **MCP** tools (Cursor/Claude/any host).

Full guide: [docs/integrations.md](docs/integrations.md).

## Documentation

- [Quickstart](docs/quickstart.md) · [The Loop](docs/the-loop.md) ·
  [Conformance](docs/conformance.md) · [Handoff (eyes→brain)](docs/handoff.md) ·
  [Streaming / temporal](docs/use-cases/streaming.md) · [Backends](docs/backends.md) ·
  [Adapters](docs/adapters.md) · [Integrations](docs/integrations.md) · [Vision](docs/VISION.md)

## What we do **not** claim (honesty)

- Pixel-accurate *vision-model* bounding boxes (they're advisory).
- WCAG verdicts on rasterized non-HTML (heuristic only).
- Bit-reproducible screenshots / deterministic LLM reports.
- Uniform provider-agnostic *behavior* (only the API surface is uniform).

## License

MIT © Amit Patole
