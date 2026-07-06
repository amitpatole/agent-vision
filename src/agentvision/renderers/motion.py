"""Local motion media (video files + animated GIFs) -> sampled ``Frame`` sequence.

Feeds the existing temporal grader (``core/temporal.py`` — "judge what happens *over
time*, not in a single frame"), the same path ``watch`` uses for ``<video>``-on-a-page.
This is an ingestion path, not new grading science: a video file must never be handed to
the browser (blank render → misleading FAIL) and an animated GIF must never be flattened
to frame 0 (all motion requirements silently "not depicted").

Security — a media decoder consuming untrusted bytes is an attack surface, so decode is
bounded the same way LibreOffice conversion is (see ``office.py``):

- gated by ``settings.allow_motion_render`` (**off on the REST service**);
- **byte cap** (``max_document_bytes``) before any decode;
- ffmpeg invoked in **argv form, never a shell**, with the input as an **absolute path**
  (a ``-``-leading filename can't become a flag) placed after ``-i``;
- **hard timeout with process-group kill** per invocation (``start_new_session=True``);
- frame dimensions are probed and refused above the image pixel cap (decompression-bomb
  guard), and extracted frames are downscaled to a bounded edge;
- animated GIFs decode via Pillow under ``open_image_safely`` (byte + pixel caps).

ffmpeg resolves from PATH, falling back to the ``imageio-ffmpeg`` wheel (the ``[motion]``
extra) — absent both, this fails closed with an actionable install message.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
import time
from pathlib import Path

from ..config import Settings
from ..errors import MissingDependencyError, RenderError
from ..models.geometry import Viewport
from ..sources import ResolvedSource
from .base import Frame, RenderedImage, RenderResult, RenderSpec

_FRAME_MAX_EDGE = 2000  # extracted-frame downscale bound (matches vision_max_edge_px default)
_GIF_MAX_FRAMES = 10_000  # cap GIF frame iteration (a tiny file can declare huge frame counts)
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")
_DIMENSIONS_RE = re.compile(r"Video:.*?\b(\d{2,6})x(\d{2,6})\b")
_INPUT_FORMAT_RE = re.compile(r"Input #0,\s*([\w,]+),")

# ffmpeg detects the container by CONTENT, not extension — a file named `.mp4` holding an
# HLS/m3u8 playlist or a concat script would make ffmpeg dereference other URLs/files (SSRF /
# local-file inclusion). Two layers close it:
#   1) `-protocol_whitelist file` — the decoder can only ever open local files, never a
#      network protocol (kills the SSRF half outright);
#   2) the detected demuxer must be one of the real containers we support — playlist-style
#      formats (hls, concat, m3u8, ffmetadata, …) are refused before any extraction runs.
_ALLOWED_DEMUXERS = {"mov", "mp4", "m4a", "3gp", "3g2", "mj2", "matroska", "webm", "avi", "gif"}


def find_ffmpeg() -> str | None:
    """Resolve an ffmpeg binary: PATH first, then the imageio-ffmpeg wheel (``[motion]``)."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg  # type: ignore[import-not-found]

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # noqa: BLE001  # not installed / no bundled binary for this platform
        return None


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


