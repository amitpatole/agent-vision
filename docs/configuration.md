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
| `cache_dir` | `AGENTVISION_CACHE_DIR` | `/home/amitpatole/.cache/agentvision` |  |
| `session_ttl_s` | `AGENTVISION_SESSION_TTL_S` | `604800` |  |
| `rest_enabled_backends` | `AGENTVISION_REST_ENABLED_BACKENDS` | `['local']` |  |

## API keys & key files

Each backend's key resolves from its env var **or** a key file at `~/.config/<Provider>/key` (`Anthropic`, `OpenAI`, `Google`, `ollama`). Keys are read once, never logged or written to any cache/report.

## REST service & auth

Knobs for `agentvision serve` (see [Swarms & scaling](scaling.md) for deployment).

| Setting | Env var | Default | Notes |
|---|---|---|---|
| `api_token` | `AGENTVISION_API_TOKEN` | _none_ | Bearer token for the REST service. **You generate it** (there's no default); required for any non-loopback bind. |
| `max_concurrent_renders` | `AGENTVISION_MAX_CONCURRENT_RENDERS` | `4` | Per-process cap on simultaneous renders. Scale by adding replicas. |
| `max_request_bytes` | `AGENTVISION_MAX_REQUEST_BYTES` | `8388608` | Request-body cap (header **and** stream). |
| `request_timeout_s` | `AGENTVISION_REQUEST_TIMEOUT_S` | `120` | Per-request work bound. |
| `rest_enabled_backends` | `AGENTVISION_REST_ENABLED_BACKENDS` | `['local']` | Backends a client may request per call. |

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

