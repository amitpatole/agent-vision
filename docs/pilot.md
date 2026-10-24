# Pilot guide: media and communications

This guide is for a team that wants to try AgentVision inside a real media or communications
pipeline before relying on it. The pilot is **advisory**: AgentVision grades every artifact and
reports what it finds, but it does not block a release. You measure its accuracy on your own
work first, then decide where to turn on gating.

## Run a pilot with us

We are looking for one or two media or communications teams to run this pilot with. It is early,
so you would be shaping it, not buying something finished.

What we would ask of you:

- **One real pipeline stage to watch.** AgentVision runs in advisory mode, so nothing is blocked
  and nothing in your release process changes.
- **A few weeks of your normal output.** Web pages, promo stills, social cards, short promo
  videos or documents, whatever that stage already produces.
- **A couple of your own people to mark the results.** They say which artifacts really had a
  defect, clean ones included. Without that, an accuracy number tells you nothing, and it is the
  only way to find out whether gating is safe for you.

What you would get:

- **A report on your own artifacts** against the [acceptance criteria](#acceptance-criteria)
  below, including every clean page it wrongly failed.
- **Fixes for what you hit.** Defects and false alarms you find are fixed upstream and show up in
  the [changelog](https://github.com/amitpatole/agent-vision/blob/main/CHANGELOG.md).
- **The same shadow-mode setup for audio.** AgentVision only grades what renders to pixels. For
  loudness, A/V sync and delivery specs, [Verel's pilot mode](https://amitpatole.github.io/verel/pilot/)
  records every grader's verdict in one tamper-evident log, so you can pilot picture and sound
  together.

To start, [open an issue](https://github.com/amitpatole/agent-vision/issues/new?title=Pilot%3A%20%3Cyour%20team%3E)
titled `Pilot: <your team>` and tell us three things: which pipeline stage, roughly how many
artifacts a week it produces, and whether screenshots are allowed to leave your network. That
last answer decides which backend you use (see [Deployment shape](#deployment-shape)).

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

   If your policy allows screenshots to leave the network, Ollama Cloud grades more
   accurately than any model that fits a 12 GB card (see the [benchmark](#benchmark)). It is
   the default base URL and needs `OLLAMA_API_KEY`:

    ```bash
    export AGENTVISION_VISION_BACKEND=ollama          # model defaults to kimi-k2.7-code
    agentvision analyze page.html
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
- uses: amitpatole/agent-vision@v0.14.0
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

Measured on 2026-10-23, after the 0.14.0 grading fixes. Self-hosted models ran on one 12 GB
RTX 3500 Ada with Ollama 0.34.2. Cloud models ran on the Ollama Cloud subscription, three or
four at a time. Rendering ran on a separate 4-core host, so times include rendering and some
contention between parallel runs. Each row is one run of all 22 cases unless it says otherwise.

| Backend | Where | Defects flagged | Right issue kind | Found by the model itself | Clean pages passed | Clean pages falsely failed | Unparseable replies | Median time |
|---|---|---|---|---|---|---|---|---|
| `local` (no model) | this host | 12 of 13 | 11 of 13 | n/a | 8 of 9 | 0 of 9 | n/a | 1.8 s |
| **`kimi-k2.7-code`** (3 runs) | cloud | **39 of 39** | **39 of 39** | 25 of 39 | **27 of 27** | **0 of 27** | **0 of 66** | 7.0 s |
| `deepseek-v4.1-flash` (3 runs) | cloud | 39 of 39 | 39 of 39 | 22 of 39 | 21 of 27 | 1 of 27 | 0 of 66 | 4.5 s |
| `kimi-k2.6` | cloud | 13 of 13 | 13 of 13 | 4 of 13 | 9 of 9 | 0 of 9 | 0 of 22 | 15.9 s |
| `minimax-m3` | cloud | 13 of 13 | 12 of 13 | 2 of 13 | 9 of 9 | 0 of 9 | 0 of 22 | 7.0 s |
| `mistral-large-4` | cloud | 13 of 13 | 13 of 13 | 6 of 13 | 9 of 9 | 0 of 9 | 1 of 22 | 27.1 s |
| `minimax-m3.1-flash` | cloud | 13 of 13 | 13 of 13 | 3 of 13 | 8 of 9 | 0 of 9 | 0 of 22 | 6.6 s |
| `glm-5.3-flash` | cloud | 13 of 13 | 12 of 13 | 4 of 13 | 8 of 9 | 0 of 9 | 0 of 22 | 9.2 s |
| `kimi-k3` | cloud | 12 of 13 | 12 of 13 | 4 of 13 | 8 of 9 | 0 of 9 | 0 of 22 | 6.7 s |
| `deepseek-v4.1-flash:1017` | cloud | 13 of 13 | 12 of 13 | 6 of 13 | 5 of 9 | 0 of 9 | 0 of 22 | 5.3 s |
| `muse-spark-open` | cloud | 13 of 13 | 13 of 13 | 3 of 13 | 6 of 9 | 1 of 9 | 0 of 22 | 8.4 s |
| `gemma4:31b` | cloud | 13 of 13 | 13 of 13 | 11 of 13 | 6 of 9 | 3 of 9 | 0 of 22 | 3.2 s |
| `mistral-large-3:675b` | cloud | 13 of 13 | 12 of 13 | 11 of 13 | 0 of 9 | 8 of 9 | 0 of 22 | 7.0 s |
| `qwen2.5vl:7b` | 12 GB GPU | 12 of 13 | 12 of 13 | 4 of 13 | 8 of 9 | 0 of 9 | 3 of 22 | 3.7 s |
| `gemma4:12b-it-qat` | 12 GB GPU | 12 of 13 | 12 of 13 | 3 of 13 | 9 of 9 | 0 of 9 | 1 of 22 | 32.9 s |
| `llama3.2-vision:11b` | neither | did not run | | | | | | |
| `clef:27b` | cloud | did not run | | | | | | |

Clean pages that were neither passed nor falsely failed graded WARN. An unparseable reply also
grades WARN, so it can still count as a flagged defect even though the model said nothing useful.
Read the unparseable column next to the defect column.

Two models could not be measured. `llama3.2-vision:11b` will not load on Ollama 0.34.2, which
no longer supports its `mllama` architecture, and Ollama Cloud does not offer it. `clef:27b` is a
decision model that Ollama Cloud serves only on its own `/v1/systemone` endpoint, not on the
chat endpoint AgentVision uses.

What the numbers say:

- **The deterministic checks do most of the work.** With no model at all they report the right
  issue on 11 of 13 defects and never fail a clean page. One clean page grades WARN rather than
  PASS. Its brief asks for "a Subscribe button" without quotes, and the offline checks
  correctly say they cannot judge a button.
- **`kimi-k2.7-code` is the strongest grader we measured.** Over three runs it flagged every
  defect, named the right issue kind every time, passed every clean page and never returned
  an unparseable reply. It is the default Ollama model from 0.14.0.
- **Single runs vary.** `deepseek-v4.1-flash` passed 8, 7 and then 6 of the 9 clean pages on
  three runs of the same corpus. `qwen2.5vl:7b` went from 0 to 3 unparseable replies between
  two runs. Run a candidate model several times before you trust its row.
- **Some models find more and also accuse more.** `gemma4:31b` and `mistral-large-3:675b`
  found the most defects on their own, 11 of 13 each, but failed 3 and 8 of the 9 clean pages.
  On `chart_ok` both object that the bar chart has no value axis. That page is labelled clean,
  so it is scored as a false fail. It is a reasonable design critique, and the reason to keep
  model findings advisory.
- **Thinking models need a larger completion budget.** At the old fixed limit of 2048 tokens,
  `kimi-k2.7-code` was cut off mid-reply on 1 to 4 pages per run, and `kimi-k2.6` on 10 of 22.
  With the 0.14.0 default of 8192 (`AGENTVISION_OLLAMA_MAX_TOKENS`) both dropped to zero.
- **Neither layer catches low-contrast text baked into a social-card PNG.** Raster contrast is
  a known gap today.

**Recommendation for the pilot:** run `check` (deterministic) everywhere. Add `analyze` on
surfaces where layout judgement matters. If screenshots may leave your network, use Ollama Cloud
with the default `kimi-k2.7-code`. If they may not, use `qwen2.5vl:7b` on your own GPU, the
best self-hosted option here. Quote every required text.

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
