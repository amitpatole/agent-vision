import pytest

from agentvision.config import load_settings
from agentvision.errors import UnsafeSourceError
from agentvision.sources import resolve_source


@pytest.fixture
def settings():
    return load_settings()


def test_detect_inline_html(settings):
    assert resolve_source("<html><body>hi</body></html>", settings=settings).kind == "html"


def test_detect_inline_svg(settings):
    s = "<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    assert resolve_source(s, settings=settings).kind == "svg"


def test_detect_url(settings):
    assert resolve_source("https://example.com", settings=settings).kind == "url"


def test_ssrf_blocked(settings):
    with pytest.raises(UnsafeSourceError):
        resolve_source("http://169.254.169.254/latest/meta-data/", settings=settings)


def test_localhost_blocked(settings):
    with pytest.raises(UnsafeSourceError):
        resolve_source("http://127.0.0.1:8000/", settings=settings)


def test_file_scheme_blocked(settings):
    with pytest.raises(UnsafeSourceError):
        resolve_source("file:///etc/passwd", settings=settings)


def test_file_scheme_allowed_when_opted_in():
    s = load_settings(allow_file_scheme=True)
    # /etc/hostname exists on Linux CI; fall back to /etc/passwd
    import os
    path = "/etc/hostname" if os.path.exists("/etc/hostname") else "/etc/passwd"
    resolved = resolve_source(f"file://{path}", settings=s)
    assert resolved.kind in {"html", "image", "pdf", "svg"}
