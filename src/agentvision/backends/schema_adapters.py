"""Per-provider schema emission for the ``VisionFindings`` structured output.

One internal contract, three provider dialects:

* **Anthropic** — pass the Pydantic model to ``messages.parse(output_format=...)``; the
  SDK derives and enforces the schema.
* **OpenAI** — strict ``json_schema`` requires ``additionalProperties: false`` on every
  object and *every* property in ``required`` (optionals become nullable unions). Built
  by hand here for guaranteed compliance.
* **Gemini** — accepts a Pydantic model as ``response_schema`` (OpenAPI subset); the SDK
  adapts it.
"""

from __future__ import annotations

from ..models.report import Confidence, IssueKind, Severity, Verdict
from .prompt import VisionFindings


def _enum_values(enum_cls) -> list[str]:
    return [e.value for e in enum_cls]


def _box_schema() -> dict:
    num = {"type": "number"}
    return {
        "type": ["object", "null"],
        "additionalProperties": False,
        "properties": {"x": num, "y": num, "width": num, "height": num},
        "required": ["x", "y", "width", "height"],
    }


def _issue_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "kind": {"type": "string", "enum": _enum_values(IssueKind)},
            "severity": {"type": "string", "enum": _enum_values(Severity)},
            "message": {"type": "string"},
            "confidence": {"type": "string", "enum": _enum_values(Confidence)},
            "box": _box_schema(),
        },
        "required": ["kind", "severity", "message", "confidence", "box"],
    }


def vision_findings_strict_schema() -> dict:
    """A strict JSON schema (OpenAI-compatible) for VisionFindings."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "verdict": {"type": "string", "enum": _enum_values(Verdict)},
            "summary": {"type": "string"},
            "issues": {"type": "array", "items": _issue_schema()},
        },
        "required": ["verdict", "summary", "issues"],
    }


def openai_response_format() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "VisionFindings",
            "strict": True,
            "schema": vision_findings_strict_schema(),
        },
    }


def anthropic_output_format():
    """Anthropic accepts the Pydantic model directly via messages.parse."""
    return VisionFindings


def gemini_response_schema():
    """google-genai accepts a Pydantic model as response_schema."""
    return VisionFindings


def assert_strict(schema: dict) -> None:
    """Validate that a schema satisfies strict-mode invariants (used by tests)."""
    if schema.get("type") in ("object", ["object", "null"]) or (
        isinstance(schema.get("type"), list) and "object" in schema["type"]
    ):
        assert schema.get("additionalProperties") is False, "objects must disable additionalProperties"
        props = set(schema.get("properties", {}))
        required = set(schema.get("required", []))
        assert props == required, f"strict mode requires all properties in required: {props ^ required}"
        for sub in schema.get("properties", {}).values():
            assert_strict(sub)
    if schema.get("type") == "array":
        assert_strict(schema["items"])
