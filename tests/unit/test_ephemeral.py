"""Ephemeral (--no-cache) mode: confidential inputs are never persisted to the cache."""

from pathlib import Path

from agentvision import ephemeral_cache, load_settings
from agentvision.config import default_cache_dir
from agentvision.workspace import Workspace


def test_ephemeral_default_off():
    assert load_settings().ephemeral is False


def test_ephemeral_cache_uses_temp_and_wipes(tmp_path):
    base = load_settings(cache_dir=tmp_path)
    captured = {}
    with ephemeral_cache(base) as s:
        assert s.ephemeral is True
        assert Path(s.cache_dir) != Path(base.cache_dir)
        assert Path(s.cache_dir).exists()
        # A workspace under the ephemeral settings writes only inside the temp dir.
        ws = Workspace(s)
        marker = ws.tmp / "artifact.bin"
        marker.write_bytes(b"secret")
        assert marker.exists()
        captured["dir"] = Path(s.cache_dir)
    # On exit the whole temp tree (and the secret artifact) is gone.
    assert not captured["dir"].exists()


def test_ephemeral_cache_wipes_on_error(tmp_path):
    leaked = {}
    try:
        with ephemeral_cache(load_settings(cache_dir=tmp_path)) as s:
            leaked["dir"] = Path(s.cache_dir)
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert not leaked["dir"].exists()


def test_cli_no_cache_settings_are_ephemeral_and_off_default():
    from agentvision.adapters import cli

    s = cli._settings(no_cache=True)
    assert s.ephemeral is True
    assert Path(s.cache_dir) != default_cache_dir()
    assert Path(s.cache_dir).exists()  # atexit wipes it when the CLI process ends
