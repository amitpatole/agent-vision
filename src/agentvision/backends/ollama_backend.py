"""Ollama vision backend (OpenAI-compatible endpoint).

Lets AgentVision "see" with an open-source multimodal model served by Ollama (local or
Ollama Cloud) — the offline/OSS option for semantic critique. Default model: gemma3:27b.

Structured output is requested as JSON and parsed tolerantly (Ollama's JSON-schema support
varies by model), then validated into the shared VisionFindings model.
"""

from __future__ import annotations

import json
import re
import time

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


class OllamaBackend:
    name = "ollama"

    def __init__(self, settings: Settings):
        self.settings = settings

    def available(self) -> bool:
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return bool(self.settings.key_for("ollama"))

    async def analyze(self, req: AnalysisRequest) -> Report:
        try:
            import openai
            from openai import AsyncOpenAI
        except ImportError as e:
            raise MissingDependencyError("Ollama backend", pip_extra="openai") from e

        key = self.settings.key_for("ollama")
        if not key:
            raise BackendAuthError("OLLAMA_API_KEY is not set (and no key file found).")

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
        findings = _parse_findings(content)
        return findings_to_report(
            findings, req, backend=self.name, model=model,
            grounded=req.dom_hints, image_size=size, elapsed_ms=elapsed,
        )

    async def complete_text(self, system: str, user: str) -> str:
        import openai
        from openai import AsyncOpenAI

        key = self.settings.key_for("ollama")
        if not key:
            raise BackendAuthError("OLLAMA_API_KEY is not set (and no key file found).")
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


def _parse_findings(content: str) -> VisionFindings:
    """Tolerantly extract a JSON object and validate it into VisionFindings."""
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
        return VisionFindings.model_validate(data)
    except (json.JSONDecodeError, ValueError):
        from ..models.report import Verdict
        return VisionFindings(
            verdict=Verdict.WARN,
            summary=(content[:300] or "Ollama returned no parseable findings."),
            issues=[],
        )
