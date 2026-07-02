# Configuration

Settings resolve in order: **explicit kwargs → environment variables → a `.env` file → defaults**. Every field is an env var with the `AGENTVISION_` prefix (e.g. `AGENTVISION_NAV_WAIT=load`); provider API keys use their conventional names.

```python
from agentvision import load_settings
settings = load_settings(vision_backend='anthropic', settle_ms=800)
```

## Settings

| Setting | Env var | Default | Description |
|---|---|---|---|
| `vision_backend` | `AGENTVISION_VISION_BACKEND` |  | anthropic\|openai\|gemini\|local |
| `anthropic_model` | `AGENTVISION_ANTHROPIC_MODEL` | `'claude-haiku-4-5'` |  |
| `openai_model` | `AGENTVISION_OPENAI_MODEL` | `'gpt-4o-mini'` |  |
| `gemini_model` | `AGENTVISION_GEMINI_MODEL` | `'gemini-2.0-flash'` |  |
| `ollama_model` | `AGENTVISION_OLLAMA_MODEL` | `'gemma3:27b'` |  |
| `ollama_base_url` | `AGENTVISION_OLLAMA_BASE_URL` | `'https://ollama.com/v1'` |  |
| `anthropic_api_key` | `ANTHROPIC_API_KEY` |  | Provider API key *(secret — never logged)* |
| `openai_api_key` | `OPENAI_API_KEY` |  | Provider API key *(secret — never logged)* |
| `google_api_key` | `GOOGLE_API_KEY` |  | Provider API key *(secret — never logged)* |
| `ollama_api_key` | `OLLAMA_API_KEY` |  | Provider API key *(secret — never logged)* |
| `default_viewport_width` | `AGENTVISION_DEFAULT_VIEWPORT_WIDTH` | `1280` |  |
| `default_viewport_height` | `AGENTVISION_DEFAULT_VIEWPORT_HEIGHT` | `800` |  |
| `device_scale` | `AGENTVISION_DEVICE_SCALE` | `1.0` |  |
| `full_page` | `AGENTVISION_FULL_PAGE` | `False` |  |
| `render_timeout_s` | `AGENTVISION_RENDER_TIMEOUT_S` | `60.0` |  |
| `nav_wait` | `AGENTVISION_NAV_WAIT` | `'load'` |  |
| `settle_ms` | `AGENTVISION_SETTLE_MS` | `400` |  |
| `freeze_animations` | `AGENTVISION_FREEZE_ANIMATIONS` | `True` |  |
| `canvas_settle_ms` | `AGENTVISION_CANVAS_SETTLE_MS` | `1500` |  |
| `vision_max_edge_px` | `AGENTVISION_VISION_MAX_EDGE_PX` | `2000` |  |
| `crop_visual_claims` | `AGENTVISION_CROP_VISUAL_CLAIMS` | `True` |  |
| `max_visual_crops` | `AGENTVISION_MAX_VISUAL_CROPS` | `3` |  |
| `vision_full_coverage` | `AGENTVISION_VISION_FULL_COVERAGE` | `True` |  |
| `max_vision_tiles` | `AGENTVISION_MAX_VISION_TILES` | `6` |  |
| `watch_frames` | `AGENTVISION_WATCH_FRAMES` | `5` |  |
| `watch_interval_ms` | `AGENTVISION_WATCH_INTERVAL_MS` | `600` |  |
| `allow_url_rendering` | `AGENTVISION_ALLOW_URL_RENDERING` | `True` |  |
| `block_private_networks` | `AGENTVISION_BLOCK_PRIVATE_NETWORKS` | `True` |  |
| `allow_file_scheme` | `AGENTVISION_ALLOW_FILE_SCHEME` | `False` |  |
| `file_root` | `AGENTVISION_FILE_ROOT` | `None` | Confine all local file reads beneath this directory (path-traversal hardening for untrusted/REST callers); reads that escape it are refused. `None` = unrestricted (trusted CLI/library use). |
| `cache_dir` | `AGENTVISION_CACHE_DIR` | `/home/amitpatole/.cache/agentvision` |  |
| `session_ttl_s` | `AGENTVISION_SESSION_TTL_S` | `604800` |  |
| `ephemeral` | `AGENTVISION_EPHEMERAL` | `False` | Render into a throwaway temp dir wiped at the end of the run — nothing persists to the on-disk cache. For confidential inputs. The CLI `--no-cache` flag and the `ephemeral_cache()` context manager both turn this on. |
| `storage_state` | `AGENTVISION_STORAGE_STATE` | `None` | Path to a Playwright `storage_state` JSON (cookies + localStorage) so the renderer starts **authenticated** and grades the app, not the login wall. Accepts only a **path** — never inline credentials. Setting it **forces ephemeral mode** (the CLI passes `--no-cache`). The file *is* a live credential — keep it out of version control. |
| `interactions` | _(library / CLI only)_ | `[]` | Ordered pre-capture steps (closed vocabulary — click / hover / fill / click_at / …) to reveal a popup/panel/tooltip before grading. Requires a single viewport. **Not** settable by a remote REST/MCP caller. |
| `allow_mutations` | `AGENTVISION_ALLOW_MUTATIONS` | `False` | While interactions run, non-GET requests (POST/PUT/PATCH/DELETE) are **blocked** so clicking a live app can't write. Set `True` only when a step legitimately needs a write (e.g. a popup whose data loads via POST). |
| `max_interactions` | `AGENTVISION_MAX_INTERACTIONS` | `20` | Cap on the number of interaction steps (runaway/DoS bound). |
| `interaction_step_timeout_ms` | `AGENTVISION_INTERACTION_STEP_TIMEOUT_MS` | `8000` | Per-step ceiling (hard-clamped to 30 s). |
| `rest_enabled_backends` | `AGENTVISION_REST_ENABLED_BACKENDS` | `['local']` |  |

