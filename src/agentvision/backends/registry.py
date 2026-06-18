"""Backend selection.

Precedence: explicit arg -> settings.vision_backend (env/config) -> first available cloud
backend -> local. If a specific cloud backend is requested but unavailable (missing
key/dep), we fall back to ``local`` and surface a warning (handled by the caller). An
invalid key / quota error at call time is NOT a silent fallback — it raises.
"""

from __future__ import annotations

from ..config import Settings

_CLOUD_ORDER = ("anthropic", "openai", "gemini")
ALL_BACKENDS = ("anthropic", "openai", "gemini", "local")


def build_backend(name: str, settings: Settings):
    if name == "local":
        from .local_backend import LocalBackend

        return LocalBackend()
    if name == "anthropic":
        from .anthropic_backend import AnthropicBackend

        return AnthropicBackend(settings)
    if name == "openai":
        from .openai_backend import OpenAIBackend

        return OpenAIBackend(settings)
    if name == "gemini":
        from .gemini_backend import GeminiBackend

        return GeminiBackend(settings)
    raise ValueError(f"Unknown backend: {name!r}")


def available_backends(settings: Settings) -> list[str]:
    out = []
    for name in ALL_BACKENDS:
        try:
            if build_backend(name, settings).available():
                out.append(name)
        except Exception:  # noqa: BLE001
            pass
    return out


def select_backend(settings: Settings, requested: str | None = None):
    """Return ``(backend, fallback_warning_or_None)``."""
    requested = requested or settings.vision_backend
    if requested:
        backend = build_backend(requested, settings)
        if requested == "local" or backend.available():
            return backend, None
        from .local_backend import LocalBackend

        return LocalBackend(), (
            f"Vision backend '{requested}' is unavailable (missing API key or dependency); "
            "fell back to the offline 'local' backend. Set the API key to enable semantic "
            "analysis."
        )
    for name in _CLOUD_ORDER:
        backend = build_backend(name, settings)
        if backend.available():
            return backend, None
    from .local_backend import LocalBackend

    return LocalBackend(), None
