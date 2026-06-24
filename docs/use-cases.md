# Use cases

Where the eyes earn their keep. The through-line: **anything that renders to pixels can be
graded before it's shipped** — by one agent, a CI pipeline, or a whole swarm.

## A swarm of agents (the main event)

A fleet of agents generating UIs, charts, dashboards or documents in parallel — each one needs
to *see* its output before claiming done, and the orchestrator needs every verdict in the same
language to decide what advances.

- Run **eyes as a service** ([scaling](scaling.md)) and point the whole swarm at it; or embed
  the library in each worker. Single-shot grading (`check`/`analyze`/`conform`) scales
  horizontally with zero coordination.
- Every worker returns the same [`agentsensory`](https://pypi.org/project/agentsensory/)
  `Report`/`Handoff`, so a coordinator (or a brain like [Verel](handoff.md)) aggregates verdicts
  on **one bus** — vision alongside tests, lint and types — and only PASS work compounds.
- See **[Swarms & scaling](scaling.md)** for topologies and the [fan-out
  example](scaling.md#fan-out-example-one-service-many-agents).

## An agent that self-corrects before claiming done

The single-agent core, and the foundation of the swarm case. The agent writes a UI, **renders
and looks at it**, gets grounded issues, fixes them, and re-renders until the verdict is PASS —
instead of confidently shipping breakage it can't perceive.

- Drop the [agent contract](integrations.md) into the system prompt, or use the **MCP** tools or
  **Claude Code Skill** so the agent calls the eyes mid-task.
- The [self-correcting loop](the-loop.md) (`loop` / `LoopSession`) automates the
  render→see→fix→re-render cycle.

## A visual gate in CI

Fail the build when the page actually looks wrong — not when a snapshot pixel-diffs (those flake
on fonts/timing). `check` is deterministic and needs no API key:

```bash
agentvision check dist/index.html --full-page --quiet   # exit 2 on FAIL
```

Add a vision backend and `conform` to gate on **intent** ("a checkout button is visible"), not
just defects. See [Workflows & agents](integrations.md) for the GitHub Action and pre-commit
hook.

## Documents, decks, and PDFs

Point any command at a `.pdf` or an Office/OpenDocument file (`.docx/.pptx/.xlsx/.odt/…`) and
it's rasterized **per page** and graded like a screenshot — so a generated report or slide deck
gets the same FAIL/PASS treatment as a web page. (Office conversion is on for local use, off by
default on the REST service — it's a large attack surface.)

## Streaming, loading, and liveness

A glance can't tell a chart that's still loading from one that's broken. `watch` verifies an
artifact **over time** — frames across an interval — to confirm playback, a loading→loaded
transition, or that a live dashboard actually updates. See [Streaming /
temporal](use-cases/streaming.md).

## Visual regression against a baseline

Capture a named baseline, then gate future renders against it with a structural SSIM diff:

```bash
agentvision baseline dist/index.html --name home
agentvision regress dist/index.html --name home      # fails if it drifted
```

Useful as a cheap, key-free guardrail alongside the semantic checks.

## Generative loops (image/asset generation)

When the artifact is *generated* (not hand-written), `generate` runs generate → see → grade vs
intent → refine prompt → regenerate, so an image/asset pipeline converges on what you actually
asked for rather than stopping at the first plausible output.

---

Ready to try these? **[Try it yourself](try-it.md)** · **[5-minute tutorial](tutorial.md)** ·
**[Real-world scenarios](examples.md)**.
