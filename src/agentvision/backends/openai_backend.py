"""OpenAI (GPT vision) backend. Strict json_schema structured output."""

from __future__ import annotations

import json
import time

from ..config import Settings
from ..errors import BackendAuthError, BackendError, MissingDependencyError
from ..models.report import Report
from ._image import load_image_b64
from .base import AnalysisRequest
from .prompt import SYSTEM_PROMPT, VisionFindings, build_user_text, findings_to_report
from .schema_adapters import openai_response_format


class OpenAIBackend:
    name = "openai"

    def __init__(self, settings: Settings):
        self.settings = settings

    def available(self) -> bool:
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return bool(self.settings.key_for("openai"))

    async def analyze(self, req: AnalysisRequest) -> Report:
        try:
            import openai
            from openai import AsyncOpenAI
        except ImportError as e:
            raise MissingDependencyError("OpenAI backend", pip_extra="openai") from e

        key = self.settings.key_for("openai")
        if not key:
            raise BackendAuthError("OPENAI_API_KEY is not set.")

        b64, media, size = load_image_b64(req.image_path)
        user_text = build_user_text(req, size)
        model = self.settings.openai_model
        client = AsyncOpenAI(api_key=key)
        t0 = time.monotonic()
        try:
            resp = await client.chat.completions.create(
                model=model,
                max_tokens=2048,
                response_format=openai_response_format(),
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url",
                         "image_url": {"url": f"data:{media};base64,{b64}"}},
                    ]},
                ],
            )
        except openai.AuthenticationError as e:
            raise BackendAuthError(f"OpenAI auth failed: {e}") from e
        except openai.RateLimitError as e:
            raise BackendAuthError(f"OpenAI rate limit / quota exceeded: {e}") from e
        except openai.APIError as e:
            raise BackendError(f"OpenAI API error: {e}") from e
        finally:
            await client.close()

        elapsed = int((time.monotonic() - t0) * 1000)
        content = resp.choices[0].message.content or "{}"
        try:
            findings = VisionFindings.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValueError) as e:
            raise BackendError(f"OpenAI returned invalid structured output: {e}") from e
        return findings_to_report(
            findings, req, backend=self.name, model=model,
            grounded=req.dom_hints, image_size=size, elapsed_ms=elapsed,
        )
