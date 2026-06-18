# Quickstart

## Install

```bash
pip install "agentvision[render]"        # rendering + offline local loop (no key)
# or everything (all backends + adapters):
pip install "agentvision[all]"
```

Install the Chromium browser used for rendering:

```bash
playwright install chromium
```

### System dependencies

Chromium needs OS libraries that `playwright install` does **not** install.

- **Debian/Ubuntu:** `playwright install --with-deps chromium`
- **RHEL/CentOS/Fedora** (no `--with-deps` support):

  ```bash
  sudo dnf install -y nss nspr atk at-spi2-atk at-spi2-core cups-libs libdrm \
    mesa-libgbm libxkbcommon libXcomposite libXdamage libXrandr libXfixes \
    libXrender pango cairo alsa-lib gtk3
  ```

- **Optional extras:** `tesseract-ocr tesseract-ocr-eng` (OCR), `poppler-utils` (PDF).

Verify everything:

```bash
agentvision doctor          # attempts a real Chromium launch; lists any missing libs
agentvision doctor --fix    # installs the Chromium browser binary
```

Or skip all of this with the bundled **Dockerfile** (deps baked in):

```bash
docker build -t agentvision .
docker run --rm -v "$PWD:/work" agentvision demo
```

## First run (no API key)

```bash
agentvision demo
```

You'll see a broken page get a **FAIL** report (overflow, low contrast, broken image),
then the fixed version reach **PASS** with a "what changed" narrative.

## Everyday use

```bash
agentvision check  ./index.html --json          # structural checks, no key
agentvision analyze ./index.html --backend anthropic   # + semantic critique (needs key)
agentvision loop   ./index.html --max-iter 3
agentvision sheet  ./index.html
agentvision baseline ./index.html --name home && agentvision regress ./index.html --name home
```

Set a key to enable semantic analysis:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # or OPENAI_API_KEY / GOOGLE_API_KEY
```
