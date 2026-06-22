"""Configuration for AgentVision.

All settings resolve from (in order) explicit kwargs -> environment variables
(``AGENTVISION_*`` plus provider keys) -> a config file -> defaults. Credentials are
read here and nowhere else, and are never persisted or logged.
"""

from __future__ import annotations

from pathlib import Path

import platformdirs
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "agentvision"

# Default model per provider. Anthropic defaults to the cheap/fast Haiku because
# `analyze` runs frequently inside the loop; users can upgrade via config/env.
DEFAULT_MODELS = {
    "anthropic": "claude-haiku-4-5",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "ollama": "gemma3:27b",
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

    # Provider credentials (conventional names; never logged/persisted)
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    google_api_key: str | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    ollama_api_key: str | None = Field(default=None, validation_alias="OLLAMA_API_KEY")

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

    # Safety
    allow_url_rendering: bool = True
    block_private_networks: bool = True
    allow_file_scheme: bool = False
    # Reading a local file path as a source (e.g. `analyze ./index.html`). Safe for CLI/library
    # (trusted local user); the REST service sets this False so a remote caller can't read host
    # files via a bare path like "/etc/passwd".
    allow_local_files: bool = True

    # HTTP service (REST): bind + auth + DoS bounds
    api_token: str | None = Field(default=None, validation_alias="AGENTVISION_API_TOKEN")
    max_request_bytes: int = 8_000_000  # cap request bodies before buffering/rendering
    max_concurrent_renders: int = 4  # global semaphore so N requests can't spawn N browsers
    request_timeout_s: float = 120.0  # hard per-request ceiling above the render timeout

    # Workspace
    cache_dir: Path = Field(default_factory=default_cache_dir)
    session_ttl_s: float = 60 * 60 * 24 * 7  # 7 days

    # REST: only these backends may be selected per-request (allowlist)
    rest_enabled_backends: list[str] = Field(default_factory=lambda: ["local"])

    def model_for(self, backend: str) -> str:
        return {
            "anthropic": self.anthropic_model,
            "openai": self.openai_model,
            "gemini": self.gemini_model,
            "ollama": self.ollama_model,
        }.get(backend, "")

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
        return key


def load_settings(**overrides) -> Settings:
    """Build a Settings object, applying any explicit overrides last."""
    return Settings(**{k: v for k, v in overrides.items() if v is not None})
