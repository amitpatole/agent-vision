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


def crop_bbox(img, bbox, min_side: int = 8):
    """Crop ``img`` to ``bbox`` (image px), clamped to the image bounds. ``None`` if the
    clamped region is smaller than ``min_side`` on either axis (too small to grade)."""
    iw, ih = img.size
    x0 = max(0, int(bbox.x))
    y0 = max(0, int(bbox.y))
    x1 = min(iw, int(bbox.x + bbox.width))
    y1 = min(ih, int(bbox.y + bbox.height))
    if x1 - x0 < min_side or y1 - y0 < min_side:
        return None
    return img.crop((x0, y0, x1, y1))


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


def exact_fg_contrast(crop, fg_rgb: tuple, alpha: float = 1.0) -> float | None:
    """Contrast of a KNOWN text colour against the real backdrop pixels in ``crop``.

    Unlike :func:`worst_case_contrast` (which assumes the minority cluster is the ink), the ink
    cluster here is the one closest to ``fg_rgb``, so a bold headline filling most of its glyph
    box is not mistaken for background. The backdrop is split into light/dark halves and the
    worse one is used. Returns ``None`` when the crop has no second cluster to measure.
    """
    import numpy as np

    arr = np.asarray(crop.convert("RGB")).reshape(-1, 3).astype(float)
    if len(arr) < 64:
        return None
    g = _luma(arr)
    cut = _otsu_threshold(g) + 0.5
    a_cl, b_cl = arr[g <= cut], arr[g > cut]
    if len(a_cl) < 10 or len(b_cl) < 10:
        return None
    fg = tuple(float(v) for v in fg_rgb[:3])
    near_a = contrast_ratio(fg, a_cl.mean(0)) <= contrast_ratio(fg, b_cl.mean(0))
    near = a_cl if near_a else b_cl
    bg = b_cl if near_a else a_cl
    if len(near) > 0.6 * len(arr):
        # The text-coloured cluster dominates the line box: the backdrop itself is ~the text
        # colour (black text on mostly-black stripes). Grade against that, not the minority.
        return contrast_ratio(fg, tuple(near.mean(0)))
    # Same rule per line-height tile: part of a line on a text-coloured backdrop (a gradient
    # that is black for the first third) is invisible there even if the line as a whole isn't.
    w, h = crop.size
    if w >= 2 * h and h >= 8:
        img = np.asarray(crop.convert("RGB")).astype(float)
        gimg = _luma(img.reshape(-1, 3)).reshape(h, w)
        near_low = near_a  # the fg-near cluster is the <= cut side when near_a
        for x0 in range(0, w - h + 1, max(1, h // 2)):
            tile_g = gimg[:, x0:x0 + h]
            tile_near = (tile_g <= cut) if near_low else (tile_g > cut)
            if tile_near.mean() > 0.6:
                tpx = img[:, x0:x0 + h].reshape(-1, 3)[tile_near.reshape(-1)]
                return contrast_ratio(fg, tuple(tpx.mean(0)))
    bg_g = _luma(bg)
    med = float(np.median(bg_g))
    min_px = max(10, int(0.15 * len(bg)))
    cands = [c.mean(0) for c in (bg[bg_g <= med], bg[bg_g > med]) if len(c) >= min_px]
    if not cands:
        cands = [bg.mean(0)]

    def _painted(px):
        return tuple(fg[i] * alpha + px[i] * (1 - alpha) for i in range(3))

    return min(contrast_ratio(_painted(c), c) for c in cands)


def _fill_contrast(rgb, fg):
    import numpy as np

    def _rl(v):
        v = v / 255.0
        return np.where(v <= 0.03928, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)

    px = rgb.reshape(-1, 3)
    rl = 0.2126 * _rl(px[:, 0]) + 0.7152 * _rl(px[:, 1]) + 0.0722 * _rl(px[:, 2])
    fr = 0.2126 * _rl(fg[0]) + 0.7152 * _rl(fg[1]) + 0.0722 * _rl(fg[2])
    return (np.maximum(rl, fr) + 0.05) / (np.minimum(rl, fr) + 0.05)


def halo_painted(img, rect, fg_rgb: tuple, need: float = 4.5) -> bool:
    """A text halo is only real if it is painted AROUND THE GLYPHS. Compare the share of pixels
    contrasting with the fill (>= 2:1) inside the line box against a band just above and
    below it: a halo concentrates inside, backdrop texture (dots, noise) does not. If the
    surrounding backdrop itself contrasts with the fill, the text is legible on its own.
    Measured 2026-10-22: real halos 9-20% inside vs ~0% outside; a faint 1px outline <= 0.3%;
    an off-screen shadow 0%; a dotted backdrop similar inside and out."""
    import numpy as np

    iw, ih = img.size
    x0, x1 = max(0, int(rect.x)), min(iw, int(rect.x + rect.width))
    y0, y1 = max(0, int(rect.y)), min(ih, int(rect.y + rect.height))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return False
    fg = np.array([float(v) for v in fg_rgb[:3]])
    inside = np.asarray(img.crop((x0, y0, x1, y1)).convert("RGB")).astype(float)
    band = max(4, (y1 - y0) // 2)
    outs = []
    if y0 - band >= 0:
        outs.append(np.asarray(img.crop((x0, y0 - band, x1, y0)).convert("RGB")).astype(float))
    if y1 + band <= ih:
        outs.append(np.asarray(img.crop((x0, y1, x1, y1 + band)).convert("RGB")).astype(float))
    if not outs:
        return False
    h = y1 - y0
    in_cr = _fill_contrast(inside, fg).reshape(inside.shape[0], inside.shape[1])
    in_c = in_cr >= 2.0
    in_dark = in_cr >= need  # halo pixels must reach the text's own AA bar (3 large, 4.5 normal)
    in_aa = in_cr >= need
    # Backdrop pixels only (the glyphs themselves are the fill colour and never contrast).
    backdrop = np.sqrt(((inside - fg) ** 2).sum(-1)) >= 40
    out_cr = [_fill_contrast(o, fg).reshape(o.shape[0], o.shape[1]) for o in outs]
    out_c = [o >= 2.0 for o in out_cr]
    out_dark = [o >= need for o in out_cr]
    # Judge each line-height tile on its own: a backdrop can contrast on one side only (a
    # gradient hero), and texture can be local.
    ok_tiles = tiles = 0
    for tx in range(0, inside.shape[1], h):
        sl = slice(tx, min(inside.shape[1], tx + h))
        in_frac = float(in_c[:, sl].mean())
        out_frac = float(np.concatenate([o[:, sl].reshape(-1) for o in out_c]).mean())
        tiles += 1
        # The backdrop INSIDE the line meeting the AA bar against the fill makes the text
        # legible on its own (a dark band above/below the line proves nothing, and a 2:1
        # mid-grey backdrop is not "legible").
        bd = backdrop[:, sl]
        bd_aa = float(in_aa[:, sl][bd].mean()) if bd.any() else 0.0
        dark_in = float(in_dark[:, sl].mean())
        dark_out = float(np.concatenate([o[:, sl].reshape(-1) for o in out_dark]).mean())
        # Legible if: the backdrop itself meets AA against the fill; or a halo concentrates
        # around the glyphs vs the bands (soft halo at >= 2:1 on a clean backdrop, or a dark
        # one reaching the text's AA bar when the backdrop is mid-tone). Calibrated 2026-10-22 on real hero/byline halos vs fakes
        # (off-screen, faint 1px, half-alpha over mid-grey, textured or banded backdrops).
        # A halo SURROUNDS the glyphs, so its pixels spread across most rows and columns of
        # the tile; a stripe or bar of backdrop crossing the line occupies a few rows only.
        # Rows >= 30% (lowercase-only stretches of small text fill just the x-height); a
        # backdrop stripe across a line covers <= ~27% of its rows.
        def _spread(mask):
            return float(mask.any(axis=1).mean()) >= 0.3 and float(mask.any(axis=0).mean()) >= 0.5

        soft = (in_frac >= 0.04 and (in_frac >= 3.0 * out_frac or in_frac >= out_frac + 0.15)
                and _spread(in_c[:, sl]))
        dark = dark_in >= 0.03 and dark_in >= 3.0 * dark_out and _spread(in_dark[:, sl])
        if bd_aa >= 0.5 or soft or dark:
            ok_tiles += 1
    return tiles > 0 and ok_tiles >= 0.8 * tiles
