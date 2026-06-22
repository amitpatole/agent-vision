"""The eyes → brain handoff — re-exported from the shared :mod:`agentsensory`.

``Handoff``/``NextAction`` are domain-neutral and duck-typed over any sense's Report, so they live
in agentsensory; this module preserves the ``agentvision.models.handoff`` import path for back-compat.
"""

from __future__ import annotations

from agentsensory import Handoff, NextAction

__all__ = ["Handoff", "NextAction"]
