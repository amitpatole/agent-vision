from agentvision.backends.prompt import VisionFindings
from agentvision.backends.schema_adapters import (
    anthropic_output_format,
    assert_strict,
    gemini_response_schema,
    openai_response_format,
    vision_findings_strict_schema,
)


def test_strict_schema_is_strict():
    assert_strict(vision_findings_strict_schema())


def test_openai_response_format_shape():
    rf = openai_response_format()
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    assert_strict(rf["json_schema"]["schema"])


def test_anthropic_and_gemini_use_pydantic_model():
    assert anthropic_output_format() is VisionFindings
    assert gemini_response_schema() is VisionFindings


def test_vision_findings_validates_sample():
    sample = {
        "verdict": "fail",
        "summary": "Button overflows.",
        "issues": [
            {"kind": "overflow", "severity": "error", "message": "button overflows",
             "confidence": "high", "box": {"x": 1, "y": 2, "width": 3, "height": 4}},
            {"kind": "contrast", "severity": "warning", "message": "low contrast",
             "confidence": "low", "box": None},
        ],
    }
    vf = VisionFindings.model_validate(sample)
    assert vf.verdict.value == "fail"
    assert len(vf.issues) == 2
    assert vf.issues[1].box is None
