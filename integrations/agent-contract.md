# The AgentVision "agent contract"

Paste this into any coding agent's system prompt / rules to make it use its eyes. It is
provider-agnostic: it only assumes the agent can run a shell command. (MCP hosts get the same
via the `agentvision-mcp` tools; Claude Code via `skill/SKILL.md`.)

---

You have **eyes** via the `agentvision` CLI. You cannot otherwise see what your code renders,
so you MUST visually verify any visual artifact before claiming it is done. Add `--quiet` to
any command for JSON-only output on stdout (logs on stderr); exit codes are **0 = pass/warn,
2 = fail, 3 = error**, so you can branch on them.

After you create or modify a visual artifact (HTML/CSS/JS UI, chart, SVG, PDF, image), run the
loop that fits the task:

1. **See it.**
   - `agentvision check <artifact> --quiet` — fast, no API key (DOM geometry, contrast, broken
     images, OCR/typos). Always available.
   - `agentvision analyze <artifact> --backend <b> --quiet` — adds semantic vision critique.
2. **Did it match what you were asked to build?** (not just "is it broken?")
   - `agentvision conform <artifact> --brief "<the goal>" --expect 'must: …' --quiet`
   - PASS means it matches intent. Put exact required text in quotes (graded deterministically).
3. **Does it behave over time?** (streaming / video / live / animated)
   - `agentvision watch <artifact> --expect 'must: the video is playing' --quiet`
   - Verifies playback / loading / liveness across frames, not a single glance.
4. **Read the result.** Parse the JSON. Treat every `issues[]` entry as a required fix (each has
   `kind`, `severity`, `message`, often a `bbox`). Prefer `--handoff`, which distills the report
   to `{ perceived, next_action (done|revise|review), todo[], open_questions[] }` — act on
   `next_action`/`todo` directly.
5. **Fix the source**, then **re-run** `agentvision loop <artifact> --max-iter 3 --quiet` to
   confirm the fixes and detect when you are stuck (it reports what changed).
6. **Only report the task complete when the verdict is `pass`** (or remaining items are
   explicitly accepted warnings).

Never claim a visual task is finished without a passing AgentVision verdict.
