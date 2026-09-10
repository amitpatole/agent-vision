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
| `auth_header_env` | `AGENTVISION_AUTH_HEADER_ENV` | `None` | **Name** of an env var holding an `Authorization` header value (e.g. `Bearer …`). Attached to **same-origin requests only** (never leaked to a cross-origin CDN/analytics host). URL sources only; forces ephemeral. |
| `http_credentials_env` | `AGENTVISION_HTTP_CREDENTIALS_ENV` | `None` | **Name** of an env var holding `user:password` for HTTP Basic, scoped to the target origin. URL sources only; forces ephemeral. |
| `interactions` | _(library / CLI only)_ | `[]` | Ordered pre-capture steps (closed vocabulary — click / hover / fill / click_at / …) to reveal a popup/panel/tooltip before grading. Requires a single viewport. **Not** settable by a remote REST/MCP caller. |
| `allow_mutations` | `AGENTVISION_ALLOW_MUTATIONS` | `False` | While interactions run, non-GET requests (POST/PUT/PATCH/DELETE) are **blocked** so clicking a live app can't write. Set `True` only when a step legitimately needs a write (e.g. a popup whose data loads via POST). |
| `max_interactions` | `AGENTVISION_MAX_INTERACTIONS` | `20` | Cap on the number of interaction steps (runaway/DoS bound). |
| `interaction_step_timeout_ms` | `AGENTVISION_INTERACTION_STEP_TIMEOUT_MS` | `8000` | Per-step ceiling (hard-clamped to 30 s). |
| `motion_frames` | `AGENTVISION_MOTION_FRAMES` | `6` | Frames sampled evenly across a **local motion file** (video / animated GIF) before grading over time. |
| `motion_decode_timeout_s` | `AGENTVISION_MOTION_DECODE_TIMEOUT_S` | `30.0` | Hard timeout per ffmpeg invocation (process-group killed on expiry). |
| `allow_motion_render` | `AGENTVISION_ALLOW_MOTION_RENDER` | `True` | Decode local motion media with ffmpeg. **Off on the REST service** — a media decoder is an attack surface on untrusted bytes. |
| `allow_screen_capture` | `AGENTVISION_ALLOW_SCREEN_CAPTURE` | `True` | Allow live desktop capture via `xdg-desktop-portal` (source `desktop:` / `screen:`). **Off on the REST service** — a remote caller must never grab the host's screen. The portal still prompts for consent on every capture. |
| `allow_screen_capture_egress` | `AGENTVISION_ALLOW_SCREEN_CAPTURE_EGRESS` | `False` | Allow sending a live desktop capture to a **non-local (cloud)** vision backend. **Fail-closed** — refused unless explicitly `True` (CLI `--allow-egress`, MCP `allow_egress=True`). The `local` backend never egresses. |
| `screen_capture_interactive` | `AGENTVISION_SCREEN_CAPTURE_INTERACTIVE` | `False` | Let the portal prompt you to pick the area/window/screen; when `False`, the portal captures per its default (typically the whole screen). Consent is prompted either way. |
| `screen_capture_timeout_s` | `AGENTVISION_SCREEN_CAPTURE_TIMEOUT_S` | `60.0` | Ceiling (bounded 0 < t ≤ 300) on waiting for the portal permission prompt before failing closed, so an unanswered prompt can't hang. |
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

For a **token- or header-gated** app (URL sources), skip the session file and pass the secret by
env-var name — the value is attached only to same-origin requests, so it can't leak to a
third-party subresource host:

```bash
export APP_TOKEN="Bearer $(cat ~/.config/myapp/token)"
agentvision check https://app.example.com/dashboard --auth-header-env APP_TOKEN
# HTTP Basic instead:
export APP_BASIC="alice:$(cat ~/.config/myapp/pw)"
agentvision check https://app.example.com/ --http-credentials-env APP_BASIC
```

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

## Grading local motion media (video files & animated GIFs)

The eyes grade **motion over time**, not just a single frame — so a local video file
(`.mp4`/`.webm`/`.mov`/`.m4v`/`.avi`/`.mkv`) or an **animated GIF** is sampled into frames and
fed to the temporal grader (`watch`), the same path used for a `<video>` on a page. This closes
two silent failures: a video handed to the browser rendered **blank** (a misleading `blank
render` FAIL), and an animated GIF was flattened to **frame 0** and graded as a still (so every
motion/story requirement failed as "not depicted").

```bash
# grade a motion file offline — no key, no egress (frames sampled across the whole clip):
agentvision check ./promo.mp4            # deterministic motion/black/dead-export signals
agentvision analyze ./promo.gif          # + a time-aware vision pass (with a backend key)
agentvision watch  ./promo.mp4 --frames 8   # explicit temporal form; --frames overrides
```

- **`analyze` / `check` / `watch` auto-detect** motion inputs and film-strip them. A **single-frame
  GIF stays a still** (back-compat); pass `--source-type image` to deliberately grade an animated
  GIF's first frame.
- **Sampling spans the full duration** (default `motion_frames=6`) so the story start → middle →
  end is graded, not one arbitrary window. `--frames N` overrides.
- **Deterministic checks (no LLM):** a motion file that **doesn't move** fails as a dead/static
  export; a `loops_cleanly` signal reports whether the first and last frames match. Findings are
  grounded with a **frame index**.
- **Dependencies:** animated GIFs need nothing extra; **video needs ffmpeg** — install it
  (`dnf install ffmpeg` / `apt install ffmpeg`) or `pip install 'agentvision[motion]'` (bundles a
  static binary). `agentvision doctor` reports a **Motion (ffmpeg)** line. See
  [Security → Motion media](security.md#motion-media-video-gif-decode) for the decode hardening.

## Live desktop screen capture

AgentVision can grade the **live desktop** — not just an artifact you hand it. The eyes become
**sight**: the agent looks at the screen *right now* and answers a question about it. Use the
`desktop:` / `screen:` source, the [`agentvision screen`](cli.md#agentvision-screen) command, the
library (`analyze("desktop:", …)`), or the MCP `capture_screen` tool.

```bash
agentvision screen --ask "is an error dialog open?" --backend local   # offline, no egress
```

- **Portal consent (the real boundary).** Capture goes through the freedesktop
  `xdg-desktop-portal` **Screenshot** interface, which shows a permission prompt on the desktop.
  **Nothing is captured without your approval** — a denied/cancelled/unanswered prompt fails closed.
- **Consent ≠ egress.** The portal authorizes the *capture*; sending the frame to a **cloud**
  backend is a *separate* consent. It is **refused by default** (`allow_screen_capture_egress`) —
  pass `--allow-egress` (CLI) / `allow_egress=True` (MCP) to opt in. `--backend local` never
  egresses (deterministic, offline grade).
- **Confidential by default.** A desktop capture is always **ephemeral** — the screenshot is
  rendered into a throwaway temp dir wiped on exit and never written to `~/.cache/agentvision`;
  the portal's own output file is deleted after it is read.
- **Full screen vs. pick.** `screen_capture_interactive` (CLI `--interactive`) lets the portal
  prompt you to choose a window/area; the default captures the whole screen. Consent either way.
- **Not on the REST service.** `allow_screen_capture` is forced **off** for `agentvision serve` —
  a remote caller can never capture the host's screen.
- **Dependencies:** the `[desktop]` extra (`pip install 'agentvision[desktop]'`, bundles
  `jeepney`) plus a running `xdg-desktop-portal` on the OS. `agentvision doctor` reports a
  **Screen capture (portal)** line. See
  [Security → Screen capture](security.md#live-desktop-screen-capture) for the hardening.

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

