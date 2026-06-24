# Real-world scenarios

Runnable end-to-end demos with **real captured output** (nothing here is mocked). Each maps to
a script in the repo's [`examples/`](https://github.com/amitpatole/agent-vision/tree/main/examples)
directory or a single command you can paste.

## 1. The 60-second demo — FAIL → PASS, no key

The whole loop in one command, on the offline `local` backend:

```bash
agentvision demo
```

```text
AgentVision demo — giving an agent eyes (local backend, no API key)

1) The agent renders its page and looks at it:

  FAIL  (local)
  Heuristic structural analysis (no semantic critique): found 4 issue(s).

  • [contrast] Low contrast (ratio 1.66, needs 4.5 for AA) on text 'Revenue is up 12%…' @(24,105) (dom/high)
  • [contrast] Low contrast (ratio 1.70, needs 4.5 for AA) on text 'Click here to view the full report' @(24,283) (dom/high)
  • [overflow] Page content overflows horizontally by 976px (causes a horizontal scrollbar). (dom/high)
  • [broken_image] Broken image (failed to load): missing-logo.png @(24,138) (dom/high)

2) The agent fixes the issues and looks again:

  PASS  (local)
  No issues.

   what changed: Moderate visual change (SSIM 0.972); 12 region(s) differ.

✓ The agent SAW the problems and fixed them — FAIL → PASS.
```

## 2. Programmatic self-correcting loop

[`examples/fix_loop.py`](https://github.com/amitpatole/agent-vision/blob/main/examples/fix_loop.py)
— a `LoopSession` that re-grades after the agent edits the source (no API key, `local` backend):

```bash
python examples/fix_loop.py
```

```text
iter 0 → FAIL with 4 issue(s):
   - [contrast] Low contrast (ratio 1.66, needs 4.5 for AA) on text 'Revenue is up 12%…'
   - [contrast] Low contrast (ratio 1.70, needs 4.5 for AA) on text 'Click here to view the full report'
   - [overflow] Page content overflows horizontally by 976px (causes a horizontal scrollbar).
   - [broken_image] Broken image (failed to load): missing-logo.png

iter 1 → PASS with 0 issue(s)
what changed: Moderate visual change (SSIM 0.972); 12 region(s) differ.

✓ FAIL → PASS: the agent saw the problems and fixed them.
```

## 3. Grade against intent (vision backend)

Does the page do what you set out to build? `conform` grades the render against requirements:

```bash
agentvision conform examples/broken_layout.html --backend openai \
  --expect "must: a 'View report' call-to-action link is visible"
```

```text
  • [intent_mismatch] [#1] a 'View report' call-to-action link is visible is not satisfied —
    the text 'Click here to view the full report' is nearly illegible due to low contrast and
    not highlighted as a call-to-action. (vision/high)

  intent match: 0/1 requirement(s)
    ✗ [must] a 'View report' call-to-action link is visible  (ocr)
```

The unmet `must` drives a `fail` — "no defects" and "built the right thing" are different
verdicts. See [Conformance](conformance.md).

## 4. Responsive contact sheet

[`examples/contact_sheet.py`](https://github.com/amitpatole/agent-vision/blob/main/examples/contact_sheet.py)
renders one source across breakpoints into a single image — eyeball the whole responsive range
at once:

```bash
python examples/contact_sheet.py
```

```text
Contact sheet written to .../examples/contact_sheet.png
```

Or from the CLI: `agentvision sheet ./index.html`.

## 5. A swarm grading against shared eyes

Run the eyes once as a service and have many agents grade concurrently — the topology behind a
multi-agent fleet. Start the service:

```bash
AGENTVISION_API_TOKEN=$TOKEN agentvision serve --host 0.0.0.0 --port 8000
```

Fan out from a coordinator (single-shot `/check` is stateless, so this scales by adding
replicas):

```python
import asyncio, httpx

async def grade(client, artifact):
    r = await client.post("http://localhost:8000/check",
                          headers={"Authorization": f"Bearer {TOKEN}"},
                          json={"source": artifact})
    return r.json()["verdict"]

async def main(artifacts):
    async with httpx.AsyncClient(timeout=120) as c:
        verdicts = await asyncio.gather(*(grade(c, a) for a in artifacts))
    print(sum(v != "fail" for v in verdicts), "of", len(artifacts), "passed")

asyncio.run(main([...]))
```

For loop sessions across multiple workers, mind the [multi-worker
caveat](scaling.md#the-multi-worker-loop-caveat) — keep loops client-side or sticky-routed. Full
treatment: **[Swarms & scaling](scaling.md)**.

---

More: **[Recipes](recipes.md)** (copy-paste snippets) · **[Workflows &
agents](integrations.md)** (CI + agent on-ramps) · **[CLI reference](cli.md)**.
