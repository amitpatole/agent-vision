# Try it yourself

A from-scratch, copy-paste walkthrough you can run in a couple of minutes — **no API key, no
account, no sample repo**. You'll give the eyes a page you wrote by hand, watch them mark
exactly what's wrong, fix it, and watch the verdict flip to **PASS**.

## 1. Install

```bash
pip install "agentvision[render]"     # rendering + the offline 'local' loop (no key)
playwright install chromium           # the browser used to render
```

Confirm rendering works (this attempts a real Chromium launch):

```bash
agentvision doctor
```

```text
AgentVision doctor
========================================
  ✓ Rendering (Chromium): Chromium launches
  ! OCR (tesseract): not found — install tesseract-ocr + tesseract-ocr-eng (optional)
  ✓ PDF (poppler): /usr/bin/pdftoppm
  ✓ Office docs (LibreOffice): /usr/bin/soffice

  Vision backends:
    ! anthropic (set ANTHROPIC_API_KEY to enable)
    ✓ local (offline, always available)
========================================
Ready. Try: agentvision demo
```

A `✓` on **Rendering (Chromium)** is all you need for this walkthrough — everything below uses
the offline `local` backend.

## 2. Write a deliberately broken page

Save this as `card.html`. It has three real defects: text that's too faint to read, a layout
wider than the viewport, and an image that doesn't exist.

```html
<!doctype html>
<html><head><meta charset="utf-8"><title>Pricing card</title></head>
<body style="margin:0;font-family:sans-serif">
  <div style="width:1600px;padding:24px">
    <h1 style="color:#cfcfcf">Pro plan</h1>
    <p style="color:#dcdcdc">Everything you need to ship faster.</p>
    <img src="badge.png" alt="popular badge">
    <a href="#" style="color:#bcd7ff">Start free trial</a>
  </div>
</body></html>
```

## 3. Let the eyes look

```bash
agentvision check card.html
```

`check` runs structural DOM/CV analysis only — no LLM, no key, no network. This is the **actual
output**:

```text
  FAIL  (checks)
  Structural checks found 5 issue(s).

  • [contrast] Low contrast (ratio 1.56, needs 3.0 for AA) on text 'Pro plan' [rgb(207, 207, 207) on rgb(255,255,255)] (background not solid — verify manually) @(24,45) (dom/low)
  • [contrast] Low contrast (ratio 1.37, needs 4.5 for AA) on text 'Everything you need to ship faster.' [rgb(220, 220, 220) on rgb(255,255,255)] @(24,104) (dom/low)
  • [contrast] Low contrast (ratio 1.47, needs 4.5 for AA) on text 'Start free trial' [rgb(188, 215, 255) on rgb(255,255,255)] @(147,138) (dom/low)
  • [overflow] Page content overflows horizontally by 368px (causes a horizontal scrollbar). (dom/high)
  • [broken_image] Broken image (failed to load): badge.png @(24,138) (dom/high)
```

Every issue is **grounded**: a `kind`, a coordinate (`@(x,y)`), the source that found it
(`dom`), and a confidence. Nothing is guessed — these are measured from the rendered page.

## 4. Fix it and look again

Replace `card.html` with a version that fixes all three: readable colors, a width that fits,
and no missing image.

```html
<!doctype html>
<html><head><meta charset="utf-8"><title>Pricing card</title></head>
<body style="margin:0;font-family:sans-serif">
  <div style="max-width:640px;padding:24px">
    <h1 style="color:#1b1a17">Pro plan</h1>
    <p style="color:#3a3a3a">Everything you need to ship faster.</p>
    <a href="#" style="color:#1746a2;font-weight:600">Start free trial</a>
  </div>
</body></html>
```

```bash
agentvision check card.html
```

```text
  PASS  (checks)
  Structural checks passed (no DOM/CV defects detected).

  No issues.
```

That **FAIL → PASS** arc is the whole idea: the agent (or you) ships only after the eyes
confirm the page actually looks right.

## 5. Machine-readable mode

For a CI gate or an agent, add `--quiet` to get JSON on stdout and a meaningful exit code
(`0` pass/warn · `2` fail · `3` error):

```bash
agentvision check card.html --quiet
```

```json
{
  "verdict": "pass",
  "summary": "Structural checks passed (no DOM/CV defects detected).",
  "issues": []
}
```

## Where to go next

- **[5-minute tutorial](tutorial.md)** — add semantic critique and grade against *intent*.
- **[Real-world scenarios](examples.md)** — runnable end-to-end demos with captured output.
- **[Quickstart](quickstart.md)** — full install matrix (system deps, Docker, OCR/PDF/Office).
- **[Workflows & agents](integrations.md)** — drop the eyes into CI or your agent's loop.
