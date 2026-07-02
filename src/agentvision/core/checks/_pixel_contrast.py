"""Shared pixel-level WCAG contrast math (used by the PPTX inspector and the DOM-over-raster
contrast check).

Computed-style contrast reads a CSS ``color`` vs ``background-color``; over a ``<canvas>`` /
raster tile / gradient there is *no* CSS background to read, so legibility has to be measured
from the rendered bitmap. These helpers do that: an Otsu split separates ink from background
inside a text crop, and ``worst_case_contrast`` grades the ink against the lowest-contrast
background patch under the text — because contrast can swing across a heatmap within a few
pixels, a single average would hide the unreadable region.
"""

from __future__ import annotations


def relative_luminance(rgb) -> float:
    """WCAG relative luminance of an sRGB triple (0–255)."""
    def f(v: float) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2])


def contrast_ratio(a, b) -> float:
    """WCAG contrast ratio between two sRGB triples."""
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _otsu_threshold(g) -> int:
    """Otsu's method: the grayscale cut that maximises between-class variance."""
    import numpy as np

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
    return thr


def _luma(arr):
    # arr is an (N, 3) float ndarray — vectorised luminance, no direct numpy call needed.
    return 0.2126 * arr[:, 0] + 0.7152 * arr[:, 1] + 0.0722 * arr[:, 2]  # noqa: E226


def bimodal_contrast(crop) -> tuple[float, float] | None:
    """Split a text-box crop into foreground/background by Otsu luminance and return
    ``(contrast_ratio, text_fraction)``. ``None`` if there's no discernible text.

    This is the average-vs-average measure the PPTX inspector uses.
    """
    import numpy as np

    arr = np.asarray(crop.convert("RGB")).reshape(-1, 3).astype(float)
    if len(arr) < 64:
        return None
    g = _luma(arr)
    cut = _otsu_threshold(g) + 0.5  # split at the bin boundary
    dark, light = arr[g <= cut], arr[g > cut]
    if len(dark) < 10 or len(light) < 10:
        return None
    minority, majority = (dark, light) if len(dark) < len(light) else (light, dark)
    frac = len(minority) / len(arr)
    if frac < 0.003:  # negligible ink — treat as no text
        return None
    return contrast_ratio(minority.mean(0), majority.mean(0)), frac


def worst_case_contrast(crop) -> tuple[float, float, tuple, tuple] | None:
    """Grade text legibility over a variable background (canvas/heatmap/gradient).

    Otsu-splits the crop into ink (minority cluster) vs background (majority), then measures
    the ink against the **worst** (lowest-contrast) meaningful background patch under the text
    — so text that is readable over the dark part of a map but not the light part is caught.

    Returns ``(worst_ratio, ink_fraction, ink_rgb, worst_bg_rgb)`` or ``None`` if there's no
    discernible text.
    """
    import numpy as np

    arr = np.asarray(crop.convert("RGB")).reshape(-1, 3).astype(float)
    if len(arr) < 64:
        return None
    g = _luma(arr)
    cut = _otsu_threshold(g) + 0.5
    dark, light = arr[g <= cut], arr[g > cut]
    if len(dark) < 10 or len(light) < 10:
        return None
    ink, bg = (dark, light) if len(dark) <= len(light) else (light, dark)
    frac = len(ink) / len(arr)
    if frac < 0.003:  # negligible ink — treat as no text
        return None
    ink_rgb = ink.mean(0)
    # Split the background into its own light/dark halves; keep only patches large enough to be
    # real regions (not anti-aliasing fringe), then take the one giving the lowest contrast.
    bg_g = _luma(bg)
    med = float(np.median(bg_g))
    min_px = max(10, int(0.15 * len(bg)))
    cands = [c.mean(0) for c in (bg[bg_g <= med], bg[bg_g > med]) if len(c) >= min_px]
    if not cands:
        cands = [bg.mean(0)]
    worst_bg = min(cands, key=lambda c: contrast_ratio(ink_rgb, c))
    return contrast_ratio(ink_rgb, worst_bg), frac, tuple(ink_rgb), tuple(worst_bg)
