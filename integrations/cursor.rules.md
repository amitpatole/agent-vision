# Using AgentVision in Cursor

Two ways to wire AgentVision into Cursor.

## A. As an MCP server (recommended)

Add to your Cursor MCP settings (`~/.cursor/mcp.json` or the MCP settings UI):

```json
{
  "mcpServers": {
    "agentvision": {
      "command": "agentvision-mcp",
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-…"
      }
    }
  }
}
```

Then the agent can call `analyze_artifact`, `start_loop`/`loop_iterate`, `render_artifact`,
`contact_sheet`, `visual_diff`, and `doctor` directly.

## B. As a project rule (no MCP)

Add a `.cursor/rules` entry (or paste into Cursor Rules):

```
When you generate or edit any visual artifact (HTML/CSS/JS UI, chart, SVG, PDF, image),
you must verify it visually before saying it's done:
1. Run `agentvision check <artifact> --json` (no API key) or
   `agentvision analyze <artifact> --json` (with a key for semantic critique).
2. Treat the report's `issues` as a required to-do list; fix the source.
3. Re-run `agentvision loop <artifact> --max-iter 3` and only finish when verdict is `pass`.
```

See `integrations/agent-contract.md` for the full copy-paste contract.
