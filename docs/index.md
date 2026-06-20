# AgentVision — Eyes for AI Agents 👁️

<p align="center">
  <img src="banner.png" alt="AgentVision — render, see, report, fix before claiming done" width="100%">
</p>

> **Problem:** AI coding agents are *blind* — they write a UI, chart, SVG, PDF or image and
> never *see* the result, shipping breakage they can't perceive.
> **Result:** AgentVision gives them eyes — **render → see → report → fix** — so the agent
> **self-corrects before it claims done.**

```bash
pip install "agentvision[render]"
playwright install chromium      # see `agentvision doctor` if Chromium won't launch
agentvision demo                 # no API key required
```

`agentvision demo` renders a deliberately broken page, prints a **FAIL** report (overflow +
low-contrast + a 404 image — all DOM/CV-grounded, no LLM key), then loops against the fixed
version and prints *"what changed: 3 issues resolved → PASS."*

## What it does

| Capability | What you get |
|---|---|
| **See & report** | A machine verdict (`pass`/`warn`/`fail`) + coordinate-grounded issues — DOM geometry, computed-style WCAG contrast, OCR/typos, broken-image & console/4xx capture. |
| **[Match intent](conformance.md)** | Grade a render against a brief / checklist / reference — PASS means *"it's what I set out to build,"* not just *"defect-free."* |
| **[Full-coverage vision](backends.md)** | Large artifacts get a downscaled overview **plus full-res tiles** — pixel-based & source-agnostic (HTML, image, PDF, canvas). |
| **[Streaming / temporal](use-cases/streaming.md)** | `watch` verifies behavior over time — playback, loading, liveness — not just a single glance. |
| **[Eyes → brain handoff](handoff.md)** | A distilled `{verdict, next_action, todo, open_questions}` signal any agent/brain acts on. |

## Where to go next

<div class="grid cards" markdown>

- :material-rocket-launch: **[Quickstart](quickstart.md)** — install, system deps, first run.
- :material-sync: **[The loop](the-loop.md)** — render → perceive → report → fix → diff.
- :material-target: **[Conformance](conformance.md)** — grade against intent.
- :material-brain: **[Handoff](handoff.md)** — wire perception into your reasoning/memory.
- :material-play-circle: **[Streaming / temporal](use-cases/streaming.md)** — `watch` over time.
- :material-cog: **[Workflows & agents](integrations.md)** — GitHub Action, pre-commit, MCP, the agent contract.
- :material-console: **[CLI reference](cli.md)** · :material-tune: **[Configuration](configuration.md)** · :material-language-python: **[Python API](api.md)**
- :material-book-open-variant: **[Recipes](recipes.md)** · :material-help-circle: **[FAQ](faq.md)**

</div>

## Eyes & brain

AgentVision is the **eyes**. It pairs with **[Verel](https://github.com/amitpatole/verel)**, the
**brain** — an agent framework where *nothing is "done" until a grader returns a verdict.* The
eyes perceive and grade intent; the brain decides and **compounds only verified work** into
memory; then the eyes look again.

<p align="center">
  <img src="unified-architecture.png" alt="Eyes & Brain — AgentVision perceives; Verel decides and compounds verified work" width="100%">
</p>

Install: `pip install "agentvision[all]"` · Source: [GitHub](https://github.com/amitpatole/agent-vision)
· Package: [PyPI](https://pypi.org/project/agentvision/) · License: MIT.
