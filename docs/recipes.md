# Recipes

Copy-paste solutions to common tasks. All exit non-zero on a `fail` verdict, so they double
as gates.

## Gate a built page in CI (no API key)

```bash
agentvision check dist/index.html --full-page --quiet
```

Or as a [GitHub Action](integrations.md#in-your-ci-workflow):

```yaml
- uses: amitpatole/agent-vision@v0.6.1
  with: { source: dist/index.html, command: check, args: --full-page }
```

## Verify a localhost dev server

```bash
agentvision analyze http://localhost:5173 --allow-local \
  --wait-for "#app" --settle-ms 800 --backend local --quiet
```

`--allow-local` permits private/LAN hosts; `--wait-for`/`--settle-ms` let client-rendered
content populate before capture.

## Does it match the brief? (intent conformance)

```bash
agentvision conform ./pricing.html \
  --brief "a pricing page with three tiers, middle one highlighted" \
  --expect 'must: a "Pro" plan card is visible' \
  --expect 'should: the middle tier is visually emphasized' \
  --backend anthropic
```

Quoted text is graded **deterministically** (OCR/DOM); the rest is judged by the vision model.

## Close the loop on an AI-generated image

```python
from agentvision import Brief, GenerativeLoopSession

def make_image(prompt: str) -> str:
    img = my_model.generate(prompt)        # OpenAI gpt-image, Qwen-Image, local SD, …
    img.save("/tmp/out.png"); return "/tmp/out.png"

brief = Brief.from_inputs(text="minimalist launch infographic, dark bg, no typos",
                          expect=['must: spelled correctly'])
session = GenerativeLoopSession(brief, make_image, backend="anthropic")
history = await session.run(max_iter=4)
print(session.stop_reason)                 # "matched intent" | "stuck" | "max-iter"
```

## Verify a video actually plays (streaming)

```bash
agentvision watch https://app.example.com/player --allow-local \
  --frames 6 --interval-ms 500 \
  --expect 'must: the video is playing' --expect 'should: captions are visible'
```

Deterministic: reads `<video>` `currentTime`/`readyState`/`textTracks`. See
[Streaming / temporal](use-cases/streaming.md).

## Drive the loop from your own agent

```python
from agentvision import analyze, NextAction

async def build_until_right(edit_fn, source, brief=None, max_steps=4):
    for _ in range(max_steps):
        signal = (await analyze(source, brief=brief)).to_handoff()
        if signal.next_action == NextAction.DONE:
            return True
        edit_fn(todo=signal.todo, questions=signal.open_questions)   # your fix step
    return False
```

See [Eyes → brain (handoff)](handoff.md).

## Air-gapped / no-egress

```bash
agentvision check ./report.html --quiet      # local backend: DOM/CV/OCR, nothing leaves the box
```

The `local` backend never makes a network call. See [Backends](backends.md).

## Responsive contact sheet & visual regression

```bash
agentvision sheet ./index.html --breakpoints 375,768,1280,1920 -o sheet.png
agentvision baseline ./index.html --name home      # capture once
agentvision regress  ./index.html --name home      # later: fail on drift
```
