"""The *intent* contract (the thought) — re-exported from the shared :mod:`agentsensory`.

``Brief``/``IntentClaim`` are domain-neutral, so they live in agentsensory; this module preserves
the ``agentvision.models.intent`` import path for back-compat.
"""

from __future__ import annotations

from agentsensory import Brief, IntentClaim

__all__ = ["Brief", "IntentClaim"]
