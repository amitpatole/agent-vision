"""Offline structural inspection for PowerPoint (.pptx) slides — deterministic, no LLM, no
egress.

The PPTX path otherwise rasterizes slides to a flat image, so offline AgentVision was blind
to slide-structure defects. This reads the OOXML for *where* text and tables are, then reads
the *rendered pixels* in those regions for the ground truth a flat raster can't give us:

* **Unreadable text (low contrast)** — bimodal (Otsu) pixel contrast inside each text box.
  Reading real composited pixels catches dark-on-dark and stacked-background cases that XML
  colors alone get wrong (a full-bleed shape behind the text).
* **Off-slide / clipped content** — a shape or table whose box extends past the slide edge.
* **Overlapping text boxes** — two text boxes colliding (one clips/obscures the other).

Honest limits (offline): text over a *photo* and table overflow that only appears at
render-time aren't reliably catchable here — those need the vision backend on the slide
image. This check is the no-key, no-egress floor.
"""

from __future__ import annotations

import re
import zipfile
from xml.etree import ElementTree as ET

from ...logging import get_logger
from ...models.geometry import BBox
from ...models.report import Confidence, Issue, IssueKind, IssueSource, Severity

log = get_logger("slides")

_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_EMU = 914400
_OFFSLIDE_IN = 0.35  # ignore tiny placeholder spill; flag a real run-off-the-edge
_OVERLAP_FRAC = 0.40
_CONTRAST_FAIL = 3.0  # clearly unreadable (e.g. dark-on-dark)
_CONTRAST_AA = 4.5  # borderline below AA


def _slide_xmls(z: zipfile.ZipFile) -> list[str]:
    names = [n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)]
    names.sort(key=lambda n: int(re.search(r"\d+", n).group()))
    return names


def _shapes(root: ET.Element):
    """Yield (x, y, cx, cy, text, is_table) in EMU for sized shapes/tables on a slide."""
    for sp in list(root.iter(f"{_P}sp")) + list(root.iter(f"{_P}graphicFrame")):
        xfrm = sp.find(f".//{_A}xfrm")
        if xfrm is None:
            continue
        off, ext = xfrm.find(f"{_A}off"), xfrm.find(f"{_A}ext")
        if off is None or ext is None:
            continue
        text = "".join(t.text or "" for t in sp.iter(f"{_A}t")).strip()
        yield (int(off.get("x")), int(off.get("y")), int(ext.get("cx")), int(ext.get("cy")),
               text, sp.tag.endswith("graphicFrame"))


def _relative_luminance(rgb) -> float:
    def f(v: float) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2])


