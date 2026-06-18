# Integrating AgentVision with any agent

"Provider-agnostic" means the **API surface** works anywhere — but an agent only benefits
if it's actually told to use the loop. Pick the on-ramp that matches your agent:

| Agent / host | How | Recipe |
|---|---|---|
| **Claude Code** | Skill (auto-invokes before "done") | [`skill/SKILL.md`](../skill/SKILL.md) |
| **Cursor** | MCP server or project rule | [`integrations/cursor.rules.md`](../integrations/cursor.rules.md) |
| **Aider** | `/run` or `--test-cmd` | [`integrations/aider.md`](../integrations/aider.md) |
| **Any MCP host** | `agentvision-mcp` | [`adapters.md`](adapters.md) |
| **Anything else** | the CLI + a system-prompt contract | [`integrations/agent-contract.md`](../integrations/agent-contract.md) |

## The universal contract

Whatever the agent, the behavior you want is:

1. After producing/editing a visual artifact, run `agentvision analyze <artifact> --json`
   (or `check` for no-key structural verification).
2. Treat `issues` as a required to-do list; fix the source.
3. Re-run `agentvision loop` until the verdict is `pass`.
4. Don't claim the task done without a passing verdict.

Copy [`integrations/agent-contract.md`](../integrations/agent-contract.md) into your
agent's system prompt to enforce it.

## Why Claude Code is "first-class"

The Claude Code Skill is the one surface that makes an agent invoke the loop *proactively*
(its `description` triggers on visual work, before the agent claims completion). Other
agents get the same capability but you must wire the trigger yourself (a rule, a test
command, or the contract above). MCP is the first-class cross-host path.
