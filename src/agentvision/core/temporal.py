"""Temporal verification — judge what happens *over time*, not in a single frame.

Streaming correctness is temporal: does the video actually play, does the buffering spinner
clear, do captions appear, does the live tile update, does a transition finish, is anything
stalled/frozen/black/flickering. This module computes **deterministic** signals from a
sequence of sampled frames (+ per-frame `<video>` state) — the trustworthy half; a vision
pass over the frames adds semantic judgment on top.

Findings reuse existing `IssueKind`s (with a ``temporal`` tag in ``detail``) so the
verdict-bus contract — and any consumer mirroring it (e.g. Verel) — stays stable.
"""

from __future__ import annotations

from ..models.report import (
    Confidence,
    Issue,
    IssueKind,
    IssueSource,
    Severity,
)
from ..renderers.base import Frame

_MOTION_EPS = 0.002   # changed-pixel fraction above which a pair of frames "moved"
_SETTLE_EPS = 0.004   # below this, consecutive frames are effectively stable
_TIME_EPS = 0.05      # seconds of currentTime advance that counts as real playback


def _gray(path: str):
    import numpy as np

    from ..imageguard import open_image_safely

    return np.asarray(open_image_safely(path).convert("L"), dtype="int16")


def changed_ratio(a_path: str, b_path: str, thresh: int = 16) -> float:
    """Fraction of pixels that changed meaningfully between two frames."""
    import numpy as np

    from ..imageguard import open_image_safely

    a = _gray(a_path)
    b = _gray(b_path)
    if a.shape != b.shape:
        b = np.asarray(
            open_image_safely(b_path).convert("L").resize((a.shape[1], a.shape[0])),
            dtype="int16",
        )
    return float((np.abs(a - b) > thresh).mean())


def _frame_stats(path: str) -> tuple[float, float]:
    arr = _gray(path)
    return float(arr.mean()), float(arr.std())


def compute_temporal_checks(frames: list[Frame]) -> tuple[list[Issue], dict]:
    """Return ``(issues, signals)`` from a frame sequence (deterministic, no LLM)."""
    issues: list[Issue] = []
    if len(frames) < 2:
        return issues, {"frames": len(frames), "moving": False, "stabilized": True, "videos": []}

    diffs = [changed_ratio(frames[i - 1].image_path, frames[i].image_path)
             for i in range(1, len(frames))]
    max_change = max(diffs)
    last_change = diffs[-1]
    moving = max_change > _MOTION_EPS
    stabilized = last_change < _SETTLE_EPS
    window_ms = frames[-1].t_ms - frames[0].t_ms

    # Black / blank across the whole window.
    stats = [_frame_stats(f.image_path) for f in frames]
    if all(m < 12 for m, _ in stats):
        issues.append(Issue.make(
            IssueKind.BLANK, Severity.ERROR, "Frames are black/near-black for the whole window.",
            source=IssueSource.CV, confidence=Confidence.HIGH, detail={"temporal": "black"}))
    elif all(s < 4 for _, s in stats):
        issues.append(Issue.make(
            IssueKind.BLANK, Severity.WARNING, "Frames are blank (no content) across the window.",
            source=IssueSource.CV, confidence=Confidence.HIGH, detail={"temporal": "blank"}))

    # Per-<video> playback (deterministic, from the media element).
    videos: list[dict] = []
    by_sel: dict[str, list] = {}
    for fr in frames:
        for m in fr.media:
            by_sel.setdefault(m.selector, []).append(m)
    for sel, states in by_sel.items():
        first, last = states[0], states[-1]
        advanced = last.current_time - first.current_time
        playing = advanced > _TIME_EPS and not last.paused
        has_frames = any(s.video_width > 0 for s in states) or last.ready_state >= 2
        active_caps = max(s.active_captions for s in states)
        caps = max(s.captions for s in states)
        videos.append({
            "selector": sel, "playing": playing, "paused": bool(last.paused),
            "ended": bool(last.ended), "advanced_s": round(advanced, 3),
            "has_frames": has_frames, "captions": caps, "active_captions": active_caps,
        })
        if last.ended:
            continue
        if not last.paused and advanced <= _TIME_EPS:
            issues.append(Issue.make(
                IssueKind.OTHER, Severity.ERROR,
                f"Video {sel!r} is not playing — currentTime did not advance "
                f"({advanced:.2f}s over {window_ms}ms) while not paused (stalled/buffering).",
                source=IssueSource.DOM, confidence=Confidence.HIGH,
                detail={"temporal": "stall", "selector": sel}))
        elif not has_frames:
            issues.append(Issue.make(
                IssueKind.OTHER, Severity.WARNING,
                f"Video {sel!r} has no decoded frames (readyState<2, videoWidth=0) — black/loading?",
                source=IssueSource.DOM, confidence=Confidence.HIGH,
                detail={"temporal": "no_frames", "selector": sel}))

    signals = {
        "frames": len(frames), "window_ms": window_ms,
        "max_change": round(max_change, 4), "last_change": round(last_change, 4),
        "moving": moving, "stabilized": stabilized, "videos": videos,
    }
    return issues, signals


def temporal_summary(signals: dict) -> str:
    n = signals.get("frames", 0)
    win = signals.get("window_ms", 0)
    bits = [f"{n} frames over {win}ms"]
    bits.append("moving" if signals.get("moving") else "static")
    bits.append("stabilized" if signals.get("stabilized") else "still-changing")
    for v in signals.get("videos", []):
        state = ("playing" if v["playing"] else "ended" if v["ended"]
                 else "paused" if v["paused"] else "stalled")
        cap = f", captions {v['active_captions']}/{v['captions']}" if v["captions"] else ""
        bits.append(f"video {v['selector']}: {state}{cap}")
    return "; ".join(bits)
