# 5-minute tutorial

A guided tour of the four things the eyes do — **structural checks**, **semantic critique**,
**intent conformance**, and the **self-correcting loop** — on one page. By the end you'll know
which command to reach for and what each verdict means.

!!! tip "Prerequisites"
    Install with `pip install "agentvision[all]"` and `playwright install chromium`. Steps 1
    and 4 need no key; steps 2–3 use a vision backend — set one of `OPENAI_API_KEY`,
    `ANTHROPIC_API_KEY`, or `GOOGLE_API_KEY` (or use `--backend local` to skip semantic
    grading). New here? Start with **[Try it yourself](try-it.md)**.

We'll use the broken page shipped in the repo, `examples/broken_layout.html`.

## Minute 1 — structural checks (no key)

```bash
agentvision check examples/broken_layout.html
```

`check` measures the rendered DOM + pixels. No LLM, no network. **Actual output:**

```text
  FAIL  (checks)
  Structural checks found 4 issue(s).

  • [contrast] Low contrast (ratio 1.66, needs 4.5 for AA) on text 'Revenue is up 12% over last quarter…' @(24,105) (dom/high)
  • [contrast] Low contrast (ratio 1.70, needs 4.5 for AA) on text 'Click here to view the full report' @(24,283) (dom/high)
  • [overflow] Page content overflows horizontally by 976px (causes a horizontal scrollbar). (dom/high)
  • [broken_image] Broken image (failed to load): missing-logo.png @(24,138) (dom/high)
```

These four are **deterministic** — same page, same verdict, every time. Use `check` as a
zero-cost CI gate.

## Minute 2 — semantic critique (vision backend)

`check` can't tell you the headline is awkward or the button looks unclickable — that needs a
vision model. `analyze` adds semantic critique on top of the structural grounding:

```bash
agentvision analyze examples/broken_layout.html --backend openai
```

You get the same DOM/CV issues **plus** model-found issues, each still grounded with a source
(`vision`) and a bounding box. The structural findings keep the model honest: a vision
"missing element" claim is cross-checked against the DOM/OCR and suppressed if the element is
provably present.

## Minute 3 — grade against intent

Defects aside, *does the page do what you set out to build?* `conform` grades the render
against requirements you state — `must` (gating) and `should` (advisory):

```bash
agentvision conform examples/broken_layout.html --backend openai \
  --expect "must: a 'View report' call-to-action link is visible"
```

**Actual output (trimmed):**

```text
  intent match: 0/1 requirement(s)
    ✗ [must] a 'View report' call-to-action link is visible  (ocr)
```

The eyes graded the requirement **violated** — the "View report" CTA isn't found in the
rendered output — and the unmet `must` drives the `fail` verdict. That's the difference between
"no defects" and "actually built the right thing." See **[Conformance](conformance.md)** for
the full `must`/`should`/reference grammar.

## Minute 4 — the self-correcting loop

In an agent, you don't want a one-shot report — you want *render → see → fix → re-render* until
it passes. That's `loop` on the CLI, and `LoopSession` in Python:

```python
import asyncio
from pathlib import Path
from agentvision.config import load_settings
from agentvision.core.loop import LoopSession

async def main():
    settings = load_settings(vision_backend="local")
    session = LoopSession(Path("examples/broken_layout.html"), settings=settings)
    result = await session.iterate()
    print(result.report.verdict, len(result.report.issues), "issue(s)")

asyncio.run(main())
```

Running the bundled `examples/fix_loop.py` (the agent edits the source between iterations)
produces this **actual output**:

```text
iter 0 → FAIL with 4 issue(s):
   - [contrast] Low contrast (ratio 1.66, needs 4.5 for AA) on text 'Revenue is up 12%…'
   - [contrast] Low contrast (ratio 1.70, needs 4.5 for AA) on text 'Click here to view the full report'
   - [overflow] Page content overflows horizontally by 976px (causes a horizontal scrollbar).
   - [broken_image] Broken image (failed to load): missing-logo.png

iter 1 → PASS with 0 issue(s)
what changed: Moderate visual change (SSIM 0.972); 12 region(s) differ.

✓ FAIL → PASS: the agent saw the problems and fixed them.
```

## Minute 5 — hand the result to a brain

Every report distills to a **`Handoff`** — `{verdict, next_action, todo, open_questions}` — the
one signal an agent or orchestrator acts on:

```bash
agentvision check examples/broken_layout.html --handoff
```

This is the shared **[`agentsensory`](https://pypi.org/project/agentsensory/)** contract, so the
same `Handoff` drops straight onto a brain like [Verel](handoff.md)'s verdict bus — vision
graded alongside tests, lint, and types.

## Recap

| Command | What it grades | Needs a key? |
|---|---|---|
| `check` | structural DOM/CV defects | no |
| `analyze` | defects **+** semantic critique | yes (vision backend) |
| `conform` | match against stated **intent** | yes (vision backend) |
| `loop` | iterate until it passes | no (with `local`) |

Next: **[Real-world scenarios](examples.md)** · **[Use cases](use-cases.md)** ·
**[CLI reference](cli.md)**.
