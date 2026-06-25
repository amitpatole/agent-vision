import pytest

from agentvision.config import load_settings
from agentvision.errors import UnsafeSourceError
from agentvision.pathsafe import confine, resolve_local, safe_segment, under


def test_safe_segment_accepts_plain_names():
    assert safe_segment("home") == "home"
    assert safe_segment("v0.2.0-beta_1") == "v0.2.0-beta_1"
    assert safe_segment("  spaced  ") == "spaced"


@pytest.mark.parametrize("bad", ["..", ".", "a/b", "a\\b", "../x", "x/../y", "", "   ", "a b"])
def test_safe_segment_rejects_traversal_and_separators(bad):
    with pytest.raises(UnsafeSourceError):
        safe_segment(bad)


def test_confine_allows_child(tmp_path):
    f = tmp_path / "a.png"
    assert confine(tmp_path, f) == f.resolve()


def test_confine_blocks_escape(tmp_path):
    with pytest.raises(UnsafeSourceError):
        confine(tmp_path, tmp_path / ".." / ".." / "etc" / "passwd")


def test_under_builds_confined_path(tmp_path):
    p = under(tmp_path, "home", suffix=".png")
    assert p.parent == tmp_path.resolve()
    assert p.name == "home.png"
    with pytest.raises(UnsafeSourceError):
        under(tmp_path, "../evil", suffix=".png")


def test_resolve_local_unconfined_for_cli(tmp_path):
    f = tmp_path / "x.html"
    f.write_text("<html></html>")
    s = load_settings()  # file_root is None -> trusted CLI, no restriction
    assert resolve_local(str(f), s).samefile(f)


def test_resolve_local_confined_to_file_root(tmp_path):
    ok = tmp_path / "ok.html"
    ok.write_text("<html></html>")
    s = load_settings(file_root=tmp_path)
    assert resolve_local(str(ok), s).samefile(ok)
    with pytest.raises(UnsafeSourceError):
        resolve_local("/etc/passwd", s)
    with pytest.raises(UnsafeSourceError):
        resolve_local(str(tmp_path / ".." / "escape.html"), s)
