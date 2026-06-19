# Eyes → Brain: the handoff path

## The anatomy

Eyes don't decide. In the human visual loop the **retina perceives**, the **optic nerve**
carries the signal to the **brain**, the brain **decides**, a **motor signal** moves the
hand, and then the eyes **look again**. Perception is the *afferent* (inbound) half; action
is the *efferent* (outbound) half.

AgentVision is the **afferent pathway for an agent**. It gives an agent eyes — but it
deliberately does **not** decide what to do, edit your code, or rewrite your prompt. It
perceives the rendered artifact and hands a clean, structured signal back to **the brain**:
whatever does the reasoning, planning, or memory in your stack.

```
        AgentVision (the eyes)                     your agent (the brain)
   ┌──────────────────────────────┐        ┌────────────────────────────────┐
   │ render → perceive → grade     │  ───►  │ decide → act (edit code /        │
   │   = Report  ⟶  Handoff signal │ afferent│   refine prompt) = efferent     │
   └──────────────────────────────┘        └────────────────────────────────┘
                  ▲                                          │
                  └──────────────  look again  ──────────────┘
```

This separation is the point: AgentVision stays **provider-agnostic** and brain-agnostic. Any
reasoning layer, any memory system, any orchestrator can consume the same signal.

## The signal: `Handoff`

A [`Report`](the-loop.md) is the full sensory detail. A **`Handoff`** is that report distilled
into what a brain acts on directly — produced by `report.to_handoff()`:

```jsonc
{
  "perceived": "fail",            // what the eyes concluded: pass | warn | fail
  "next_action": "revise",        // done | revise | review
  "matches_intent": false,        // null when no brief was given
  "summary": "…",
  "todo": [                       // prioritized, actionable (defects first, then unmet musts)
    "[overflow] hero text overflows its container on the right",
    "[intent/must] a \"Checkout\" button is visible"
  ],
  "open_questions": [             // what perception could NOT confirm — the brain should verify
    "Verify: uses the brand's dark theme"
  ],
  "artifact": "/…/render.png",
  "backend": "anthropic",
  "model": "claude-haiku-4-5"
}
```

Contract, in one line: **`next_action`** tells the brain whether to stop (`done`), act on
`todo` and look again (`revise`), or apply judgment (`review`). `todo` is the efferent
work-list. `open_questions` is what the eyes saw but couldn't decide — never silently
dropped.

## Getting the signal

```bash
# CLI — any perception command can emit the handoff instead of the full report
agentvision analyze ./page.html --handoff
agentvision conform ./infographic.png --brief "…" --handoff
agentvision check  ./page.html --handoff          # offline, no key
```

```python
# Library
from agentvision import analyze
report = await analyze("./page.html", brief=brief)
signal = report.to_handoff()
```

- **MCP**: the `perceive_handoff` tool returns the signal directly (for hosts that want the
  decision, not the full report).
- **REST**: `POST /handoff` returns the signal + an `artifact_id`.
- **Loop**: every `IterationResult` carries a `handoff`, and each iteration writes a
  `handoff.json` next to its `report.json`.

## Wiring it into a brain (provider-agnostic recipe)

The handoff is designed to drive a loop without the brain understanding AgentVision's
internals:

```python
from agentvision import analyze, NextAction

async def build_until_it_looks_right(make_or_edit, source, brief=None, max_steps=4):
    for _ in range(max_steps):
        signal = (await analyze(source, brief=brief)).to_handoff()
        if signal.next_action == NextAction.DONE:
            return True                      # eyes say it's right — safe to claim done
        if signal.next_action == NextAction.REVIEW:
            # uncertain/minor — let the brain decide (ask the user, accept, or push on)
            ...
        # efferent step: the BRAIN acts on the work-list, then we look again
        make_or_edit(todo=signal.todo, questions=signal.open_questions)
    return False
```

### Persisting to memory (any memory/brain system)

The `Handoff` is also the natural unit of **visual episodic memory** — one record per
look. Store it (it's plain JSON) keyed by artifact + iteration, and your reasoning layer can
recall *"what did the eyes say last time, and did my fix actually resolve it?"* AgentVision
emits the signal in a stable, self-describing shape (`schema_version`) precisely so any
external brain or memory store can own persistence and recall — AgentVision does not assume
or require a particular one. [Verel](#reference-brain-verel) is the reference implementation
of this pattern.

## Reference brain: Verel

[Verel](https://github.com/amitpatole/verel) is a full agent brain built on exactly this
split. It consumes AgentVision as its **Eyes** organ (`verel.senses.sight`): each `Report` is
mapped into a unified **verdict bus** (vision graded alongside tests, lint, and types), and
verified perceptions — including **intent conformance** (`matches_intent` and the
satisfied/total counts) — **compound into its memory** across iterations.

One design note worth copying: a *full* brain like Verel ingests the rich `Report` directly,
because it runs its **own** verdict gate and its **own** progressed/stuck detection — so it
deliberately ignores AgentVision's `next_action` (the brain keeps decision authority). The
`Handoff` is for *simpler* brains that want the decision pre-distilled. Both consume the same
eyes; pick the level that fits your brain.

## Why the split matters (honesty)

- AgentVision will not pretend to be the brain. It reports `next_action: review` for
  uncertain/minor cases rather than forcing a decision it can't justify.
- `open_questions` surfaces the limits of perception (low-confidence findings, unverifiable
  intent) so the brain can resolve them instead of inheriting a false PASS.
- The signal is advisory where perception is advisory (vision-model findings) and trustworthy
  where it is grounded (DOM/OCR/CV) — the brain keeps final authority.

See also: [The Loop](the-loop.md) · [Conformance](conformance.md) · [Adapters](adapters.md) ·
[Integrations](integrations.md).
