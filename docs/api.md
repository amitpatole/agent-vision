# Python API

Everything the CLI does is available as a library. The high-level entry points are async.

```python
import asyncio
from agentvision import analyze, load_settings

async def main():
    report = await analyze("dist/index.html", settings=load_settings(vision_backend="local"))
    print(report.verdict, [i.message for i in report.issues])

asyncio.run(main())
```

### Confidential inputs (ephemeral cache)

Wrap any call in `ephemeral_cache()` so renders/sessions go to a throwaway temp dir that's
wiped on exit — nothing touches the on-disk cache. Use it for confidential artifacts:

```python
from agentvision import analyze, ephemeral_cache, load_settings

async def main():
    with ephemeral_cache(load_settings()) as settings:
        report = await analyze("confidential.pptx", settings=settings)
        # ... use report ...
    # temp cache dir is removed here, even on error
```

## Core functions

::: agentvision.core.analyze.analyze
::: agentvision.core.analyze.check
::: agentvision.core.watch.watch
::: agentvision.core.render.render
::: agentvision.core.diff.compute_diff

## Sessions

::: agentvision.core.loop.LoopSession
::: agentvision.core.loop.IterationResult
::: agentvision.core.generate.GenerativeLoopSession

## Intent

::: agentvision.models.intent.Brief
::: agentvision.models.intent.IntentClaim

## The report contract

The verdict/report/intent types — `Report`, `Issue`, `Brief`, `Conformance`, `Handoff`,
`BBox` and friends — are the shared **[`agentsensory`](https://pypi.org/project/agentsensory/)**
contract, re-exported from `agentvision` since `0.9.0`. Every organ in the eyes/ears/brain
trio speaks this one language, so a `Report` the eyes grade drops straight onto the same
verdict bus the brain (Verel) consumes — no per-organ translation. `from agentvision import
Report` keeps working unchanged; the import surface is identical.

::: agentvision.models.report.Report
::: agentvision.models.report.Issue
::: agentvision.models.report.Conformance
::: agentvision.models.report.ClaimResult

## The handoff

::: agentvision.models.handoff.Handoff

## Backends

::: agentvision.backends.base.VisionBackend
::: agentvision.backends.base.AnalysisRequest

## Configuration

::: agentvision.config.Settings
::: agentvision.config.load_settings
::: agentvision.workspace.ephemeral_cache
