"""Temporal verification — deterministic playback/liveness/black-frame checks."""

from PIL import Image

from agentvision.core.temporal import changed_ratio, compute_temporal_checks
from agentvision.renderers.base import Frame, MediaState


def _frame(tmp, idx, color, media=None):
    p = tmp / f"f{idx}.png"
    Image.new("RGB", (200, 150), color).save(p)
    return Frame(index=idx, t_ms=idx * 500, image_path=str(p), width=200, height=150,
                 media=media or [])


def _vid(ct, paused=False, rs=4, vw=640):
    return MediaState(selector="#v", current_time=ct, paused=paused, ready_state=rs,
                      video_width=vw)


def test_changed_ratio(tmp_path):
    a = _frame(tmp_path, 0, "white")
    b = _frame(tmp_path, 1, "black")
    assert changed_ratio(a.image_path, b.image_path) > 0.9
    assert changed_ratio(a.image_path, a.image_path) == 0.0


def test_video_stall_detected(tmp_path):
    # not paused, but currentTime never advances -> stalled/buffering (ERROR).
    frames = [_frame(tmp_path, 0, "gray", [_vid(1.0)]),
              _frame(tmp_path, 1, "gray", [_vid(1.0)])]
    issues, signals = compute_temporal_checks(frames)
    stalls = [i for i in issues if i.detail.get("temporal") == "stall"]
    assert stalls and stalls[0].severity.value == "error"
    assert signals["videos"][0]["playing"] is False


def test_video_playing_ok(tmp_path):
    frames = [_frame(tmp_path, 0, "gray", [_vid(1.0)]),
              _frame(tmp_path, 1, "gray", [_vid(1.6)])]
    issues, signals = compute_temporal_checks(frames)
    assert not [i for i in issues if i.detail.get("temporal") == "stall"]
    assert signals["videos"][0]["playing"] is True
    assert signals["videos"][0]["advanced_s"] > 0.5


def test_paused_video_is_not_a_stall(tmp_path):
    frames = [_frame(tmp_path, 0, "gray", [_vid(1.0, paused=True)]),
              _frame(tmp_path, 1, "gray", [_vid(1.0, paused=True)])]
    issues, _ = compute_temporal_checks(frames)
    assert not [i for i in issues if i.detail.get("temporal") == "stall"]


def test_black_frames_flagged(tmp_path):
    frames = [_frame(tmp_path, 0, (2, 2, 2)), _frame(tmp_path, 1, (1, 1, 1))]
    issues, _ = compute_temporal_checks(frames)
    assert [i for i in issues if i.detail.get("temporal") == "black"]


def test_captions_signal(tmp_path):
    m = MediaState(selector="#v", current_time=1.0, paused=False, ready_state=4,
                   video_width=640, captions=2, active_captions=1)
    m2 = MediaState(selector="#v", current_time=1.6, paused=False, ready_state=4,
                    video_width=640, captions=2, active_captions=1)
    issues, signals = compute_temporal_checks([_frame(tmp_path, 0, "gray", [m]),
                                               _frame(tmp_path, 1, "gray", [m2])])
    v = signals["videos"][0]
    assert v["captions"] == 2 and v["active_captions"] == 1
