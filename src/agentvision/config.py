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

# Fallback location for an Ollama API key if the env var is unset.
OLLAMA_KEY_FILE = Path.home() / ".config" / "ollama" / "key"


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
    render_timeout_s: float = 30.0
    nav_wait: str = "networkidle"  # load|domcontentloaded|networkidle

    # Safety
    allow_url_rendering: bool = True
    block_private_networks: bool = True
    allow_file_scheme: bool = False

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
        # Ollama: fall back to the conventional key file if env is unset.
        if backend == "ollama" and not key and OLLAMA_KEY_FILE.exists():
            try:
                key = OLLAMA_KEY_FILE.read_text().strip() or None
            except OSError:
                key = None
        return key


def load_settings(**overrides) -> Settings:
    """Build a Settings object, applying any explicit overrides last."""
    return Settings(**{k: v for k, v in overrides.items() if v is not None})
