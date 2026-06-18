"""AgentVision exception hierarchy.

Kept dependency-free so it can be imported anywhere (including pure-model modules).
"""

from __future__ import annotations


class AgentVisionError(Exception):
    """Base class for all AgentVision errors."""


class MissingDependencyError(AgentVisionError):
    """An optional dependency (a pip extra or a system package) is not installed.

    The message tells the user exactly how to fix it.
    """

    def __init__(self, feature: str, *, pip_extra: str | None = None, system: str | None = None):
        parts = [f"AgentVision feature '{feature}' requires extra dependencies that are not installed."]
        if pip_extra:
            parts.append(f"Install the Python extra:  pip install 'agentvision[{pip_extra}]'")
        if system:
            parts.append(f"Install the system package(s):  {system}")
        super().__init__("\n".join(parts))
        self.feature = feature
        self.pip_extra = pip_extra
        self.system = system


class RenderError(AgentVisionError):
    """Rendering an artifact failed (bad source, navigation error, crash)."""


class RenderTimeout(RenderError):
    """A render exceeded its hard timeout (likely a hanging page)."""


class UnsafeSourceError(AgentVisionError):
    """A source was blocked by the safety policy (SSRF / file:// / disallowed scheme)."""


class BackendError(AgentVisionError):
    """A vision backend failed in a way that is not a missing dependency."""


class BackendAuthError(BackendError):
    """A backend's credentials are missing, invalid, or out of quota."""


class ConfigError(AgentVisionError):
    """Invalid configuration."""
