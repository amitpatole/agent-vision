"""Unit tests for Phase-1 auth + interaction plumbing (no browser required).

Pins the closed interaction vocabulary, the single-viewport rule, secret-safe storage_state
loading (cookie/localStorage values must be redaction-registered and never logged), and the
CLI interaction parser.
"""

import json
import logging

import pytest
from pydantic import ValidationError

from agentvision import load_settings
from agentvision.models.geometry import Viewport
from agentvision.models.interaction import Interaction
from agentvision.renderers.base import RenderSpec
from agentvision.renderers.playwright_renderer import PlaywrightRenderer

# --- the closed vocabulary --------------------------------------------------------------

def test_interaction_requires_selector_where_needed():
    for t in ("click", "hover", "scroll_into_view", "wait_for", "click_at", "fill"):
        with pytest.raises(ValidationError):
            Interaction(type=t)  # missing selector


def test_click_at_fraction_must_be_in_unit_range():
    with pytest.raises(ValidationError):
        Interaction(type="click_at", selector="#map", x=1.5, y=0.5)
    ok = Interaction(type="click_at", selector="#map", x=0.6, y=0.4)
    assert ok.x == 0.6 and ok.y == 0.4


def test_fill_and_press_require_value():
    with pytest.raises(ValidationError):
        Interaction(type="fill", selector="#q")  # no value
    with pytest.raises(ValidationError):
        Interaction(type="press")  # no key
    assert Interaction(type="press", value="Enter").value == "Enter"


def test_unknown_step_key_is_rejected():
    # extra='forbid' — a config can't smuggle an unknown option (e.g. a raw-JS field).
    with pytest.raises(ValidationError):
        Interaction.model_validate({"type": "click", "selector": "#x", "js": "alert(1)"})


def test_no_eval_step_exists():
    # The vocabulary must never grow an arbitrary-code escape hatch by accident.
    from typing import get_args

    from agentvision.models.interaction import StepType
    banned = {"eval", "evaluate", "script", "exec", "js", "function"}
    assert banned.isdisjoint(set(get_args(StepType)))


def test_redacted_never_exposes_fill_value():
    step = Interaction(type="fill", selector="#pw", value="hunter2")
    assert step.redacted()["value"] == "[REDACTED]"
    env = Interaction(type="fill_env", selector="#pw", value="MY_SECRET_ENV")
    assert env.redacted()["value"] == "[REDACTED]"  # even the env var NAME is not logged
    assert Interaction(type="press", value="Enter").redacted()["value"] == "Enter"  # keys ok


# --- RenderSpec single-viewport rule ----------------------------------------------------

def test_interactions_require_single_viewport():
    two = [Viewport(width=800, height=600), Viewport(width=400, height=800)]
    with pytest.raises(ValidationError):
        RenderSpec(source="x", viewports=two,
                   interactions=[Interaction(type="click", selector="#a")])
    # one viewport is fine
    RenderSpec(source="x", viewports=[two[0]],
               interactions=[Interaction(type="click", selector="#a")])


# --- storage_state: secret-safe loading -------------------------------------------------

def test_storage_state_missing_file_raises(tmp_path):
    r = PlaywrightRenderer(load_settings())
    from agentvision.errors import RenderError
    with pytest.raises(RenderError):
        r._load_storage_state(str(tmp_path / "nope.json"))


def test_storage_state_registers_secrets_and_logs_only_counts(tmp_path, caplog):
    state = {
        "cookies": [{"name": "sid", "value": "SECRET-SESSION-TOKEN-123", "domain": "app"}],
        "origins": [{"origin": "https://app",
                     "localStorage": [{"name": "jwt", "value": "SECRET-JWT-XYZ-456"}]}],
    }
    p = tmp_path / "state.json"
    p.write_text(json.dumps(state))
    r = PlaywrightRenderer(load_settings())

    with caplog.at_level(logging.INFO, logger="agentvision"):
        loaded = r._load_storage_state(str(p))

    assert loaded is not None  # returns the in-memory dict (never re-serialized)
    # Both secret values are registered so any future log line is scrubbed.
    from agentvision.logging import _KNOWN_SECRETS
    assert "SECRET-SESSION-TOKEN-123" in _KNOWN_SECRETS
    assert "SECRET-JWT-XYZ-456" in _KNOWN_SECRETS
    # The load log names counts, not values.
    joined = " ".join(rec.getMessage() for rec in caplog.records)
    assert "SECRET-SESSION-TOKEN-123" not in joined
    assert "SECRET-JWT-XYZ-456" not in joined
    assert "1 cookie" in joined and "1 origin" in joined


def test_storage_state_secret_is_scrubbed_from_logs(tmp_path):
    # End-to-end: a registered cookie value is replaced with [REDACTED] by the log filter.
    state = {"cookies": [{"name": "sid", "value": "TOPSECRETVALUE0001", "domain": "a"}],
             "origins": []}
    p = tmp_path / "s.json"
    p.write_text(json.dumps(state))
    r = PlaywrightRenderer(load_settings())
    r._load_storage_state(str(p))

    from agentvision.logging import _SecretScrubber
    rec = logging.LogRecord("agentvision", logging.INFO, __file__, 1,
                            "leak attempt: TOPSECRETVALUE0001", None, None)
    _SecretScrubber().filter(rec)
    assert "TOPSECRETVALUE0001" not in rec.getMessage()
    assert "[REDACTED]" in rec.getMessage()


# --- CLI parser -------------------------------------------------------------------------

def test_cli_parse_interactions_inline_and_validation():
    from agentvision.adapters.cli import _parse_interactions

    steps = _parse_interactions('[{"type":"click","selector":"#a"},'
                                '{"type":"click_at","selector":"#map","x":0.5,"y":0.5}]')
    assert [s.type for s in steps] == ["click", "click_at"]
    assert _parse_interactions(None) == []

    import typer
    with pytest.raises(typer.BadParameter):
        _parse_interactions('[{"type":"bogus"}]')
    with pytest.raises(typer.BadParameter):
        _parse_interactions('not json')
