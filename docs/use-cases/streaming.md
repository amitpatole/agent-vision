# AgentVision for streaming providers

Streaming teams ship a *lot* of UI — and increasingly build it with coding agents. Those
agents are blind, and the thing they're building is the hardest possible thing to verify from
source code: **behavior over time.** A screenshot can't tell you the video is playing, the
spinner cleared, the captions appeared, or the live tile updated. AgentVision's `watch` can.

> The core idea: a glance verifies *layout*; **watching** verifies *playback, loading, and
> liveness.** `agentvision watch` samples frames over a window and judges what changes.

## Why this is hard without it

| What "looks right" in a screenshot | …but is actually broken over time |
|---|---|
| A video frame is visible | Playback is **stalled/buffering** (frame frozen) |
| The player chrome rendered | The scene is a **black frame** (decode failed / DRM) |
| A caption line is shown | Captions are **mistimed** or never change |
| The dashboard has numbers | The live feed **stopped updating** (silent stall) |
| The page rendered | A transition/loader **never finished** |

## The trustworthy core (no API key)

`watch` reads **deterministic** signals — the streaming equivalent of our computed-style
contrast — straight from the page, not inferred from pixels:

- **`<video>` playback**: `currentTime` advancing across the window ⇒ *playing*; not advancing
  while `paused === false` ⇒ **stall/buffering** (a hard FAIL). `readyState` / `videoWidth`
  ⇒ has decoded frames (catches black/loading). `textTracks` ⇒ captions present & *showing*.
- **Pixel liveness** ⇒ is anything changing at all? **Stabilization** ⇒ did loading converge?
  **Black/blank-frame** detection across the window.

A vision backend adds a **time-aware** pass over the sampled frames (stitched into a labeled
contact sheet) for semantic judgment — "the scrubber doesn't move", "the ad never returns to
content", "the spinner is still up at t=2400ms".

## Use it

```bash
# Is the player actually playing (and are captions on)?
agentvision watch https://app.example.com/watch/123 --allow-local \
  --frames 6 --interval-ms 500 \
  --expect 'must: the video is playing' --expect 'should: captions are visible'

# Deterministic only (no key), great for CI gates:
agentvision watch http://localhost:3000/player --no-vision --quiet
```

```python
from agentvision import watch
report = await watch(url, frames=6, interval_ms=500)
signal = report.issues[0].detail["temporal"]   # {moving, stabilized, videos:[{playing,...}]}
```

Also available as the MCP tool `watch_artifact` and `POST /watch`.

## The three audiences, one capability

- **Media / OTT (Netflix/Disney/Roku-style):** player states (playing vs buffering vs black vs
  error), captions timing, scrubbing, ad insert/return, lazy artwork in carousels, and the
  10-ft TV / mobile / web matrix (pair `watch` with the responsive `sheet`). Combine with
  **conformance** to assert the intended player behavior, and **diff/baseline** to catch
  playback-UI regressions.
- **LLM / inference streaming providers:** token-streaming chat UIs — does markdown/code render
  progressively without layout jank as content streams? Playgrounds and latency dashboards.
- **Live data / observability:** the original strength (polling/websocket pages, freeze,
  settle) plus "did it actually update / stabilize / stall?" over the window.

## Eyes → brain (Verel)

A temporal `Report` flows through the [handoff](../handoff.md) like any other, so a brain
(e.g. [Verel](https://github.com/amitpatole/verel)) can gate a release on *verified playback*
and **compound** "the player plays with captions across builds" into memory — not re-checking
a claim it already proved.

## Honest limits

- `watch` needs a renderable, scriptable surface (URL/HTML). DRM-protected commercial streams
  may render as a black frame by design — which `watch` will *correctly* report as no decoded
  frames; that's a true signal, not a bug. Use test/clear content for green-path verification.
- Pixel liveness is global; a tiny animated element may read as "static" (video fills enough of
  the frame to register). The deterministic `<video>` signal is size-independent — prefer it.
- The vision pass is advisory, as always; the deterministic playback/stall signal is the gate.
