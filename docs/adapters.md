# Adapters

One core engine, several faces. All adapters wrap the same `agentvision.core` functions
and the same `Report` model.

## Library

```python
import asyncio
from agentvision import load_settings
from agentvision.core import analyze, check, render, compute_diff, contact_sheet
from agentvision.core.loop import LoopSession

report = asyncio.run(analyze("index.html", settings=load_settings(vision_backend="local")))
```

## CLI

```
agentvision demo | render | analyze | check | diff | ocr | loop | sheet
              | baseline | regress | doctor | serve
```

All commands accept `--json` and exit non-zero on a FAIL verdict.

## MCP server

```bash
agentvision-mcp        # stdio
```

Register it with an MCP host (Claude Desktop / Cursor):

```json
{
  "mcpServers": {
    "agentvision": { "command": "agentvision-mcp", "env": { "ANTHROPIC_API_KEY": "sk-ant-…" } }
  }
}
```

Tools: `analyze_artifact`, `check_artifact`, `render_artifact`, `contact_sheet`,
`visual_diff`, `ocr_artifact`, `start_loop`, `loop_iterate`, `manage_baseline`, `doctor`.
Image-returning tools downscale before encoding so they don't overflow stdio/token budgets.
Loop sessions persist in-process so `loop_iterate` continues a `start_loop`.

## REST service

```bash
agentvision-serve --host 0.0.0.0 --port 8000
```

Endpoints: `POST /analyze /check /loop /loop/{id}/iterate /sheet /baseline`,
`GET /baseline/{name} /artifacts/{id} /healthz`.

**Security:** API keys are read server-side only and are never accepted in requests.
Per-request `backend` is limited to the server allowlist (`AGENTVISION_REST_ENABLED_BACKENDS`,
default `["local"]`).

**Multi-worker caveat:** loop sessions are kept in-process. Behind multiple workers you
need sticky sessions or a shared session store; for single-shot `analyze`/`check` there is
no such constraint.