async def _run_ffmpeg(argv: list[str], timeout_s: float) -> tuple[int, str]:
    """Run ffmpeg (argv form, own process group, hard timeout). Returns (rc, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL,
        start_new_session=True,  # own process group so a hung decoder tree dies together
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        _kill_group(proc)
        raise RenderError(
            f"ffmpeg timed out after {timeout_s}s (motion_decode_timeout_s) — refusing to "
            "let a malformed media file hold the process."
        ) from None
    return proc.returncode or 0, (err or b"").decode("utf-8", "replace")


class MotionRenderer:
    """Sample a local video / animated GIF into ``Frame``s for the temporal grader."""

    SUPPORTED = {"motion"}

    def __init__(self, settings: Settings):
        self.settings = settings

    def supports(self, kind: str) -> bool:
        return kind in self.SUPPORTED

    # -- shared guards ---------------------------------------------------------------

    def _checked_path(self, resolved: ResolvedSource) -> Path:
        if resolved.path is None:
            raise RenderError("Motion source must be a local file path.")
        if not self.settings.allow_motion_render:
            raise RenderError(
                "Motion media rendering is disabled (allow_motion_render=False). It is off "
                "by default on the REST service because a media decoder is an attack surface "
                "on untrusted input; use the CLI/library, or enable it only for trusted files."
            )
        path = resolved.path.resolve()
        try:
            nbytes = path.stat().st_size
        except OSError as e:
            raise RenderError(f"Cannot stat motion source: {e}") from e
        if nbytes > self.settings.max_document_bytes:
            raise RenderError(
                f"Motion file is {nbytes} bytes, over the {self.settings.max_document_bytes}-"
                "byte cap (max_document_bytes; DoS protection)."
            )
        return path

    # -- Renderer protocol -----------------------------------------------------------

    async def render(self, spec: RenderSpec, resolved: ResolvedSource,
                     out_dir: Path) -> RenderResult:
        """Single-shot render: the sampled frames become the image list (frame 0 primary)."""
        frames = await self.render_sequence(
            spec, resolved, out_dir, frames=self.settings.motion_frames,
            interval_ms=0,
        )
        images = [
            RenderedImage(path=f.image_path,
                          viewport=Viewport(width=f.width, height=f.height),
                          width=f.width, height=f.height)
            for f in frames
        ]
        return RenderResult(images=images, source_type="motion")

    async def render_sequence(self, spec: RenderSpec, resolved: ResolvedSource,
                              out_dir: Path, *, frames: int,
                              interval_ms: int = 0) -> list[Frame]:
        """Sample ``frames`` images evenly across the media's duration.

        ``interval_ms`` is ignored for files — sampling always spans the full duration so
        the story (start → middle → end) is what gets graded, not one arbitrary window.
        """
        path = self._checked_path(resolved)
        out_dir.mkdir(parents=True, exist_ok=True)
        # Clamp even for direct library callers (defense in depth; `watch` clamps too).
        n = max(2, min(frames, self.settings.watch_max_frames))
        if path.suffix.lower() == ".gif":
            return self._gif_frames(path, out_dir, n)
        return await self._video_frames(path, out_dir, n)

    # -- animated GIF (Pillow — no ffmpeg needed) --------------------------------------

    def _gif_frames(self, path: Path, out_dir: Path, n: int) -> list[Frame]:
        from ..imageguard import open_image_safely

        with open_image_safely(path) as im:
            total = int(getattr(im, "n_frames", 1))
            if total < 2:
                raise RenderError(
                    "GIF has a single frame — it should be classified as an image, not motion."
                )
            if total > _GIF_MAX_FRAMES:
                raise RenderError(
                    f"GIF declares {total} frames, over the {_GIF_MAX_FRAMES}-frame cap "
                    "(DoS protection)."
                )
            k = min(n, total)
            picks = {round(i * (total - 1) / (k - 1)) for i in range(k)}
            last_pick = max(picks)
            frames: list[Frame] = []
            t_ms = 0
            try:
                for idx in range(total):
                    im.seek(idx)  # EOFError on a truncated GIF -> clean RenderError below
                    dur = int(im.info.get("duration", 100) or 100)
                    if idx in picks:
                        p = out_dir / f"frame_{len(frames):02d}.png"
                        rgb = im.convert("RGB")
                        rgb.save(p, "PNG")
                        frames.append(Frame(index=len(frames), t_ms=t_ms, image_path=str(p),
                                            width=rgb.width, height=rgb.height))
                    if idx >= last_pick:
                        break  # no need to walk the tail after the final sampled frame
                    t_ms += dur
            except (EOFError, OSError, ValueError) as e:
                raise RenderError(f"Could not decode GIF frames (truncated/corrupt?): {e}") from e
        if len(frames) < 2:
            raise RenderError("GIF decoded fewer than 2 usable frames — nothing temporal to grade.")
        return frames

    # -- video (ffmpeg) ----------------------------------------------------------------

    async def _video_frames(self, path: Path, out_dir: Path, n: int) -> list[Frame]:
        exe = find_ffmpeg()
        if not exe:
            raise MissingDependencyError(
                "Grading a video file needs ffmpeg. Install it (dnf/apt install ffmpeg) or "
                "pip install 'agentvision[motion]' (bundles a static ffmpeg). "
                "`agentvision doctor` reports motion readiness."
            )
        duration_s, width, height = await self._probe(exe, path)
        from ..imageguard import MAX_IMAGE_PIXELS

        if width * height > MAX_IMAGE_PIXELS:
            raise RenderError(
                f"Video frame dimensions {width}x{height} exceed the {MAX_IMAGE_PIXELS}-pixel "
                "cap (decompression-bomb protection)."
            )
        # Sample evenly across [0, duration): the last pick backs off from EOF — the header
        # duration often exceeds the last decodable frame's timestamp, so an exact-EOF seek
        # returns nothing.
        times = [duration_s * i / (n - 1) for i in range(n)]
        times[-1] = max(0.0, duration_s - max(0.25, 0.02 * duration_s))
        per_call = self.settings.motion_decode_timeout_s
        # Overall wall-clock budget across ALL extractions — a per-invocation timeout alone
        # lets a pathological file that stalls just under the limit each frame accumulate to
        # minutes (per_call × n). Bound the whole sequence like the browser render path does.
        deadline = time.monotonic() + self.settings.render_timeout_s
        frames: list[Frame] = []
        for i, t in enumerate(times):
            out_png = out_dir / f"frame_{i:02d}.png"
            rc, err = -1, ""
            for attempt_t in (t, max(0.0, t - 1.0)):  # one step-back retry near EOF
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RenderError(
                        f"Motion decode exceeded the overall {self.settings.render_timeout_s}s "
                        f"budget after {i} frame(s) (render_timeout_s; raise it for long clips)."
                    )
                argv = [
                    exe, "-hide_banner", "-loglevel", "error", "-nostdin",
                    "-protocol_whitelist", "file",    # never a network protocol (SSRF guard)
                    "-ss", f"{attempt_t:.3f}",
                    "-i", str(path),                  # absolute path: can't read as a flag
                    "-frames:v", "1",
                    "-vf", f"scale=min({_FRAME_MAX_EDGE}\\,iw):-2",  # bound the output edge
                    "-y", str(out_png),
                ]
                rc, err = await _run_ffmpeg(argv, min(per_call, remaining))
                if rc == 0 and out_png.exists() and out_png.stat().st_size > 0:
                    t = attempt_t
                    break
            else:
                raise RenderError(
                    f"ffmpeg failed to extract a frame at t={t:.2f}s "
                    f"(rc={rc}): {err.strip()[:400] or 'no output produced'}"
                )
            from ..imageguard import open_image_safely

            with open_image_safely(out_png) as im:
                fw, fh = im.size
            frames.append(Frame(index=i, t_ms=int(t * 1000), image_path=str(out_png),
                                width=fw, height=fh))
        return frames

    async def _probe(self, exe: str, path: Path) -> tuple[float, int, int]:
        """Duration (s) + frame dimensions, parsed from ``ffmpeg -i`` (no ffprobe needed).

        Refuses playlist-style demuxers (hls/concat/…): ffmpeg picks the demuxer from file
        CONTENT, so a ``.mp4`` extension proves nothing about what the bytes will do.
        """
        rc, err = await _run_ffmpeg(
            [exe, "-hide_banner", "-nostdin", "-protocol_whitelist", "file", "-i", str(path)],
            self.settings.motion_decode_timeout_s,
        )
        # `ffmpeg -i` with no output exits non-zero by design; the metadata is on stderr.
        fmt = _INPUT_FORMAT_RE.search(err)
        if fmt:
            detected = {p.strip() for p in fmt.group(1).split(",")}
            if not detected & _ALLOWED_DEMUXERS:
                raise RenderError(
                    f"Refusing to decode: detected container {fmt.group(1)!r} is not a "
                    "supported video format (playlist/script-style inputs are blocked — "
                    "they can reference other files or URLs)."
                )
        m = _DURATION_RE.search(err)
        if not m:
            raise RenderError(
                "Could not determine media duration — the file may be corrupt or not a "
                f"video: {err.strip()[:400]}"
            )
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        if duration <= 0:
            raise RenderError("Media reports zero duration — nothing to sample.")
        d = _DIMENSIONS_RE.search(err)
        if not d:
            raise RenderError("Could not determine video dimensions from the stream header.")
        return duration, int(d.group(1)), int(d.group(2))