def _contrast(a, b) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _bimodal_contrast(crop) -> tuple[float, float] | None:
    """Split a text-box crop into foreground/background by Otsu luminance and return
    (contrast_ratio, text_fraction). None if there's no discernible text."""
    import numpy as np

    arr = np.asarray(crop.convert("RGB")).reshape(-1, 3).astype(float)
    if len(arr) < 64:
        return None
    g = 0.2126 * arr[:, 0] + 0.7152 * arr[:, 1] + 0.0722 * arr[:, 2]
    hist, _ = np.histogram(g, bins=256, range=(0, 255))
    total = g.size
    sum_total = float((np.arange(256) * hist).sum())
    sum_b = w_b = 0.0
    best_var, thr = -1.0, 128
    for i in range(256):
        w_b += hist[i]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += i * hist[i]
        m_b = sum_b / w_b
        m_f = (sum_total - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best_var:
            best_var, thr = var, i
    cut = thr + 0.5  # split at the bin boundary so float luminance in bin `thr` lands left
    dark, light = arr[g <= cut], arr[g > cut]
    if len(dark) < 10 or len(light) < 10:
        return None
    minority, majority = (dark, light) if len(dark) < len(light) else (light, dark)
    frac = len(minority) / len(arr)
    if frac < 0.003:  # negligible ink — treat as no text
        return None
    return _contrast(minority.mean(0), majority.mean(0)), frac


def check_pptx(pptx_path, page_images: list[str], settings=None) -> list[Issue]:
    """Inspect a .pptx against its per-slide rendered images (slide order). Returns Issues."""
    try:
        from PIL import Image
    except ImportError:
        return []
    issues: list[Issue] = []
    try:
        z = zipfile.ZipFile(str(pptx_path))
    except (OSError, zipfile.BadZipFile):
        return []
    with z:
        try:
            pres = ET.fromstring(z.read("ppt/presentation.xml"))
            sz = pres.find(f"{_P}sldSz")
            slide_w, slide_h = int(sz.get("cx")), int(sz.get("cy"))
        except (KeyError, ET.ParseError, AttributeError, TypeError):
            return []
        slide_names = _slide_xmls(z)
        for idx, name in enumerate(slide_names):
            img_path = page_images[idx] if idx < len(page_images) else None
            try:
                root = ET.fromstring(z.read(name))
            except (KeyError, ET.ParseError):
                continue
            issues += _check_one_slide(root, idx + 1, slide_w, slide_h, img_path, Image)
    return issues


def _check_one_slide(root, slide_no, slide_w, slide_h, img_path, Image) -> list[Issue]:
    issues: list[Issue] = []
    img = None
    if img_path:
        try:
            img = Image.open(img_path)
        except (OSError, ValueError):
            img = None
    iw, ih = (img.size if img else (0, 0))
    sx, sy = (iw / slide_w, ih / slide_h) if img else (0, 0)
    tag = f"[slide {slide_no}]"
    text_boxes: list[tuple[int, int, int, int, str]] = []

    for x, y, cx, cy, text, is_table in _shapes(root):
        # Off-slide / clipped content (geometry).
        over_emu = max(x + cx - slide_w, y + cy - slide_h, -x, -y)
        if over_emu > _OFFSLIDE_IN * _EMU and (text or is_table):
            what = "A table" if is_table else f"Text {text[:40]!r}"
            issues.append(Issue.make(
                IssueKind.OVERFLOW, Severity.WARNING,
                f"{tag} {what} extends ~{over_emu / _EMU:.2f}in past the slide edge (clipped).",
                source=IssueSource.CV, confidence=Confidence.MEDIUM,
                detail={"slide": slide_no, "overflow_in": round(over_emu / _EMU, 2)},
            ))
        if text:
            text_boxes.append((x, y, cx, cy, text))
        # Pixel contrast within the text box (reads real composited pixels).
        if text and img is not None:
            px = (max(0, int(x * sx)), max(0, int(y * sy)),
                  min(iw, int((x + cx) * sx)), min(ih, int((y + cy) * sy)))
            if px[2] - px[0] >= 8 and px[3] - px[1] >= 8:
                res = _bimodal_contrast(img.crop(px))
                if res and res[0] < _CONTRAST_AA:
                    ratio, _frac = res
                    bbox = BBox(x=float(px[0]), y=float(px[1]),
                                width=float(px[2] - px[0]), height=float(px[3] - px[1]))
                    fail = ratio < _CONTRAST_FAIL
                    issues.append(Issue.make(
                        IssueKind.CONTRAST,
                        Severity.ERROR if fail else Severity.WARNING,
                        f"{tag} Text is hard to read — contrast ~{ratio:.1f}:1 "
                        f"(WCAG AA needs 4.5): {text[:40]!r}",
                        bbox=bbox, bbox_precise=True, source=IssueSource.CV,
                        confidence=Confidence.MEDIUM if fail else Confidence.LOW,
                        detail={"slide": slide_no, "ratio": round(ratio, 2)},
                    ))

    # Overlapping text boxes (one clips/obscures the other).
    for i in range(len(text_boxes)):
        ax, ay, aw, ah, at = text_boxes[i]
        for j in range(i + 1, len(text_boxes)):
            bx, by, bw, bh, bt = text_boxes[j]
            ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
            iy = max(0, min(ay + ah, by + bh) - max(ay, by))
            inter = ix * iy
            if inter and inter / min(aw * ah, bw * bh) > _OVERLAP_FRAC:
                issues.append(Issue.make(
                    IssueKind.OVERLAP, Severity.WARNING,
                    f"{tag} Two text boxes overlap — {at[:24]!r} collides with {bt[:24]!r}.",
                    source=IssueSource.CV, confidence=Confidence.MEDIUM,
                    detail={"slide": slide_no},
                ))
    return issues
