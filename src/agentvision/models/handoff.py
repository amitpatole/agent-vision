"""The eyes → brain handoff — re-exported from the shared :mod:`agentsense`.

``Handoff``/``NextAction`` are domain-neutral and duck-typed over any sense's Report, so they live
in agentsense; this module preserves the ``agentvision.models.handoff`` import path for back-compat.
"""

from __future__ import annotations

from agentsense import Handoff, NextAction

__all__ = ["Handoff", "NextAction"]
