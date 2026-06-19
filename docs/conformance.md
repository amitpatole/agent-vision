# Intent conformance — match the thought, not just avoid defects

By default AgentVision is a **defect detector**: it asks *"is anything broken?"* (overflow,
low contrast, broken images, typos). That's necessary but not sufficient. An artifact can be
flawless *and still be the wrong thing* — a clean infographic that shows the wrong stages, a
dashboard missing the panel you asked for, a generated image that ignored half the prompt.

**Conformance** adds the missing question: *"does this match what I set out to build?"* You
give AgentVision the **intent** (the thought), it forms an explicit checklist, grades the
render against it, and gates the verdict so **PASS means "matches intent"**, not merely
"defect-free".

## Three ways to express intent (combine freely)

| Source | How | Best for | Needs |
|---|---|---|---|
| **Brief** | `--brief "a 4-stage infographic, dark theme, title 'AgentVision'"` | quick, natural | a vision/LLM backend (extracts the checklist) |
| **Explicit checklist** | `--expect 'must: title reads "AgentVision"'` (repeatable) | determinism, CI, no-key | nothing (text claims grade via OCR) |
| **Reference image** | `--reference target.png` | "make it look like this" | a vision backend (compares the two images) |

Explicit claims take an importance prefix: `must:` (default — violation **fails**),
`should:` (violation **warns**), `nice:` (never escalates). Put exact required text in
**quotes** — those claims are graded deterministically against OCR, independent of any model.

## CLI

```bash
# Grade an artifact against intent
agentvision conform ./infographic.png \
  --brief "launch infographic for AgentVision" \
  --expect 'must: title reads "AgentVision"' \
  --expect 'should: shows 4 stages left to right' \
  --backend anthropic

# Any analyze/loop call can be conformance-aware
agentvision analyze ./dashboard.html --expect 'must: a "Checkout" button is visible'
agentvision loop ./page.html --brief "pricing page with 3 tiers" --max-iter 3
```

A `conform` run prints a per-requirement breakdown (`✓ satisfied`, `✗ violated`,
`? uncertain`) and exits non-zero on FAIL.

## The generative loop (AI images / infographics)

For a hand-written page the agent edits **code** between iterations. For a *generated*
artifact the fix is a better **prompt**. `agentvision generate` closes that loop:

```
generate → perceive → grade vs intent → refine the prompt → regenerate → … until it matches
```

The generator is **your** callable — AgentVision never bundles an image-gen dependency:

```python
# mypkg/gen.py
def make_image(prompt: str) -> str:        # returns a path to the produced image
    img = my_image_model.generate(prompt)  # OpenAI gpt-image, Qwen-Image, local SD, …
    img.save("/tmp/out.png")
    return "/tmp/out.png"
```

```bash
agentvision generate --generator mypkg.gen:make_image \
  --brief "minimalist infographic: render → see → fix, dark background, no typos" \
  --expect 'must: spelled correctly' --max-iter 4 -o final.png
```

Library form:

```python
from agentvision import Brief, GenerativeLoopSession

brief = Brief.from_inputs(text="…", expect=['must: title reads "AgentVision"'])
session = GenerativeLoopSession(brief, make_image, backend="anthropic")
history = await session.run(max_iter=4)
print(session.stop_reason)  # "matched intent" | "stuck" | "max-iter" | "cannot refine"
```

## How a requirement is graded (and why you can trust it)

In increasing order of trust:

1. **Vision** — the backend emits an `intent_mismatch` issue (citing `[#N]`) for each unmet
   requirement. Advisory, like all vision findings.
2. **OCR text-presence** — quoted-text requirements are decided by what Tesseract actually
   reads in the render. Model-independent ground truth; overrides the vision call.
3. **Verdict gate** — a violated `must` fails regardless of how the model scored it.

### Honesty / limits
- The **offline `local` backend** can't judge visual intent. It grades quoted-text claims via
  OCR and reports everything else as **`uncertain`** — never a false PASS.
- LLM-extracted checklists can over-specify. Extracted claims are surfaced; only `must` can
  fail; use the explicit checklist when you want full determinism.
- Don't grade a generated image with the **same** model that produced it if you can avoid it
  (it tends to rate itself kindly) — pick a different `--backend` for perception.

See also: [The Loop](the-loop.md) · [Backends](backends.md) · [Adapters](adapters.md).
