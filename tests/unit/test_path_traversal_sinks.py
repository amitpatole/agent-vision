"""Regression tests for the 5 CodeQL py/path-injection sinks (path traversal)."""

import pytest

from agentvision.config import load_settings
from agentvision.core.baseline import _baseline_path
from agentvision.errors import UnsafeSourceError
from agentvision.sources import resolve_source

# --- baseline.py sink (alert #1) ------------------------------------------------

def test_baseline_path_blocks_traversal(tmp_path):
    s = load_settings(cache_dir=tmp_path)
    for evil in ["../../etc/passwd", "..", "../x", "a/b"]:
        with pytest.raises(UnsafeSourceError):
            _baseline_path(s, evil)


def test_baseline_path_allows_plain_name(tmp_path):
    s = load_settings(cache_dir=tmp_path)
    p = _baseline_path(s, "home")
    assert p.name == "home.png"
    assert p.parent == (tmp_path / "baselines").resolve()


# --- sources.py sinks (alerts #2, #5) -------------------------------------------

def test_file_source_confined_to_file_root(tmp_path):
    # A confined service: a file:// (or bare path) escaping file_root is refused.
    s = load_settings(file_root=tmp_path, allow_file_scheme=True, allow_local_files=True)
    with pytest.raises(UnsafeSourceError):
        resolve_source("file:///etc/passwd", settings=s)
    with pytest.raises(UnsafeSourceError):
        resolve_source("/etc/passwd", source_type="file", settings=s)


def test_detection_existence_probe_is_confined(tmp_path):
    # The ambiguous-extension existence probe is confined too: a traversal bare string on a
    # file_root-confined service is refused, never resolved/read outside the root.
    s = load_settings(file_root=tmp_path, allow_local_files=True)
    with pytest.raises(UnsafeSourceError):
        resolve_source("../../etc/passwd", settings=s)


# --- REST sinks (alerts #3, #4) -------------------------------------------------

def test_rest_baseline_and_artifact_routes_block_traversal():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from agentvision.adapters.rest import build_app

    client = TestClient(build_app())
    # Traversal / bad names must fail closed to 404 (never read a host file).
    for name in ["..", "%2e%2e", "etc", "a..b"]:
        assert client.get(f"/baseline/{name}").status_code == 404
    assert client.get("/artifacts/..").status_code == 404
    assert client.get("/artifacts/%2e%2e").status_code == 404