## API keys & key files

Each backend's key resolves from its env var **or** a key file at `~/.config/<Provider>/key` (`Anthropic`, `OpenAI`, `Google`, `ollama`). Keys are read once, never logged or written to any cache/report.

## Confidential inputs (ephemeral cache)

By default, renders and session state are cached under `cache_dir` (`~/.cache/agentvision`).
For a **confidential or sensitive artifact** you don't want touching the disk, run in ephemeral
mode — a throwaway temp dir (created `0700`) is used as the cache and **wiped when the run ends**
(even on error):

```bash
agentvision check confidential.pptx --no-cache      # CLI: any source command
export AGENTVISION_EPHEMERAL=true                    # or set it for the whole process
```

```python
from agentvision import analyze, ephemeral_cache, load_settings

with ephemeral_cache(load_settings()) as settings:
    report = await analyze("confidential.html", settings=settings)
# temp cache dir is removed here
```

Ephemeral mode keeps bytes off the persistent cache; it does **not** stop a cloud vision
backend from sending the render to a provider. For fully on-box processing, combine `--no-cache`
with `--backend local` (or just `check`).

## Authenticated & interactive rendering

Two knobs let the eyes grade an app that lives *behind a login* and *state that only appears
after you click* — e.g. a metrics popup that opens when you click a map heat-bin.

**Get past a login wall** — capture a Playwright `storage_state` once (out of band), then point
AgentVision at it. The renderer starts already authenticated and grades the app, not the login
page. If the session has expired (the page bounces to a login wall) AgentVision **refuses to
grade it** and errors, rather than returning a confident verdict about the login screen.

```bash
# 1) capture a session once (your own script, not committed — it holds live tokens):
#    context.storage_state(path="state.json") after logging in.
# 2) grade the authenticated app (storage_state forces ephemeral — nothing is cached):
agentvision check https://app.example.com/dashboard --storage-state ./state.json
```

> The state file **is** a live credential. Keep it out of version control
> (`echo 'state.json' >> .gitignore`) — see [Security](security.md#authenticated-rendering).

**Reach state behind an interaction** — pass an ordered list of steps (a closed vocabulary:
`click`, `hover`, `fill`, `fill_env`, `press`, `scroll_into_view`, `wait_for`, `wait_timeout`,
and `click_at` for `<canvas>` maps). Steps run **before** capture, so the revealed popup/panel is
what gets graded.

```bash
# open a popup, wait for it, then grade the result:
agentvision analyze https://app.example.com/map \
  --storage-state ./state.json \
  --interactions '[{"type":"click_at","selector":"#map","x":0.62,"y":0.40},
                   {"type":"wait_for","selector":".metrics-popup"}]'
```

`click_at` takes **fractional** coordinates (0–1) inside an element's box, so a canvas click
survives a layout shift. Interactions are **read-only by default**: while they run, non-GET
requests are blocked so clicking a live app can't submit or delete — pass `--allow-mutations`
only when a step legitimately needs a write. A step whose selector is missing or that times out
**fails closed** (errors) rather than grading the wrong, pre-interaction state. Interactions
require a single viewport and are **not** exposed to remote REST/MCP callers. Use `fill_env`
(never `fill`) for a password, so no secret is written into the steps JSON.

## REST service & auth

Knobs for `agentvision serve` (see [Swarms & scaling](scaling.md) for deployment).

| Setting | Env var | Default | Notes |
|---|---|---|---|
| `api_token` | `AGENTVISION_API_TOKEN` | _none_ | Bearer token for the REST service. **You generate it** (there's no default); required for any non-loopback bind. |
| `max_concurrent_renders` | `AGENTVISION_MAX_CONCURRENT_RENDERS` | `4` | Per-process cap on simultaneous renders. Scale by adding replicas. |
| `max_request_bytes` | `AGENTVISION_MAX_REQUEST_BYTES` | `8388608` | Request-body cap (header **and** stream). |
| `request_timeout_s` | `AGENTVISION_REQUEST_TIMEOUT_S` | `120` | Per-request work bound. |
| `rest_enabled_backends` | `AGENTVISION_REST_ENABLED_BACKENDS` | `['local']` | Backends a client may request per call. |
| `file_root` | `AGENTVISION_FILE_ROOT` | _none_ | Optional: confine any local-file read beneath this directory; traversal attempts are refused. The REST service already refuses bare-path/`file://` reads by default — set this if you deliberately serve files from one directory. |

**The auth token** is a shared secret of your choosing — AgentVision never issues or defaults
one. Generate a high-entropy value, export it on the server, and hand the **same** value to each
client (sent as `Authorization: Bearer <token>`, compared in constant time):

```bash
export AGENTVISION_API_TOKEN=$(openssl rand -hex 32)
# or: python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Loopback (`127.0.0.1`) is zero-config (no token). Binding any routable host without a token is
**refused at startup** — the service fails closed. Keep the token in your secret manager or env,
never in the repo; it is value-scrubbed from logs.

