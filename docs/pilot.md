# Pilot guide: media and communications

This guide is for a team that wants to try AgentVision inside a real media or communications
pipeline before relying on it. The pilot is **advisory**: AgentVision grades every artifact and
reports what it finds, but it does not block a release. You measure its accuracy on your own
work first, then decide where to turn on gating.

## What the pilot covers

AgentVision grades things that render to pixels. In a media company that means:

- **Agent-built and human-built web surfaces**: player pages, programme guides, article
  templates, newsletters, promo landing pages.
- **Marketing and social output**: social cards, promo stills, animated GIFs and short promo
  videos. For motion files it checks whether the animation actually made it into the export.
- **Documents**: PDFs and slide decks, for example a rate card or a press pack.

It does **not** replace broadcast quality control. It does not measure loudness, caption timing,
colour space or frame-accurate black and freeze detection. Keep your existing QC tools for
playout and delivery.

## Deployment shape

Run everything inside your network. Nothing needs to leave it.

The artifact goes from your CI job or agent to AgentVision, which runs its deterministic checks
and sends the screenshot to a vision model on your own GPU. One report comes back.

1. **Deterministic checks always run locally.** Contrast, overflow, clipping, overlap, broken
   images, blank renders, visible error copy and typos come from the DOM, computer vision and
   OCR. They need no key and make no network calls.
2. **Semantic checks use a vision model on your own GPU.** Point AgentVision at a self-hosted
   Ollama server. No key is needed, and the Ollama Cloud key is never sent to it:

    ```bash
    export AGENTVISION_OLLAMA_BASE_URL=http://gpu-box.internal:11434/v1
    export AGENTVISION_OLLAMA_MODEL=qwen2.5vl:7b
    agentvision analyze page.html --backend ollama
    ```

3. **Pin the backend.** If no backend is named, `analyze` and `conform` pick the first cloud
   provider whose key is present on the host, so a stray `OPENAI_API_KEY` sends screenshots
   to that provider. Set `AGENTVISION_VISION_BACKEND=ollama` (or `local`) on every grader
   host, and keep cloud keys off those hosts. The `check` command never sends anything out.
4. **Install OCR on every grader host.** Without tesseract the typo and quoted-text checks
   cannot run. `agentvision doctor` reports it. If OCR is installed but fails, the report now
   says so with an ERROR rather than passing quietly.

## Advisory CI

Use the GitHub Action in advisory mode. It never fails the build. A FAIL or an error becomes a
warning annotation, and the full report goes to the job summary:

```yaml
- uses: amitpatole/agent-vision@v0.13.0
  with:
    source: dist/newsletter.html
    command: check
    mode: advisory
    expect: |
      must: a "Subscribe" button is visible
```

The Action ignores any `.env` file in the checkout, because a pull request could plant one.

## Write briefs the deterministic layer can check

Put the exact text you expect in quotes. A quoted requirement is checked against the rendered
text, with no model involved:

| Brief | Who decides |
|---|---|
| `must: a "Subscribe" button is visible` | OCR and DOM text. Deterministic. |
| `must: a Subscribe button is visible` | Only the vision model. Small local models get this wrong (see the benchmark). |

## House vocabulary

The typo check accepts British and other Commonwealth spellings by default. Add your show,
talent and brand names so they are not flagged:

```bash
export AGENTVISION_SPELL_ALLOW_FILE=/etc/agentvision/vocabulary.txt   # one name per line
```

## Benchmark

A small labelled corpus ships in `bench/`. It has 22 self-contained cases themed on media work:
player pages, TV schedules, headlines, carousels, newsletters and social cards. Thirteen cases
carry one known defect and nine are clean. Run it yourself:

```bash
python bench/run.py --backend local
python bench/run.py --backend ollama --model qwen2.5vl:7b --base-url http://gpu-box:11434/v1
python bench/run.py --summarize
```

Measured on 2026-10-22. The vision models ran on one 12 GB RTX 3500 Ada with Ollama 0.34.2.
Rendering ran on a separate 4-core host. Times include rendering.

| Backend | Defects flagged | Right issue kind | Found by the model itself | Clean pages passed | Clean pages falsely failed | Unparseable replies | Median time |
|---|---|---|---|---|---|---|---|
| `local` (no model) | 12 of 13 | 11 of 13 | n/a | 8 of 9 | 0 of 9 | n/a | 2.8 s |
| `qwen2.5vl:7b` | 12 of 13 | 12 of 13 | 4 of 13 | 8 of 9 | 1 of 9 | 0 of 22 | 5.3 s |
| `gemma4:12b-it-qat` | 12 of 13 | 12 of 13 | 2 of 13 | 7 of 9 | 1 of 9 | 5 of 22 | 32.2 s |
| `llama3.2-vision:11b` | did not run | | | | | | |

`llama3.2-vision:11b` would not load on Ollama 0.34.2, which no longer supports its `mllama`
architecture. All 22 cases came back as explicit errors and none graded as a pass.

What the numbers say:

- **The deterministic checks do most of the work.** With no model at all they report the right
  issue on 11 of 13 defects and never fail a clean page. One clean page grades WARN rather than
  PASS. Its brief asks for "a Subscribe button" without quotes, and the offline checks
  correctly say they cannot judge a button.
- **A vision model adds judgement but also mistakes.** `qwen2.5vl:7b` caught the unquoted
  missing-button requirement, but on the clean twin it insisted the visible Subscribe button was
  missing. In an earlier run on the same pages it made the opposite mistake. With the label
  quoted (`"Subscribe"`), both models graded both pages correctly, because the deterministic
  text check decides. Treat model findings as advisory and quote the text you require.
- **Neither model caught low-contrast text baked into a social-card PNG.** Raster contrast is a
  known gap for both layers today.
- **`gemma4:12b-it-qat` is six times slower and less reliable here.** Five of its replies were
  not valid JSON. Each one is reported as a WARNING, never a silent pass.

**Recommendation for the pilot:** run `check` (deterministic) everywhere, and add `analyze` with
`qwen2.5vl:7b` on surfaces where layout judgement matters. Quote every required text.


## Acceptance criteria

Agree on these with the pilot team before you start, and measure them on your own artifacts:

| Criterion | Suggested bar |
|---|---|
| Clean artifacts falsely failed | Under 5% over the pilot period |
| Known defects caught | At least 80% on a labelled sample of your real defects |
| Grading time per artifact | Under 30 seconds with the vision model |
| Silent passes | None. Every skipped check must show up in the report |

Turn on `mode: gate` for one surface only once it meets the bar on your own data. Start with
the deterministic `check` command, which is the most predictable.

## Known limits

- Content inside web components (shadow DOM) and iframes is not covered by the DOM checks.
  OCR and the vision model still see it in the screenshot.
- Contrast inside a raster image, such as a social card PNG, is not measured deterministically.
  Only the vision model can catch it.
- Unquoted requirements depend entirely on the vision model.
- Text that only reads thanks to a `text-shadow` halo, such as a white headline over a bright
  photo, is reported as a warning to check by eye. A scrim behind the text clears it.
- Text covered by an overlay, such as a cookie banner, a sticky bar or a paywall fade, is
  reported as an overlap warning, not as a contrast failure.
- The DOM checks have a time budget and an element cap. A very large page that hits either is
  graded as an ERROR, not a pass. Raise `dom_budget_ms` or `dom_max_elements` for such pages.
