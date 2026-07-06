"""Motion source classification — video files and animated GIFs route to the temporal
grader, never the browser (blank-render misroute) or the frame-0 still path."""

from PIL import Image

from agentvision.config import load_settings
from agentvision.sources import resolve_source


def _settings(**kw):
    return load_settings(**kw)


def _animated_gif(path, n_frames=3, size=(40, 30), move=True):
    frames = []
    for i in range(n_frames):
        im = Image.new("RGB", size, "white")
        if move:
            for x in range(5):
                for y in range(5):
                    im.putpixel((min(size[0] - 1, i * 8 + x), y), (255, 0, 0))
        frames.append(im)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=100, loop=0)


def test_mp4_classifies_as_motion(tmp_path):
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"\x00" * 64)  # classification is by extension; decode happens later
    assert resolve_source(str(p), "auto", settings=_settings()).kind == "motion"


def test_other_video_extensions_classify_as_motion(tmp_path):
    for ext in (".webm", ".mov", ".m4v", ".avi", ".mkv"):
        p = tmp_path / f"clip{ext}"
        p.write_bytes(b"\x00" * 64)
        assert resolve_source(str(p), "auto", settings=_settings()).kind == "motion", ext


def test_mp4_never_routes_to_html(tmp_path):
    """Regression: the misroute that produced a misleading 'blank render' FAIL."""
    p = tmp_path / "video.mp4"
    p.write_bytes(b"\x00" * 64)
    assert resolve_source(str(p), "auto", settings=_settings()).kind != "html"


def test_animated_gif_classifies_as_motion(tmp_path):
    p = tmp_path / "anim.gif"
    _animated_gif(p, n_frames=3)
    assert resolve_source(str(p), "auto", settings=_settings()).kind == "motion"


def test_single_frame_gif_stays_image(tmp_path):
    """Back-compat: a still GIF is graded as a still."""
    p = tmp_path / "still.gif"
    Image.new("RGB", (40, 30), "white").save(p)
    assert resolve_source(str(p), "auto", settings=_settings()).kind == "image"


def test_explicit_image_type_overrides_animation(tmp_path):
    """A caller may deliberately grade an animated GIF as its first frame."""
    p = tmp_path / "anim.gif"
    _animated_gif(p, n_frames=3)
    assert resolve_source(str(p), "image", settings=_settings()).kind == "image"


def test_corrupt_gif_falls_back_to_image(tmp_path):
    """An unreadable GIF must not crash classification; the image path reports the error."""
    p = tmp_path / "broken.gif"
    p.write_bytes(b"GIF89a" + b"\xff" * 10)
    assert resolve_source(str(p), "auto", settings=_settings()).kind == "image"
