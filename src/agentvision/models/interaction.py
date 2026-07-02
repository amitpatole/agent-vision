"""Pre-capture interaction steps — a closed, declarative vocabulary.

An ``Interaction`` describes ONE action to run against the page before the screenshot is
taken, so a grader can reach state that only appears after a click/hover/zoom (a popup, a
tooltip, an expanded panel, a map heat-bin detail). The vocabulary is deliberately
**closed and enumerated** — there is no ``eval``/raw-JS step — so a config/CLI/REST caller
can never execute arbitrary code in the page (that would turn a read-only grader into a
code-execution surface). Kept pure-pydantic (no heavy deps) so it can live on ``Settings``
and ``RenderSpec`` without import cycles.

Safety model (enforced by the renderer, documented here):

* **Read-only by default.** While interactions run, the renderer blocks non-GET/HEAD
  network requests (POST/PUT/PATCH/DELETE) unless the caller opts in with
  ``allow_mutations`` — so clicking around a *live authenticated app* can't submit a form,
  delete a record, or send mail by default.
* **Secrets by reference, never inline.** ``fill`` types a literal (a search term, a
  filter); ``fill_env`` types the value of a named environment variable, so a password is
  never written into an interactions file that a user might commit.
* **Fail-closed.** A step whose selector is missing or that times out aborts the render
  with an error — the renderer never captures and grades the wrong (pre-interaction) state.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# The closed step vocabulary. Each maps to exactly one Playwright call in the renderer.
StepType = Literal[
    "click",            # click an element by CSS selector
    "click_at",         # click at a FRACTION (x,y in 0..1) of an element's box — for <canvas>
    "fill",             # type a literal value into an input (non-secret text)
    "fill_env",         # type the value of the env var named in `value` (secret-safe)
    "press",            # press a key (e.g. "Enter", "Escape")
    "hover",            # hover an element (reveals CSS/JS tooltips)
    "scroll_into_view",  # scroll an element into view
    "wait_for",         # wait for a selector to become visible
    "wait_timeout",     # fixed pause in ms (last resort — prefer wait_for)
]

_NEEDS_SELECTOR = {"click", "click_at", "fill", "fill_env", "hover",
                   "scroll_into_view", "wait_for"}
_NEEDS_VALUE = {"fill", "fill_env", "press"}


class Interaction(BaseModel):
    """One declarative pre-capture step. See the module docstring for the safety model."""

    model_config = {"extra": "forbid"}  # reject unknown keys — no smuggling arbitrary options

    type: StepType
    selector: str | None = Field(default=None, description="CSS selector the step targets.")
    value: str | None = Field(
        default=None,
        description="fill: literal text · fill_env: ENV VAR NAME · press: key name.",
    )
    x: float | None = Field(default=None, description="click_at: fractional x (0..1) in the box.")
    y: float | None = Field(default=None, description="click_at: fractional y (0..1) in the box.")
    ms: int | None = Field(default=None, description="wait_timeout: pause in milliseconds.")

    @model_validator(mode="after")
    def _check_shape(self) -> Interaction:
        t = self.type
        if t in _NEEDS_SELECTOR and not self.selector:
            raise ValueError(f"interaction '{t}' requires a 'selector'")
        if t in _NEEDS_VALUE and self.value is None:
            raise ValueError(f"interaction '{t}' requires a 'value'")
        if t == "click_at":
            for name, v in (("x", self.x), ("y", self.y)):
                if v is None or not (0.0 <= v <= 1.0):
                    raise ValueError(f"click_at requires fractional '{name}' in [0, 1]")
        if t == "wait_timeout" and (self.ms is None or self.ms < 0):
            raise ValueError("wait_timeout requires a non-negative 'ms'")
        return self

    def redacted(self) -> dict:
        """A log-safe dict: never expose a literal fill value or an env var's contents."""
        d = {"type": self.type}
        if self.selector:
            d["selector"] = self.selector
        if self.type == "click_at":
            d["x"], d["y"] = self.x, self.y
        if self.type == "wait_timeout":
            d["ms"] = self.ms
        if self.type == "press":
            d["value"] = self.value  # a key name is not a secret
        if self.type in ("fill", "fill_env"):
            d["value"] = "[REDACTED]"  # literal text or an env var name — never logged
        return d
