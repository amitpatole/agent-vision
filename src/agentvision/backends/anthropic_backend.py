"""Anthropic (Claude) vision backend.

Uses a forced tool call to guarantee structured output across SDK/model versions, with the
strict VisionFindings schema as the tool's input schema.
"""

from __future__ import annotations

import time

from ..config import Settings
from ..errors import BackendAuthError, BackendError, MissingDependencyError
from ..models.report import Report
from ._image import load_image_b64
from .base import AnalysisRequest
from .prompt import SYSTEM_PROMPT, VisionFindings, build_user_text, findings_to_report
from .schema_adapters import vision_findings_strict_schema

_TOOL_NAME = "report_visual_findings"


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, settings: Settings):
        self.settings = settings

    def available(self) -> bool:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return bool(self.settings.key_for("anthropic"))

    async def analyze(self, req: AnalysisRequest) -> Report:
        try:
            import anthropic
            from anthropic import AsyncAnthropic
        except ImportError as e:
            raise MissingDependencyError("Anthropic backend", pip_extra="anthropic") from e

        key = self.settings.key_for("anthropic")
        if not key:
            raise BackendAuthError("ANTHROPIC_API_KEY is not set.")

        b64, media, size = load_image_b64(req.image_path, self.settings.vision_max_edge_px)
        user_text = build_user_text(req, size)
        model = self.settings.anthropic_model
        tool = {
            "name": _TOOL_NAME,
            "description": "Report structured visual findings about the screenshot.",
            "input_schema": vision_findings_strict_schema(),
        }
        content: list = [
            {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}},
        ]
        if req.reference_image_path:
            rb64, rmedia, _ = load_image_b64(req.reference_image_path,
                                             self.settings.vision_max_edge_px)
            content.append({"type": "text", "text": "REFERENCE image (target to match):"})
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": rmedia, "data": rb64}})
        for ep in req.extra_images:
            eb64, emedia, _ = load_image_b64(ep, self.settings.vision_max_edge_px)
            content.append({"type": "text", "text": "Full-resolution crop of a visual region:"})
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": emedia, "data": eb64}})
        content.append({"type": "text", "text": user_text})
        client = AsyncAnthropic(api_key=key)
        t0 = time.monotonic()
        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=[tool],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
                messages=[{"role": "user", "content": content}],
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            raise BackendAuthError(f"Anthropic auth failed: {e}") from e
        except anthropic.RateLimitError as e:
            raise BackendAuthError(f"Anthropic rate limit / quota exceeded: {e}") from e
        except anthropic.APIError as e:
            raise BackendError(f"Anthropic API error: {e}") from e
        finally:
            await client.close()

        elapsed = int((time.monotonic() - t0) * 1000)
        findings = _extract_findings(resp)
        return findings_to_report(
            findings, req, backend=self.name, model=model,
            grounded=req.dom_hints, image_size=size, elapsed_ms=elapsed,
        )

    async def complete_text(self, system: str, user: str) -> str:
        import anthropic
        from anthropic import AsyncAnthropic

        key = self.settings.key_for("anthropic")
        if not key:
            raise BackendAuthError("ANTHROPIC_API_KEY is not set.")
        client = AsyncAnthropic(api_key=key)
        try:
            resp = await client.messages.create(
                model=self.settings.anthropic_model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            raise BackendAuthError(f"Anthropic auth failed: {e}") from e
        except anthropic.APIError as e:
            raise BackendError(f"Anthropic API error: {e}") from e
        finally:
            await client.close()
        return " ".join(
            getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text"
        ).strip()


def _extract_findings(resp) -> VisionFindings:
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == _TOOL_NAME:
            return VisionFindings.model_validate(block.input)
    # Fallback: model didn't call the tool (rare with forced tool_choice).
    text = " ".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
    from ..models.report import Verdict
    from .prompt import VisionFindings as VF
    return VF(verdict=Verdict.WARN, summary=text[:400] or "No structured findings returned.", issues=[])
