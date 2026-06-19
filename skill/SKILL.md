---
name: agent-vision
description: >-
  Visually verify rendered output before claiming a UI/visual task is done. Use whenever
  you generate or edit a visual artifact — frontend HTML/CSS/JSX, a generated chart or
  plot, an SVG/diagram, a PDF, or an exported image. AgentVision renders the artifact,
  "sees" it, and returns a machine-graded report (pass/warn/fail + located, actionable
  issues) so you can self-correct instead of guessing from source code alone.
allowed-tools:
  - Bash(agentvision *)
---

# AgentVision — see your visual output before saying it's done

You cannot see what your code renders. AgentVision can. Use it to close the loop.

## When to use this

Right after you create or change anything visual, and **before** you tell the user it's
done:

- Frontend pages/components (HTML/CSS/React/Vue/Svelte)
- Generated charts, plots, dashboards
- SVG diagrams, exported PDFs, generated images

## The workflow

1. **Render + analyze** the artifact (use `local` for a fast, no-key structural pass; use
   a cloud backend for semantic critique):

   ```bash
   agentvision analyze ./path/to/artifact.html --full-page --json
   # or, no API key needed:
   agentvision check ./path/to/artifact.html --json
   ```

2. **Read the report.** Each issue has a `kind`, `severity`, a `message`, and often a
   `bbox` (DOM/CV/OCR boxes are precise; vision-model boxes are advisory). Treat the
   `issues` array as a to-do list.

3. **Fix the source** to resolve each real issue (overflow, low contrast, broken images,
   clipped/overlapping elements, console errors, …).

4. **Loop** to confirm you actually fixed it and didn't regress:

   ```bash
   agentvision loop ./path/to/artifact.html --max-iter 3
   ```

   The loop reports a "what changed" diff and detects when you're **stuck** (same issues
   repeating).

5. **Only report success when the verdict is `pass`** (or remaining items are explicitly
   accepted `warn`s).

## Grade against intent (not just defects)

A defect-free artifact can still be **the wrong thing**. When the task had an intended
result (a brief, a spec, a "make it look like X"), also grade conformance — PASS then means
*"matches what I was asked to build,"* not just *"nothing broken"*:

```bash
agentvision conform ./artifact.html \
  --brief "pricing page with three tiers and a highlighted middle plan" \
  --expect 'must: a "Pro" plan card is visible'
```

Use `--expect 'must:/should:/nice: …'` (repeatable) for explicit, checkable requirements;
put exact required **text in quotes** (those are graded deterministically via OCR). The
report's `conformance` field lists each requirement as satisfied/violated/uncertain, and a
violated `must` fails the verdict. `analyze` and `loop` accept the same
`--brief/--expect/--reference`. For artifacts **you generate** (AI images/infographics),
close the loop on the *prompt*: `agentvision generate --generator mypkg:make_image
--brief "…" --max-iter 4`.

## Tips

- Check responsiveness with a contact sheet: `agentvision sheet ./page.html`.
- The CLI exits non-zero on a `FAIL` verdict — handy in scripts.
- If rendering fails, run `agentvision doctor` (and `--fix`) to diagnose Chromium.
- `--json` gives you structured output to parse; omit it for a readable summary.

Helper script: `scripts/see.sh <artifact>` runs analyze+loop and prints a concise verdict.
