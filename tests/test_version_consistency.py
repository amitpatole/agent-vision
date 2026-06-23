"""Guard: the code __version__ must match the installed package metadata (they drifted once:
pyproject said 0.9.0 while __init__ hardcoded 0.8.0). Skips if not installed as a distribution."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

import pytest

import agentvision


def test_version_matches_metadata():
    try:
        meta = version("agentvision")
    except PackageNotFoundError:
        pytest.skip("agentvision not installed as a distribution")
    assert agentvision.__version__ == meta
