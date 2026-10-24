"""Configuration for AgentVision.

All settings resolve from (in order) explicit kwargs -> environment variables
(``AGENTVISION_*`` plus provider keys) -> a config file -> defaults. Credentials are
read here and nowhere else, and are never persisted or logged.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import platformdirs
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models.interaction import Interaction

APP_NAME = "agentvision"

# Default model per provider. Anthropic defaults to the cheap/fast Haiku because
# `analyze` runs frequently inside the loop; users can upgrade via config/env.
DEFAULT_MODELS = {
    "anthropic": "claude-haiku-4-5",
    # gpt-4o-mini shuts down 2027-01-14 and gemini-2.0-flash already returns 404. Both
    # replacements led their provider in the bench/ sweep over three runs each.
    "openai": "gpt-5.4-mini",
    "gemini": "gemini-3.5-flash-lite",
    # gemma3:27b was retired from Ollama Cloud on 2026-07-15; kimi-k2.7-code led the bench/
    # cloud sweep (3 runs: every defect flagged, no clean page failed, no unparseable reply).
    "ollama": "kimi-k2.7-code",
}

# Fallback key-file locations if the conventional env var is unset.
KEY_FILES = {
    "anthropic": Path.home() / ".config" / "Anthropic" / "key",
    "openai": Path.home() / ".config" / "OpenAI" / "key",
    "gemini": Path.home() / ".config" / "Google" / "key",
    "ollama": Path.home() / ".config" / "ollama" / "key",
}


def default_cache_dir() -> Path:
    return Path(platformdirs.user_cache_dir(APP_NAME))


class Settings(BaseSettings):
    """Runtime settings. Environment prefix: ``AGENTVISION_``.

    Provider API keys use their conventional env names (not the prefix) so they match
    what the provider SDKs already expect.
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENTVISION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Backend selection
    vision_backend: str | None = Field(default=None, description="anthropic|openai|gemini|local")
    anthropic_model: str = DEFAULT_MODELS["anthropic"]
    openai_model: str = DEFAULT_MODELS["openai"]
    gemini_model: str = DEFAULT_MODELS["gemini"]
    ollama_model: str = DEFAULT_MODELS["ollama"]
    ollama_base_url: str = "https://ollama.com/v1"
    # Thinking models spend part of the completion budget on reasoning; 2048 cut kimi-k2.7-code
    # off mid-JSON on busy pages. A cut-off reply still grades WARN, never PASS.
    ollama_max_tokens: int = Field(default=8192, ge=256, le=65536)
    # Same reason for the hosted providers: GPT-5+ and Gemini 2.5+ reason before answering, and
    # that comes out of the completion budget.
    openai_max_tokens: int = Field(default=8192, ge=256, le=65536)
    gemini_max_tokens: int = Field(default=8192, ge=256, le=65536)

    # Provider credentials (conventional names; never logged/persisted)
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    google_api_key: str | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    ollama_api_key: str | None = Field(default=None, validation_alias="OLLAMA_API_KEY")
    # Auth for a SELF-HOSTED Ollama behind a proxy. Deliberately separate from the cloud key so
    # a redirected base URL can never receive OLLAMA_API_KEY.
    ollama_self_hosted_key: str | None = Field(
        default=None, validation_alias="AGENTVISION_OLLAMA_SELF_HOSTED_KEY")

    # Rendering
    default_viewport_width: int = 1280
    default_viewport_height: int = 800
    device_scale: float = 1.0
    full_page: bool = False
    render_timeout_s: float = 60.0
    # Default to 'load' (not 'networkidle'): polling/websocket pages never go idle and
    # would hang. When networkidle IS requested it is bounded (see the renderer).
    nav_wait: str = "load"  # load|domcontentloaded|networkidle
    settle_ms: int = 400  # quiet wait after load so client-rendered data can populate
    freeze_animations: bool = True  # pause CSS animations + rAF before capture
    # When a <canvas> is present, let rAF run at least this long so a scene that BUILDS in the
    # rAF loop (three.js/WebGL/games) draws before we pause it ("settle-then-freeze").
    canvas_settle_ms: int = 1500
    vision_max_edge_px: int = 2000  # downscale oversized screenshots before the vision LLM
    # When grading intent on a page with charts/canvas/images, also send the vision model
    # focused FULL-RES crops of those regions (a downscaled whole page can't be judged well).
    crop_visual_claims: bool = True
    max_visual_crops: int = 3
    # Full-coverage vision: when the artifact is larger than the model-friendly edge, also
    # send FULL-RES tiles covering it (pixel-based, source-agnostic — works for any HTML/
    # image/PDF/canvas) so nothing is lost to downscaling. The eyes see everything.
    vision_full_coverage: bool = True
    max_vision_tiles: int = 6
    # Temporal verification (`watch`): sample frames over time to judge playback / loading /
    # transitions / liveness — for streaming UIs, video, live dashboards.
    watch_frames: int = 5
    watch_interval_ms: int = 600
    watch_max_frames: int = 60  # clamp caller-supplied frames (DoS bound)
    watch_max_interval_ms: int = 10_000
    # Local motion media (video files + animated GIFs): sampled into frames and fed to the
    # same temporal grader `watch` uses — never flattened to a still or handed to the browser.
    motion_frames: int = 6              # default frames sampled evenly across the duration
    motion_decode_timeout_s: float = 30.0  # hard timeout per ffmpeg invocation

    # DOM grading pass limits. Hitting either means some elements went unchecked, which is
    # graded as an ERROR (never a clean pass). Raise them for very large pages.
    dom_max_elements: int = 20_000
    dom_budget_ms: int = 4000

    # Renderer isolation / resource caps (untrusted pages drive Chromium)
    chromium_sandbox: bool = True  # keep the OS sandbox; disable only in a trusted/contained env
    max_viewport_px: int = 8000    # clamp viewport width/height (memory bound)
    max_device_scale: float = 4.0  # clamp device_scale (buffer = w*h*scale^2*4 bytes)
    # Vetting egress proxy bounds (per render): cap concurrent upstream connections and close
    # idle ones so a page can't open thousands of slow connections through the proxy.
    proxy_max_connections: int = 64
    proxy_idle_timeout_s: float = 30.0

    # Documents (PDF + Office/OpenDocument via LibreOffice). Multi-page is rasterized per page,
    # capped, then stacked into one composite primary image for analysis.
    document_max_pages: int = 30        # cap pages/slides rasterized (memory + token bound)
    document_max_page_px: int = 2000    # per-page raster width cap (px)
    document_raster_dpi: int = 120
    max_document_bytes: int = 50_000_000  # byte cap before handing a file to poppler/LibreOffice
    document_convert_timeout_s: float = 120.0  # hard timeout on the LibreOffice subprocess
    soffice_path: str | None = None     # explicit LibreOffice binary; else auto-detected

    # Safety
    allow_url_rendering: bool = True
    block_private_networks: bool = True
    allow_file_scheme: bool = False
    # Reading a local file path as a source (e.g. `analyze ./index.html`). Safe for CLI/library
    # (trusted local user); the REST service sets this False so a remote caller can't read host
    # files via a bare path like "/etc/passwd".
    allow_local_files: bool = True
    # Optional confinement root for local file sources. None = no restriction (trusted
    # CLI/library use). Set to a directory to confine all local file reads beneath it
    # (path-traversal hardening); reads that escape it are refused.
    file_root: Path | None = None
    # Rendering Office/OpenDocument files via LibreOffice (docx/pptx/xlsx/odt…). Enabled for
    # trusted local CLI/library use; the REST service sets this False — LibreOffice is a large
    # attack surface on untrusted input (macros/DDE/remote-template/OLE), so it is not exposed
    # to remote callers by default.
    allow_office_render: bool = True
    # Decoding local motion media (video/animated GIF) with ffmpeg. Enabled for trusted local
    # CLI/library use; the REST service sets this False — a media decoder is a meaningful
    # attack surface on untrusted bytes, so it is not exposed to remote callers by default.
    allow_motion_render: bool = True

    # Live desktop screen capture via the freedesktop screenshot portal (source `desktop:`).
    # Enabled for trusted local CLI/library use; the REST service sets this False — a remote
    # caller must never capture the host's screen. Every capture still prompts the user for
    # consent at the OS portal (that interactive approval is the real security boundary).
    allow_screen_capture: bool = True
    # Sending a live screen capture to a NON-local (cloud) vision backend is a separate egress
    # from the OS capture consent — the portal authorizes the capture, not shipping the frame to
    # a third party. Fail closed: a desktop capture + cloud backend is REFUSED unless this is
    # explicitly set True (CLI `--allow-egress`, MCP `allow_egress=True`). The `local` backend
    # never egresses and is always allowed.
    allow_screen_capture_egress: bool = False
    # When True, the portal lets the user pick the area/window/screen to capture; when False,
    # the portal captures per its default (typically the whole screen). Consent is prompted
    # either way.
    screen_capture_interactive: bool = False
    # Hard ceiling on how long to wait for the portal's Response (i.e. the user answering the
    # permission prompt) before failing closed, so an unanswered prompt can't hang forever.
    # Bounded (0 < t ≤ 300) so a caller can't set a multi-year self-hang or a negative value
    # that would escape the timeout handling as an unhandled error.
    screen_capture_timeout_s: float = Field(default=60.0, gt=0, le=300)

    # Authenticated rendering & pre-capture interaction (Phase 1)
    # Path to a Playwright storage_state JSON (cookies + localStorage) captured out-of-band, so
    # the renderer starts already logged in and grades the app, not the login wall. Accepts only
    # a PATH — never inline credentials. The file IS a live credential; keep it out of VCS.
    storage_state: Path | None = None
    # Origin-scoped auth for URL sources (Phase 3). Both hold the NAME of an env var, never the
    # secret itself. auth_header_env → the value becomes the `Authorization` header, attached
    # ONLY to same-origin requests (never leaked cross-origin to a CDN/analytics host).
    # http_credentials_env → an env var holding "user:password" for HTTP Basic, scoped to the
    # target origin. Setting either forces ephemeral mode.
    auth_header_env: str | None = None
    http_credentials_env: str | None = None
    # Ordered pre-capture steps (closed vocabulary; see models.interaction). Empty = none.
    interactions: list[Interaction] = Field(default_factory=list)
    # While interactions run, block non-GET requests (POST/PUT/PATCH/DELETE) unless enabled, so
    # clicking around a live authenticated app can't submit/delete/send by default (fail-safe).
    allow_mutations: bool = False
    max_interactions: int = 20             # cap the number of steps (DoS / runaway bound)
    interaction_step_timeout_ms: int = 8000  # per-step ceiling (clamped)

    # HTTP service (REST): bind + auth + DoS bounds
    api_token: str | None = Field(default=None, validation_alias="AGENTVISION_API_TOKEN")
    max_request_bytes: int = 8_000_000  # cap request bodies before buffering/rendering
    max_concurrent_renders: int = 4  # global semaphore so N requests can't spawn N browsers
    request_timeout_s: float = 120.0  # hard per-request ceiling above the render timeout

    # Workspace
    cache_dir: Path = Field(default_factory=default_cache_dir)
    session_ttl_s: float = 60 * 60 * 24 * 7  # 7 days
    # Ephemeral mode: render into a throwaway temp dir wiped at the end of the run, so a
    # confidential input is never persisted to the on-disk cache. Set via --no-cache (CLI),
    # AGENTVISION_EPHEMERAL=true, or the ephemeral_cache() context manager (library).
    ephemeral: bool = False

    # Spell-check vocabulary (offline OCR typo check). The base dictionary is US English;
    # spell_variants also accepts Commonwealth spellings (colour, centre, organise, ...).
    # House vocabulary — show, talent, brand names — comes from spell_allow_words and/or a
    # newline-delimited spell_allow_file (operator config only; size-capped when read).
    spell_variants: bool = True
    spell_allow_words: list[str] = Field(default_factory=list)
    spell_allow_file: Path | None = None
    spell_allow_file_max_bytes: int = 1_000_000

    # REST: only these backends may be selected per-request (allowlist)
    rest_enabled_backends: list[str] = Field(default_factory=lambda: ["local"])

    def model_for(self, backend: str) -> str:
        return {
            "anthropic": self.anthropic_model,
            "openai": self.openai_model,
            "gemini": self.gemini_model,
            "ollama": self.ollama_model,
        }.get(backend, "")

    def spell_vocabulary(self) -> frozenset[str]:
        """Lower-cased house vocabulary from ``spell_allow_words`` + ``spell_allow_file``.

        Fails closed on a bad file: it raises ConfigError rather than silently checking against
        a smaller vocabulary than the operator configured.
        """
        words = {w.strip().lower() for w in self.spell_allow_words if w.strip()}
        f = self.spell_allow_file
        if f is not None:
            words |= _read_vocab_file(Path(f), self.spell_allow_file_max_bytes)
        return frozenset(words)

    def key_for(self, backend: str) -> str | None:
        key = {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "gemini": self.google_api_key,
            "ollama": self.ollama_api_key,
        }.get(backend)
        # Fall back to a conventional key file (~/.config/<Provider>/key) if env is unset.
        if not key:
            f = KEY_FILES.get(backend)
            if f and f.exists():
                try:
                    key = f.read_text().strip() or None
                except OSError:
                    key = None
        if key:
            # Register the resolved value so it is scrubbed from any log line (defense-in-depth).
            from .logging import register_secret

            register_secret(key)
        return key


