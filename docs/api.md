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
