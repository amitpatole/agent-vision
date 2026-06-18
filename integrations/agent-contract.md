# The AgentVision "agent contract"

Paste this into any coding agent's system prompt / rules to make it use its eyes. It is
provider-agnostic: it only assumes the agent can run a shell command.

---

You have **eyes** via the `agentvision` CLI. You cannot otherwise see what your code
renders, so you MUST visually verify any visual artifact before claiming it is done.

After you create or modify a visual artifact (HTML/CSS/JS UI, a chart, an SVG, a PDF, or
an exported image), follow this loop:

1. Run: `agentvision analyze <artifact> --full-page --json`
   (or `agentvision check <artifact> --json` for a fast, no-API-key structural pass).
2. Parse the JSON `Report`. If `verdict` is `fail`, treat every entry in `issues` as a
   required fix. Each issue has `kind`, `severity`, `message`, and often a `bbox`.
3. Edit the source to resolve the issues.
4. Re-run `agentvision loop <artifact> --max-iter 3` to confirm the fixes and check for
   regressions (it reports what changed and whether you are stuck).
5. Only report the task complete when `verdict` is `pass`.

Never claim a visual task is finished without a passing AgentVision verdict.
