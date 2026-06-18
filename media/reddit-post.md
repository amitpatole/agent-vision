# Reddit post — r/aiagents (Show & Tell)

> Suggested image order: 1) `hero.png` (top), 2) `loop-diagram.png` (in "How it works"),
> 3) `before-after.png` (in the demo section). All three were rendered by AgentVision
> itself (HTML → PNG via its own engine).

---

**Title:**
Sharing my DIY framework that gives AI coding agents *eyes* — they can finally see the UI they build (open source)

---

**Body:**

I kept hitting the same wall with coding agents: they're **blind**. An agent writes a web page, a chart, an SVG, a PDF… and never actually *sees* the result. It reasons from source code and terminal output, then confidently says "done" while the button overflows, the text fails contrast, the chart legend is clipped, or an image 404s.

So I built **AgentVision** — a small framework that gives an agent a visual feedback loop: **render → see → report → fix → re-render → diff.** It's provider-agnostic (works with any agent/LLM), MIT licensed.

**How it works**

- **Render** the artifact headlessly (Chromium) — HTML/URL/SVG/PDF/image.
- **Perceive** it two ways:
  - *Grounded checks* (no LLM, no API key): DOM geometry, computed-style **WCAG contrast**, broken images, JS console / 404 capture, blank-render detection — these give **precise, located** issues.
  - *Semantic critique* on top from a vision LLM (Claude / GPT / Gemini), or skip it entirely with the offline `local` backend.
- **Report**: a machine-graded **verdict (pass / warn / fail)** + a list of located, confidence-tagged issues — so it's scriptable, not just prose.
- **Loop**: the agent fixes the source and re-runs; it diffs against the previous attempt and even detects when it's *stuck* (same issues repeating).

Key design choice: it only trusts coordinates it can actually verify (DOM/CV/OCR boxes are precise; the vision model's boxes are treated as advisory). No "looks-plausible-but-wrong" pixel guesses.

**Try it in 60 seconds (no API key needed):**

```bash
pip install agentvision
playwright install chromium
agentvision demo
```

`demo` renders a deliberately broken page → **FAIL** (overflow + low contrast + broken image, all detected offline) → the agent "fixes" it → **PASS**, with a "what changed" diff. (The before/after image below is real output.)

**It ships in a few "faces" so any agent can use it:** a Python library, a CLI, an MCP server (Cursor/Claude/any MCP host), a REST service, and a Claude Code skill.

**What it does *not* claim (because I'd rather be honest):** pixel-perfect vision-model bounding boxes, WCAG verdicts on rasterized non-HTML, or bit-reproducible screenshots. Those are clearly marked.

Fun meta note: the three images in this post were rendered by AgentVision itself.

**Links**
- GitHub: https://github.com/amitpatole/agent-vision
- PyPI: https://pypi.org/project/agentvision/

Would love feedback — especially on the grounded-vs-LLM split and what visual checks you'd want next. What does *your* agent get wrong visually that it never notices?
