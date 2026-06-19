"""Gemini vision backend (google-genai). Pydantic response_schema structured output."""

from __future__ import annotations

import json
import time

from ..config import Settings
from ..errors import BackendAuthError, BackendError, MissingDependencyError
from ..models.report import Report
from ._image import load_image_b64
from .base import AnalysisRequest
from .prompt import SYSTEM_PROMPT, VisionFindings, build_user_text, findings_to_report


class GeminiBackend:
    name = "gemini"

    def __init__(self, settings: Settings):
        self.settings = settings

    def available(self) -> bool:
        try:
            import google.genai  # noqa: F401
        except ImportError:
            return False
        return bool(self.settings.key_for("gemini"))

    async def analyze(self, req: AnalysisRequest) -> Report:
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise MissingDependencyError("Gemini backend", pip_extra="gemini") from e

        key = self.settings.key_for("gemini")
        if not key:
            raise BackendAuthError("GOOGLE_API_KEY is not set.")

        b64, media, size = load_image_b64(req.image_path, self.settings.vision_max_edge_px)
        import base64 as _b64
        image_bytes = _b64.b64decode(b64)
        user_text = build_user_text(req, size)
        model = self.settings.gemini_model
        contents: list = [types.Part.from_bytes(data=image_bytes, mime_type=media)]
        if req.reference_image_path:
            rb64, rmedia, _ = load_image_b64(req.reference_image_path,
                                             self.settings.vision_max_edge_px)
            contents.append("REFERENCE image (target to match):")
            contents.append(types.Part.from_bytes(data=_b64.b64decode(rb64), mime_type=rmedia))
        for ep in req.extra_images:
            eb64, emedia, _ = load_image_b64(ep, self.settings.vision_max_edge_px)
            contents.append("Full-resolution crop of a visual region:")
            contents.append(types.Part.from_bytes(data=_b64.b64decode(eb64), mime_type=emedia))
        contents.append(user_text)
        client = genai.Client(api_key=key)
        t0 = time.monotonic()
        try:
            resp = await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=VisionFindings,
                    max_output_tokens=2048,
                ),
            )
        except genai.errors.ClientError as e:
            code = getattr(e, "code", None)
            if code in (401, 403, 429):
                raise BackendAuthError(f"Gemini auth/quota error: {e}") from e
            raise BackendError(f"Gemini client error: {e}") from e
        except genai.errors.APIError as e:
            raise BackendError(f"Gemini API error: {e}") from e

        elapsed = int((time.monotonic() - t0) * 1000)
        findings = getattr(resp, "parsed", None)
        if not isinstance(findings, VisionFindings):
            try:
                findings = VisionFindings.model_validate(json.loads(resp.text or "{}"))
            except (json.JSONDecodeError, ValueError) as e:
                raise BackendError(f"Gemini returned invalid structured output: {e}") from e
        return findings_to_report(
            findings, req, backend=self.name, model=model,
            grounded=req.dom_hints, image_size=size, elapsed_ms=elapsed,
        )

    async def complete_text(self, system: str, user: str) -> str:
        from google import genai
        from google.genai import types

        key = self.settings.key_for("gemini")
        if not key:
            raise BackendAuthError("GOOGLE_API_KEY is not set.")
        client = genai.Client(api_key=key)
        try:
            resp = await client.aio.models.generate_content(
                model=self.settings.gemini_model,
                contents=[user],
                config=types.GenerateContentConfig(
                    system_instruction=system, max_output_tokens=1024
                ),
            )
        except genai.errors.ClientError as e:
            code = getattr(e, "code", None)
            if code in (401, 403, 429):
                raise BackendAuthError(f"Gemini auth/quota error: {e}") from e
            raise BackendError(f"Gemini client error: {e}") from e
        except genai.errors.APIError as e:
            raise BackendError(f"Gemini API error: {e}") from e
        return (resp.text or "").strip()
