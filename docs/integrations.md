# Integrating AgentVision into your workflow & your agents

Developers use AgentVision in two places: **their dev/CI workflow** (gate merges on what the
UI actually looks like) and **their agents** (give the agent eyes so it self-corrects). Both
on-ramps below.

## In your CI / workflow

**GitHub Action** (installs AgentVision + Chromium and fails the build on a `fail` verdict):

```yaml
# .github/workflows/visual.yml
jobs:
  visual:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: amitpatole/agent-vision@v0.6.1
        with:
          source: dist/index.html
          command: check            # check (no key) | analyze | conform | watch
          args: --full-page
      # Intent gate with a vision backend:
      - uses: amitpatole/agent-vision@v0.6.1
        with:
          command: conform
          source: dist/index.html
          backend: anthropic
          expect: |
            must: a "Checkout" button is visible
            should: uses the brand's dark theme
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

**pre-commit** (this repo ships `.pre-commit-hooks.yaml`):

```yaml
# .pre-commit-config.yaml
- repo: https://github.com/amitpatole/agent-vision
  rev: v0.6.1
  hooks:
    - id: agentvision-check
      args: ["dist/index.html", "--quiet"]
```

**Any CI / Makefile / script** — just shell out; non-zero exit fails the gate:

```bash
agentvision check ./dist/index.html --quiet            # 0 pass/warn · 2 fail · 3 error
agentvision conform ./dist/index.html --expect 'must: shows "Total"' --quiet
agentvision watch http://localhost:3000 --allow-local --no-vision --quiet
```

`--quiet` writes only the JSON report to stdout (logs to stderr) — easy to capture and parse.
The bundled **Dockerfile** bakes in Chromium/Tesseract/poppler for a hermetic runner.

## In your agents

"Provider-agnostic" means the **API surface** works anywhere — but an agent only benefits
if it's actually told to use the loop. Pick the on-ramp that matches your agent:

| Agent / host | How | Recipe |
|---|---|---|
| **Claude Code** | Skill (auto-invokes before "done") | [`skill/SKILL.md`](https://github.com/amitpatole/agent-vision/blob/main/skill/SKILL.md) |
| **Cursor** | MCP server or project rule | [`integrations/cursor.rules.md`](https://github.com/amitpatole/agent-vision/blob/main/integrations/cursor.rules.md) |
| **Aider** | `/run` or `--test-cmd` | [`integrations/aider.md`](https://github.com/amitpatole/agent-vision/blob/main/integrations/aider.md) |
| **Any MCP host** | `agentvision-mcp` | [`adapters.md`](adapters.md) |
| **Anything else** | the CLI + a system-prompt contract | [`integrations/agent-contract.md`](https://github.com/amitpatole/agent-vision/blob/main/integrations/agent-contract.md) |

## The universal contract

Whatever the agent, the behavior you want is:

1. After producing/editing a visual artifact, run `agentvision check`/`analyze <artifact>
   --quiet` (use `conform` to also grade intent, `watch` for streaming/over-time behavior).
2. Treat `issues` as a required to-do list (or use `--handoff` for `next_action`/`todo`); fix
   the source.
3. Re-run `agentvision loop` until the verdict is `pass`.
4. Don't claim the task done without a passing verdict.

Copy [`integrations/agent-contract.md`](https://github.com/amitpatole/agent-vision/blob/main/integrations/agent-contract.md) into your
agent's system prompt to enforce it.

## Why Claude Code is "first-class"

The Claude Code Skill is the one surface that makes an agent invoke the loop *proactively*
(its `description` triggers on visual work, before the agent claims completion). Other
agents get the same capability but you must wire the trigger yourself (a rule, a test
command, or the contract above). MCP is the first-class cross-host path.
