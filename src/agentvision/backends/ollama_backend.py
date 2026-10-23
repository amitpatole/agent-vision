"""Ollama vision backend (OpenAI-compatible endpoint).

Lets AgentVision "see" with an open-source multimodal model served by Ollama (local or
Ollama Cloud) — the offline/OSS option for semantic critique. Default model: gemma3:27b.

Two deployment shapes, decided by ``ollama_base_url``:

- **Ollama Cloud** (``https://ollama.com/...``, the default): needs an API key, resolved from
  ``OLLAMA_API_KEY`` or ``~/.config/ollama/key``.
- **Self-hosted** (any other host, e.g. ``http://192.0.2.10:11434/v1``): needs no key. The cloud
  key, from ``OLLAMA_API_KEY`` *or* the key file, is **never** sent to a self-hosted host, so a
  redirected base URL (including one planted in a ``.env``) cannot exfiltrate it. An auth proxy
  in front of a self-hosted server uses its own ``AGENTVISION_OLLAMA_SELF_HOSTED_KEY``.

The cloud key is sent only over ``https`` to an ``ollama.com`` host.

Structured output is requested as JSON and parsed tolerantly (Ollama's JSON-schema support
varies by model), then validated into the shared VisionFindings model. A reply that cannot be
parsed is surfaced as a WARNING issue, so a garbled model reply can never grade as PASS.
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urlsplit

from ..config import Settings
from ..errors import BackendAuthError, BackendError, MissingDependencyError
from ..models.report import Report
from ._image import load_image_b64
from .base import AnalysisRequest
from .prompt import SYSTEM_PROMPT, VisionFindings, build_user_text, findings_to_report

_JSON_INSTRUCTION = (
    "\n\nRespond with ONLY a JSON object, no prose, in this exact shape:\n"
    '{"verdict":"pass|warn|fail","summary":"...","issues":['
    '{"kind":"layout|overflow|clipped|contrast|missing_element|broken_image|overlap|blank|error_text|typo|intent_mismatch|other",'
    '"severity":"info|warning|error|critical","message":"...","confidence":"high|medium|low",'
    '"box":{"x":0,"y":0,"width":0,"height":0}}]}\n'
    'Omit "box" (or set null) if you cannot localize an issue.'
)


_CLOUD_HOSTS = frozenset({"ollama.com", "www.ollama.com"})
# The OpenAI SDK insists on a non-empty key; a self-hosted Ollama ignores it.
_SELF_HOSTED_PLACEHOLDER_KEY = "ollama"
_UNPARSEABLE = "Vision model returned unparseable output; semantic grade is missing."


def is_cloud_url(base_url: str) -> bool:
    """True when ``base_url`` is ``https`` to an Ollama Cloud host — the only destination that
    ever receives the cloud key (``http://ollama.com`` would send it in cleartext: not cloud)."""
    try:
        parts = urlsplit(base_url)
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return False  # unparseable: never the cloud, never gets the key
    if parts.scheme.lower() != "https":
        return False
    return host in _CLOUD_HOSTS or host.endswith(".ollama.com")


def resolve_credential(settings: Settings) -> str | None:
    """The key to send to ``settings.ollama_base_url``, or None if a required key is missing.

    Cloud: the cloud key (``OLLAMA_API_KEY`` or the key file). Self-hosted: only the separate
    ``AGENTVISION_OLLAMA_SELF_HOSTED_KEY`` (never the cloud key), else a placeholder the server
    ignores.
    """
    if is_cloud_url(settings.ollama_base_url):
        return settings.key_for("ollama")
    own = settings.ollama_self_hosted_key
    if own:
        from ..logging import register_secret

        register_secret(own)
        return own
    return _SELF_HOSTED_PLACEHOLDER_KEY


class OllamaBackend:
    name = "ollama"

    def __init__(self, settings: Settings):
        self.settings = settings

    def available(self) -> bool:
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return bool(resolve_credential(self.settings))

    def _key(self) -> str:
        key = resolve_credential(self.settings)
        if not key:
            raise BackendAuthError(
                "Ollama Cloud (https://ollama.com) needs OLLAMA_API_KEY (or ~/.config/ollama/key). "
                "For a self-hosted server set AGENTVISION_OLLAMA_BASE_URL, e.g. "
                "http://localhost:11434/v1."
            )
        return key

    async def analyze(self, req: AnalysisRequest) -> Report:
        try:
            import openai
            from openai import AsyncOpenAI
        except ImportError as e:
            raise MissingDependencyError("Ollama backend", pip_extra="openai") from e

        key = self._key()

        b64, media, size = load_image_b64(req.image_path, self.settings.vision_max_edge_px)
        user_text = build_user_text(req, size) + _JSON_INSTRUCTION
        model = self.settings.ollama_model
        user_content: list = [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": f"data:{media};base64,{b64}"}},
        ]
        if req.reference_image_path:
            rb64, rmedia, _ = load_image_b64(req.reference_image_path,
                                             self.settings.vision_max_edge_px)
            user_content.append({"type": "text", "text": "REFERENCE image (target to match):"})
            user_content.append(
                {"type": "image_url", "image_url": {"url": f"data:{rmedia};base64,{rb64}"}}
            )
        for ep in req.extra_images:
            eb64, emedia, _ = load_image_b64(ep, self.settings.vision_max_edge_px)
            user_content.append({"type": "text", "text": "Full-resolution crop of a visual region:"})
            user_content.append(
                {"type": "image_url", "image_url": {"url": f"data:{emedia};base64,{eb64}"}}
            )
        client = AsyncOpenAI(base_url=self.settings.ollama_base_url, api_key=key)
        t0 = time.monotonic()
        try:
            resp = await client.chat.completions.create(
                model=model,
                max_tokens=2048,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            )
        except openai.AuthenticationError as e:
            raise BackendAuthError(f"Ollama auth failed: {e}") from e
        except openai.APIError as e:
            raise BackendError(f"Ollama API error: {e}") from e
        finally:
            await client.close()

        elapsed = int((time.monotonic() - t0) * 1000)
        content = resp.choices[0].message.content or ""
        findings, parsed = _parse_findings(content)
        grounded = list(req.dom_hints)
        if not parsed:
            # Fail closed: a missing semantic grade must not read as a clean PASS.
            from ..models.report import Confidence, Issue, IssueKind, IssueSource, Severity

            grounded.append(Issue.make(
                IssueKind.OTHER, Severity.WARNING, _UNPARSEABLE,
                confidence=Confidence.HIGH, source=IssueSource.VISION,
            ))
        return findings_to_report(
            findings, req, backend=self.name, model=model,
            grounded=grounded, image_size=size, elapsed_ms=elapsed,
        )

    async def complete_text(self, system: str, user: str) -> str:
        import openai
        from openai import AsyncOpenAI

        key = self._key()
        client = AsyncOpenAI(base_url=self.settings.ollama_base_url, api_key=key)
        try:
            resp = await client.chat.completions.create(
                model=self.settings.ollama_model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except openai.AuthenticationError as e:
            raise BackendAuthError(f"Ollama auth failed: {e}") from e
        except openai.APIError as e:
            raise BackendError(f"Ollama API error: {e}") from e
        finally:
            await client.close()
        return (resp.choices[0].message.content or "").strip()


def _parse_findings(content: str) -> tuple[VisionFindings, bool]:
    """Tolerantly extract a JSON object and validate it into VisionFindings.

    Returns ``(findings, parsed)``; ``parsed`` is False when the reply was unusable.
    """
    text = content.strip()
    # Strip code fences if present.
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    candidate = text
    if not candidate.startswith("{"):
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            candidate = m.group(0)
    try:
        data = json.loads(candidate)
        return VisionFindings.model_validate(data), True
    except (json.JSONDecodeError, ValueError):
        from ..models.report import Verdict
        return VisionFindings(
            verdict=Verdict.WARN,
            summary=_UNPARSEABLE,
            issues=[],
        ), False
