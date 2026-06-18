from agentvision.config import load_settings
from agentvision.workspace import SCHEMA_VERSION, Workspace


def _ws(tmp_path):
    return Workspace(load_settings(cache_dir=tmp_path))


def test_render_key_is_deterministic_and_input_sensitive(tmp_path):
    ws = _ws(tmp_path)
    k1 = ws.render_key(source_bytes=b"<html>", viewport=(1280, 800), device_scale=1.0,
                       wait_for=None, full_page=False)
    k2 = ws.render_key(source_bytes=b"<html>", viewport=(1280, 800), device_scale=1.0,
                       wait_for=None, full_page=False)
    k3 = ws.render_key(source_bytes=b"<html>", viewport=(375, 800), device_scale=1.0,
                       wait_for=None, full_page=False)
    assert k1 == k2
    assert k1 != k3  # different viewport -> different key


def test_session_meta_roundtrip_and_schema_guard(tmp_path):
    ws = _ws(tmp_path)
    sid = ws.new_session_id()
    ws.write_session_meta(sid, {"iterations": 1})
    meta = ws.read_session_meta(sid)
    assert meta["iterations"] == 1
    assert meta["schema_version"] == SCHEMA_VERSION

    # Corrupt the schema_version -> read returns None (ignored) and gc reaps it.
    f = ws.session_dir(sid) / "session.json"
    f.write_text('{"schema_version": "0.0", "iterations": 1}')
    assert ws.read_session_meta(sid) is None
    removed = ws.gc()
    assert removed >= 1
