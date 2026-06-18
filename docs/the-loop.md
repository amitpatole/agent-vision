# The visual feedback loop

The loop is the whole point: **render → perceive → report → (fix) → re-render → diff.**

```
agent writes code  ─▶  agentvision renders it  ─▶  Report (verdict + issues)
       ▲                                                   │
       └────────────  agent fixes the source  ◀────────────┘
```

## Report

Every analysis returns a `Report`:

- `verdict` — `pass` | `warn` | `fail` (scriptable; the CLI exits non-zero on `fail`)
- `summary` — one-paragraph critique
- `issues[]` — each has `kind`, `severity`, `message`, optional `bbox`, a `confidence`,
  and a `source`:
  - `dom` / `ocr` / `cv` → **precise** boxes (`bbox_precise: true`)
  - `vision` → **advisory** boxes from the LLM (`bbox_precise: false`)
- `capabilities[]` — which issue kinds the producing backend can emit (the `local`
  backend emits fewer than the LLM backends — it does structural checks only)

## Progress & stuck detection

The loop decides progress by **issue-set stability**, not by pixel similarity:

- If the set of `(kind, message)` issues changes between iterations → **progressed**.
- If it stays identical across iterations and the verdict is still failing → **stuck**.

This is deliberate: a real fix (adding `alt`, fixing a 404, nudging a color) can barely
move pixels, while thrashing can move them a lot. SSIM is reported as a secondary
"what changed" signal only.

## Driving the loop

### From an agent (programmatic)

```python
import asyncio
from agentvision.config import load_settings
from agentvision.core.loop import LoopSession

async def main():
    session = LoopSession("dashboard.html", settings=load_settings(vision_backend="anthropic"))
    result = await session.iterate()
    while result.verdict.value != "pass" and not result.stuck:
        # ... agent edits dashboard.html based on result.report.issues ...
        result = await session.iterate()   # optionally pass an updated source path

asyncio.run(main())
```

### From the CLI

```bash
agentvision loop dashboard.html --max-iter 3
```

The CLI re-renders the same source up to `--max-iter` times (useful to *demonstrate* the
loop and stuck-detection). Real agents call `iterate()` and edit the source between calls.
