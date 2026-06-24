# FAQ & troubleshooting

## Do I need an API key?

No. `agentvision check` and `--backend local` run fully offline (DOM geometry, computed-style
WCAG contrast, OCR/typos, broken-image & console capture) — no key, no network. A key only
adds the vision-LLM semantic critique on top.

## Which backend should I use?

- **`local`** — CI, air-gapped, fast structural checks; honest "uncertain" instead of guessing.
- **`anthropic`** (default), **`openai`**, **`gemini`** — semantic critique + intent grading.
- **`ollama`** — self-hosted/OSS multimodal (local or Ollama Cloud).

See [Backends](backends.md). The deterministic findings (DOM/OCR/CV) are precise everywhere;
vision-model findings are advisory.

## Chromium won't launch

```bash
agentvision doctor          # attempts a real launch + lists every missing system lib
agentvision doctor --fix    # installs the Chromium browser binary
```

On bare RHEL/CentOS, `playwright install-deps` is apt-only — `doctor` prints the exact `dnf`
line. Or use the bundled **Dockerfile**, which bakes the deps in.

## My live dashboard / SPA times out

Polling and websocket pages never go network-idle. The default `--nav-wait` is already `load`
(networkidle is bounded), but if you still hit a timeout: add `--settle-ms 800`, keep
`--freeze` on for canvas/WebGL, and raise `--render-timeout`.

## Why does a requirement come back "uncertain"?

The offline `local` backend can't judge visual/semantic intent — it grades quoted-text claims
deterministically (OCR/DOM) and reports everything else as `uncertain` rather than a false
PASS. Use a vision backend for semantic claims. See [Conformance](conformance.md).

## Are the bounding boxes pixel-accurate?

DOM/OCR/CV boxes are **precise** (`bbox_precise: true`). Vision-model boxes are **advisory**
(`bbox_precise: false`) — never marketed as pixel-accurate.

## How do I keep cost / tokens down?

Use `local` where you can; oversized screenshots are auto-downscaled before the LLM, and
full-coverage tiles are content-aware and capped (`max_vision_tiles`). The default model is
the cheap/fast `claude-haiku-4-5`.

## What gets sent where? (privacy)

Only the cloud backends send anything: a screenshot (base64) to the chosen provider. `local`
sends nothing. API keys are read once and never logged or written to any cache/report. See
[Configuration](configuration.md).

## How is this different from Percy / Playwright / Applitools?

It's **not** human-reviewed visual regression and **not** browser automation. It's a
**machine-graded critique loop an agent consumes to self-correct before claiming done** — a
verdict + actionable, coordinate-grounded issues. It complements those tools.

## It found something that isn't real / missed something

Vision findings are advisory and cross-checked against DOM/OCR ground truth (a "missing"
claim is suppressed when the element provably exists). If a *grounded* (DOM/OCR/CV) finding is
wrong, please [open an issue](https://github.com/amitpatole/agent-vision/issues) with the
artifact — that's the trustworthy path and we want it airtight.
