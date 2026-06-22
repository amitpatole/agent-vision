"""REST service hardening regression tests (security batch 3).

Auth (constant-time, required once a token is set; loopback zero-config), body-size cap,
SSRF refused at the service, local-file source refused off the service, non-loopback bind
refusal. These run without a browser — they exercise auth/limits/resolution which all fire
before any render.
"""

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # starlette TestClient needs httpx
from fastapi.testclient import TestClient  # noqa: E402

from agentvision.adapters import rest  # noqa: E402


def _client(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return TestClient(rest.build_app(), raise_server_exceptions=True)


def test_healthz_always_open(monkeypatch):
    c = _client(monkeypatch, AGENTVISION_API_TOKEN="secret-xyz")
    assert c.get("/healthz").status_code == 200


def test_token_required_when_set(monkeypatch):
    c = _client(monkeypatch, AGENTVISION_API_TOKEN="secret-xyz")
    # no auth → 401 (before any handler work); a non-render endpoint proves it's auth, not render
    assert c.get("/artifacts/none").status_code == 401
    assert c.get("/artifacts/none", headers={"Authorization": "Bearer wrong"}).status_code == 401
    # correct token passes auth → 404 (lookup miss), not 401
    assert c.get("/artifacts/none", headers={"Authorization": "Bearer secret-xyz"}).status_code == 404


def test_loopback_zero_config_no_token(monkeypatch):
    monkeypatch.delenv("AGENTVISION_API_TOKEN", raising=False)
    c = TestClient(rest.build_app())
    assert c.get("/artifacts/none").status_code == 404  # no auth needed without a token


def test_body_size_cap(monkeypatch):
    c = _client(monkeypatch, AGENTVISION_MAX_REQUEST_BYTES="200")
    big = {"source": "<html>" + "A" * 1000 + "</html>"}
    assert c.post("/check", json=big).status_code == 413


def test_body_cap_not_bypassed_by_chunked(monkeypatch):
    # no Content-Length (chunked) must still be capped on the stream
    c = _client(monkeypatch, AGENTVISION_MAX_REQUEST_BYTES="200")

    def gen():
        yield b"x" * 500
        yield b"y" * 500

    assert c.post("/check", content=gen()).status_code == 413


def test_ssrf_metadata_refused_at_service(monkeypatch):
    monkeypatch.delenv("AGENTVISION_API_TOKEN", raising=False)
    c = TestClient(rest.build_app())
    r = c.post("/analyze", json={"source": "http://169.254.169.254/latest/meta-data/"})
    assert r.status_code == 400
    r2 = c.post("/analyze", json={"source": "http://127.0.0.1:9999/"})
    assert r2.status_code == 400


def test_local_file_source_refused_off_service(monkeypatch):
    monkeypatch.delenv("AGENTVISION_API_TOKEN", raising=False)
    c = TestClient(rest.build_app())
    r = c.post("/check", json={"source": "/etc/passwd", "source_type": "html"})
    assert r.status_code == 400
    assert "not permitted" in r.json()["detail"].lower()


def test_serve_refuses_nonloopback_without_token(monkeypatch):
    monkeypatch.delenv("AGENTVISION_API_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        rest.serve(host="0.0.0.0", port=0)
