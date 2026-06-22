"""SSRF boundary regression tests (security batch 1).

Pins: internal/metadata/IPv4-mapped addresses are blocked at both resolve-time and fetch-time,
internal URLs are refused, the override works, and local-file reads are gated off the service.
"""

import pytest

from agentvision import load_settings
from agentvision.errors import UnsafeSourceError
from agentvision.netguard import assert_host_safe, host_is_safe, ip_is_blocked
from agentvision.sources import resolve_source

BLOCKED = [
    "169.254.169.254", "fd00:ec2::254", "100.100.100.200",   # cloud metadata
    "127.0.0.1", "::1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "0.0.0.0",
    "::ffff:169.254.169.254", "::ffff:127.0.0.1", "::ffff:10.0.0.1",  # IPv4-mapped bypass
]
PUBLIC = ["8.8.8.8", "1.1.1.1", "93.184.216.34"]


@pytest.mark.parametrize("addr", BLOCKED)
def test_internal_addresses_blocked(addr):
    assert ip_is_blocked(addr) is True


@pytest.mark.parametrize("addr", PUBLIC)
def test_public_addresses_allowed(addr):
    assert ip_is_blocked(addr) is False


def test_unparseable_host_fails_closed():
    assert ip_is_blocked("not-an-ip") is True


@pytest.mark.parametrize("host", ["127.0.0.1", "169.254.169.254", "::ffff:169.254.169.254"])
def test_assert_host_safe_blocks_literal_internal(host):
    with pytest.raises(UnsafeSourceError):
        assert_host_safe(host, 80)


async def test_host_is_safe_literal():
    assert await host_is_safe("169.254.169.254", 80) is False
    assert await host_is_safe("::ffff:169.254.169.254", 80) is False
    assert await host_is_safe("8.8.8.8", 80) is True
    assert await host_is_safe("", 80) is False


def test_resolve_internal_url_blocked():
    with pytest.raises(UnsafeSourceError):
        resolve_source("http://127.0.0.1:9999/", settings=load_settings())
    with pytest.raises(UnsafeSourceError):
        resolve_source("http://169.254.169.254/latest/meta-data/", settings=load_settings())


def test_resolve_allows_override():
    s = load_settings(block_private_networks=False)
    assert resolve_source("http://127.0.0.1:9999/", settings=s).kind == "url"


def test_non_http_url_scheme_rejected():
    for bad in ["ftp://example.com/x", "gopher://127.0.0.1/", "file:///etc/passwd"]:
        with pytest.raises(UnsafeSourceError):
            resolve_source(bad, source_type="url", settings=load_settings())


def test_local_file_read_gated_off_service(tmp_path):
    f = tmp_path / "page.html"
    f.write_text("<html><body>hi</body></html>")
    # CLI / library default: local file allowed
    assert resolve_source(str(f), settings=load_settings()).kind == "html"
    # service context: refused (no host-file read via a bare path)
    with pytest.raises(UnsafeSourceError):
        resolve_source(str(f), settings=load_settings(allow_local_files=False))


def test_secret_path_read_blocked_off_service(tmp_path):
    secret = tmp_path / "key"
    secret.write_text("sk-ant-SECRET")
    with pytest.raises(UnsafeSourceError):
        resolve_source(str(secret), source_type="html",
                       settings=load_settings(allow_local_files=False))