_VOCAB_CACHE: dict[tuple, frozenset[str]] = {}


def _read_vocab_file(path: Path, max_bytes: int) -> frozenset[str]:
    """Read a vocabulary file: a REGULAR file only (a FIFO/device would block or stream
    forever), capped in BYTES, opened non-blocking, cached by (path, inode, mtime, size)."""
    from .errors import ConfigError

    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except OSError as e:
        raise ConfigError(f"Cannot read spell_allow_file {str(path)!r}: {e}") from e
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ConfigError(f"spell_allow_file {str(path)!r} is not a regular file.")
        if st.st_size > max_bytes:
            raise ConfigError(f"spell_allow_file is {st.st_size} bytes, over "
                              f"spell_allow_file_max_bytes ({max_bytes}).")
        key = (str(path), st.st_ino, st.st_mtime_ns, st.st_size)
        if key in _VOCAB_CACHE:
            return _VOCAB_CACHE[key]
        data = os.read(fd, max_bytes + 1)
        if len(data) > max_bytes:
            raise ConfigError(f"spell_allow_file exceeds spell_allow_file_max_bytes ({max_bytes}).")
    finally:
        os.close(fd)
    words: set[str] = set()
    for line in data.decode("utf-8", errors="replace").splitlines():
        line = line.split("#", 1)[0]
        words.update(w.lower() for w in re.findall(r"[A-Za-z]+", line))
    out = frozenset(words)
    _VOCAB_CACHE.clear()  # one live vocabulary at a time; bounded
    _VOCAB_CACHE[key] = out
    return out


def dotenv_enabled() -> bool:
    """Whether a ``.env`` in the working directory is read.

    A planted ``.env`` could redirect backends or relax sandbox/file settings, so it is read
    only where the working directory is trusted. ``AGENTVISION_DOTENV=0`` turns it off; under
    CI (``CI`` or ``GITHUB_ACTIONS`` set — usually a PR checkout) it is OFF unless
    ``AGENTVISION_DOTENV=1`` explicitly opts back in.
    """
    raw = os.environ.get("AGENTVISION_DOTENV", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return not (os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


def load_settings(**overrides) -> Settings:
    """Build a Settings object, applying any explicit overrides last."""
    kwargs = {k: v for k, v in overrides.items() if v is not None}
    if not dotenv_enabled():
        kwargs["_env_file"] = None
    s = Settings(**kwargs)
    if s.api_token:
        from .logging import register_secret

        register_secret(s.api_token)
    return s
