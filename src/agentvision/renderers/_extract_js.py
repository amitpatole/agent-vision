"""In-page JavaScript that extracts DOM geometry, computed-style WCAG contrast, and
broken images. All rectangles are returned in DOCUMENT-space CSS pixels
(getBoundingClientRect + scroll offset); the Python side multiplies by device_scale to
reach image pixels.
"""

EXTRACT_JS = r"""
(opts) => {
  // Whole-pass time budget + element cap: an attacker-shaped DOM must not stall grading into a
  // render timeout (denial of grade). If EITHER limit (or the svg-clip cap) is hit, the result
  // is flagged ``truncated`` and the report grades it as an ERROR: unchecked is never clean.
  const T0 = performance.now();
  const BUDGET_MS = (opts && opts.budgetMs) || 4000;
  const MAX_ELEMENTS = (opts && opts.maxElements) || 20000;
  let truncated = false;
  const overBudget = () => {
    if (!truncated && performance.now() - T0 > BUDGET_MS) truncated = true;
    return truncated;
  };
  const docX = window.scrollX || 0, docY = window.scrollY || 0;
  const rectOf = (el) => {
    const r = el.getBoundingClientRect();
    return { x: r.left + docX, y: r.top + docY, w: r.width, h: r.height };
  };
  const selectorOf = (el) => {
    if (el.id) return '#' + el.id;
    let s = el.tagName.toLowerCase();
    if (el.classList && el.classList.length) s += '.' + [...el.classList].slice(0,2).join('.');
    return s;
  };
  // Computed colours are legacy "rgb(r, g, b)" for sRGB, but modern CSS (oklch(), lab(),
  // color(srgb ...)) comes back in its own syntax. Anything else is resolved to sRGB by
  // painting one pixel — skipping it (or assuming white) would silently drop contrast checks.
  const _colorCache = new Map();
  let _cctx = null;
  const parseColor = (c) => {
    if (!c) return null;
    const m = c.match(/^rgba?\(([^)]+)\)$/);
    if (m && m[1].indexOf(',') >= 0) {
      const p = m[1].split(',').map(s => parseFloat(s.trim()));
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
    }
    if (_colorCache.has(c)) return _colorCache.get(c);
    let out = null;
    try {
      if (!_cctx) {
        const cv = document.createElement('canvas'); cv.width = 1; cv.height = 1;
        _cctx = cv.getContext('2d', { willReadFrequently: true });
      }
      _cctx.clearRect(0, 0, 1, 1);
      _cctx.fillStyle = '#000'; _cctx.fillStyle = c;   // an invalid value leaves #000
      _cctx.fillRect(0, 0, 1, 1);
      const d = _cctx.getImageData(0, 0, 1, 1).data;
      out = { r: d[0], g: d[1], b: d[2], a: d[3] / 255 };
    } catch (e) { out = null; }
    if (_colorCache.size < 500) _colorCache.set(c, out);
    return out;
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); };
    return 0.2126*f(c.r) + 0.7152*f(c.g) + 0.0722*f(c.b);
  };
  const ratio = (a, b) => {
    const l1 = lum(a), l2 = lum(b);
    const hi = Math.max(l1, l2), lo = Math.min(l1, l2);
    return (hi + 0.05) / (lo + 0.05);
  };
  const isVisible = (el, st) => {
    const r = el.getBoundingClientRect();
    return st.display !== 'none' && st.visibility !== 'hidden' &&
           parseFloat(st.opacity || '1') > 0.05 && r.width > 1 && r.height > 1;
  };
  const directText = (el) => {
    let t = '';
    for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent;
    return t.trim();
  };

  // Each line box of the element's OWN text nodes, separately (capped). Pixel grading crops
  // these one by one, so a child element's ink or an underline between lines can't stand in.
  const textRects = (el) => {
    const out = [];
    for (const n of el.childNodes) {
      if (n.nodeType !== 3 || !n.textContent.trim()) continue;
      const rg = document.createRange(); rg.selectNodeContents(n);
      for (const q of rg.getClientRects()) {
        if (q.width < 1 || q.height < 1) continue;
        out.push({ x: q.left + docX, y: q.top + docY, w: q.width, h: q.height });
        if (out.length >= 2000) { truncated = true; break; }   // never silently ungraded
      }
      if (out.length >= 2000) break;
    }
    // Grade at most 40 lines, sampled evenly and always including the first and last, so a
    // long block cannot hide unreadable lines past a fixed cap.
    if (out.length <= 40) return out;
    const keep = [];
    for (let i = 0; i < 40; i++) keep.push(out[Math.round(i * (out.length - 1) / 39)]);
    return keep;
  };
  // Union rect of an element's OWN text nodes (not its padding box): what is actually painted.
  const textRect = (el) => {
    let l = Infinity, t = Infinity, r = -Infinity, b = -Infinity;
    for (const n of el.childNodes) {
      if (n.nodeType !== 3 || !n.textContent.trim()) continue;
      const rg = document.createRange(); rg.selectNodeContents(n);
      for (const q of rg.getClientRects()) {
        if (q.width < 1 || q.height < 1) continue;
        l = Math.min(l, q.left); t = Math.min(t, q.top);
        r = Math.max(r, q.right); b = Math.max(b, q.bottom);
      }
    }
    return l === Infinity ? null : { left: l, top: t, right: r, bottom: b };
  };
  const hardClips = (v) => v === 'hidden' || v === 'clip';
  // Per-font line-box ratio (content-area height / font-size), from canvas text metrics: no DOM
  // is touched (the page can't observe it), and page CSS / writing-mode can't skew it.
  const _fontRatio = new Map();
  let _mctx = null;
  // [boxRatio, inkScale] per font. boxRatio = content-area height / font-size (from the font's
  // box metrics). inkScale = how big the glyph INK is versus a normal font: capital-H ink
  // height at 100px / 65. Box metrics are page-controllable (@font-face ascent/descent
  // overrides), so a face that shrinks its glyphs (size-adjust) while keeping normal boxes is
  // caught by its ink.
  const fontRatio = (st) => {
    const key = st.fontStyle + '|' + st.fontWeight + '|' + st.fontFamily;
    if (_fontRatio.has(key)) return _fontRatio.get(key);
    let r = 1.15, ink = 1;
    try {
      if (!_mctx) _mctx = document.createElement('canvas').getContext('2d');
      _mctx.font = `${st.fontStyle} ${st.fontWeight} 100px ${st.fontFamily}`;
      const m = _mctx.measureText('Hxgy');
      const h = (m.fontBoundingBoxAscent || 0) + (m.fontBoundingBoxDescent || 0);
      const cap = _mctx.measureText('H').actualBoundingBoxAscent || 0;
      if (cap > 0) ink = Math.min(1, cap / 65);
      if (h > 50 && h < 400) r = h / 100;
      else if (cap > 0) r = Math.max(0.9, cap / 60);   // implausible boxes: trust the ink
    } catch (e) { /* keep the defaults */ }
    r = Math.max(0.9, Math.min(2.5, r));
    const out = [r, Math.max(0.05, ink)];
    if (_fontRatio.size < 200) _fontRatio.set(key, out);
    return out;
  };
  // The size text is actually PAINTED at; the smallest of:
  //  1. computed font-size x the 2D transform chain's scale x CSS zoom (a ceiling);
  //  2. painted glyph boxes: single-character rects are already projected through every
  //     transform (individual scale/rotate props, 3D/perspective, offset-path, SVG viewBox).
  //     Only letters/CJK, spread across the whole text (<= 256 scanned, budget-checked), using
  //     the box size ACROSS the line (height, or width when the line runs vertically), at the
  //     25th percentile, divided by the font's own ratio;
  //  3. the smallest rendered line box (across the line) / the font's ratio, when unrotated.
  const effectiveFontPx = (el, st, minLineH) => {
    try {
      // Each ancestor's own matrix: the individual rotate/scale properties, then transform
      // (CSS order translate -> rotate -> scale -> transform; translation doesn't change size).
      let m = new DOMMatrix();
      for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
        const ns = getComputedStyle(n);
        const own = new DOMMatrix();
        const rot = ns.rotate;
        if (rot && rot !== 'none') {
          const deg = parseFloat((rot.match(/-?[\d.]+deg/) || ['0'])[0]);
          if (deg) own.rotateSelf(0, 0, deg);
        }
        const sc = ns.scale;
        if (sc && sc !== 'none') {
          const parts = sc.trim().split(/\s+/).map(parseFloat);
          own.scaleSelf(parts[0] || 1, parts.length > 1 ? parts[1] : (parts[0] || 1));
        }
        const tf = ns.transform;
        const full = (tf && tf !== 'none') ? own.multiply(new DOMMatrix(tf)) : own;
        m = full.multiply(m);
      }
      const sx = Math.hypot(m.a, m.b), sy = Math.hypot(m.c, m.d);
      const zoom = (typeof el.currentCSSZoom === 'number' && el.currentCSSZoom > 0) ? el.currentCSSZoom : 1;
      const [ratioF, inkF] = fontRatio(st);
      let px = (parseFloat(st.fontSize) || 16) * Math.min(sx, sy) * zoom * inkF;
      const vertical = (st.writingMode || '').startsWith('vertical');
      const angle = Math.abs(Math.atan2(m.b, m.a)) % Math.PI;
      const sideways = (angle > Math.PI / 4 && angle < 3 * Math.PI / 4) !== vertical;
      const LETTER = /[A-Za-zÀ-ɏͰ-ϿЀ-ӿ֐-ۿऀ-ॿ぀-ヿ㐀-鿿가-힯]/;
      const idx = [], other = [];
      for (const n of el.childNodes) {
        if (n.nodeType !== 3) continue;
        const t = n.textContent;
        const step = Math.max(1, Math.floor(t.length / 256));
        for (let i = 0, scanned = 0; i < t.length && scanned < 256; i += step, scanned++) {
          if (LETTER.test(t[i])) idx.push([n, i]);
          else if (/[0-9$%#@&+]/.test(t[i])) other.push([n, i]);   // digits-only text too
        }
        if (overBudget()) break;
      }
      if (!idx.length) idx.push(...other);
      const pick = idx.length > 16 ? idx.filter((_, k) => k % Math.ceil(idx.length / 16) === 0) : idx;
      const sizes = [];
      for (const [n, i] of pick) {
        const rg = document.createRange(); rg.setStart(n, i); rg.setEnd(n, i + 1);
        const q = rg.getBoundingClientRect();
        if (q.width > 0 && q.height > 0) sizes.push(sideways ? q.width : q.height);
      }
      if (sizes.length) {
        sizes.sort((x, y) => x - y);
        px = Math.min(px, sizes[Math.floor(sizes.length / 4)] / ratioF * inkF);
      }
      if (minLineH > 0 && angle < 0.01) px = Math.min(px, minLineH / ratioF * inkF);
      return Math.round(px * 100) / 100;
    } catch (e) { return 0; }
  };
  // Nearest block container (for pooling fragments of one text block, on either axis).
  const _blockIds = new Map(); let _nextBlock = 1;
  const blockKey = (el) => {
    let n = el;
    const flowItem = (x) => {
      const p = x.parentElement;
      if (!p) return false;
      const d = getComputedStyle(p).display;
      return d.includes('flex') || d.includes('grid');   // blockified flex/grid item
    };
    while (n && n !== document.body &&
           (getComputedStyle(n).display.startsWith('inline') || flowItem(n))) n = n.parentElement;
    if (!_blockIds.has(n)) _blockIds.set(n, _nextBlock++);
    return _blockIds.get(n);
  };
  // WCAG 1.4.3 exempts text of INACTIVE user-interface components. Only a disabled control
  // (or text inside one) qualifies — aria-disabled on a page wrapper exempts nothing.
  const CONTROL = 'button,input,select,textarea,a[href],[role=button],[role=link],[role=tab],' +
                  '[role=menuitem],[role=option],[role=switch],[role=checkbox],[role=radio]';
  // Limited to a control's own LABEL: the control itself or an inline descendant, short text,
  // and a control-sized box — so wrapping an article in a disabled button/link exempts nothing.
  // Native disabled form controls only (aria-disabled is page-assertable on anything), and a
  // page-wide budget so the exemption can't be applied one line at a time to body copy.
  let exemptCount = 0, exemptChars = 0;
  const inactiveControl = (el) => {
    try {
      const c = el.closest('button,input,select,textarea,fieldset');
      if (!c) return false;
      const off = c.matches(':disabled') || !!c.closest('fieldset:disabled');
      if (!off) return false;
      if (el !== c && !getComputedStyle(el).display.startsWith('inline')) return false;
      if ((c.innerText || '').trim().length > 80) return false;
      const r = c.getBoundingClientRect();
      if (r.width > 600 || r.height > 200) return false;
      const n = (c.innerText || '').trim().length;
      if (exemptCount >= 6 || exemptChars + n > 300) return false;
      exemptCount++; exemptChars += n;
      return true;
    } catch (e) { return false; }
  };
  // Fraction of an element's painted text that survives the document bounds and EVERY
  // hard-clipping ancestor. Used so text that is off-screen or clipped away cannot satisfy a
  // quoted requirement ("the page shows 'Subscribe'") just by existing in the DOM.
  const visibleFrac = (el, tr) => {
    if (!tr) return 0;
    const de0 = document.documentElement;
    let l = Math.max(tr.left, -docX), t = Math.max(tr.top, -docY);
    let r = Math.min(tr.right, de0.scrollWidth - docX), b = Math.min(tr.bottom, de0.scrollHeight - docY);
    let node = el, depth = 0;
    while (node && node !== document.documentElement && depth < 30 && r > l && b > t) {
      const ns = getComputedStyle(node);
      const cx = hardClips(ns.overflowX) || hardClips(ns.overflow);
      const cy = hardClips(ns.overflowY) || hardClips(ns.overflow);
      if (cx || cy) {
        // getBoundingClientRect is in transformed (painted) space but clientWidth/Height are
        // layout px: scale them by the element's own transform so a scale() can't shrink or
        // grow the clip box. overflow:clip paints up to overflow-clip-margin past the box.
        const nr = node.getBoundingClientRect();
        const sx = node.offsetWidth ? nr.width / node.offsetWidth : 1;
        const sy = node.offsetHeight ? nr.height / node.offsetHeight : 1;
        const isClip = ns.overflowX === 'clip' || ns.overflowY === 'clip' || ns.overflow === 'clip';
        const m = isClip ? (parseFloat(ns.overflowClipMargin) || 0) : 0;
        const cl = nr.left + node.clientLeft * sx - m * sx, ct = nr.top + node.clientTop * sy - m * sy;
        const cw = node.clientWidth * sx + 2 * m * sx, ch = node.clientHeight * sy + 2 * m * sy;
        if (cx) { l = Math.max(l, cl); r = Math.min(r, cl + cw); }
        if (cy) { t = Math.max(t, ct); b = Math.min(b, ct + ch); }
      }
      node = node.parentElement; depth++;
    }
    const area = Math.max(1, (tr.right - tr.left) * (tr.bottom - tr.top));
    return (r > l && b > t) ? ((r - l) * (b - t)) / area : 0;
  };
  const clamped = (st) => st.webkitLineClamp && st.webkitLineClamp !== 'none';
  // Visible error copy. Deliberately narrow, high-signal patterns: a news story saying "talks
  // failed" must not trip it; "Error 403: Playback failed" or "[object Object]" must.
  const ERROR_RE = new RegExp([
    '\\berror\\s*(code\\s*)?[:#]?\\s*\\d{3,5}\\b',
    '\\b(404|500|502|503)\\s*[-:]?\\s*(not found|internal server error|bad gateway|service unavailable)\\b',
    '\\bsomething went wrong\\b', '\\buncaught\\s+\\w*error\\b',
    '\\btraceback \\(most recent call last\\)', '\\[object object\\]',
    '\\bplayback (error|failed)\\b', '\\bnot available in your (region|country|location)\\b',
    '\\b(video|stream|content) (failed to load|could not be loaded|is unavailable)\\b',
    '^(undefined|null|nan)$',
  ].join('|'), 'i');

  const domBoxes = [], contrast = [], broken = [], clipped = [], svgClipped = [];
  const errorTexts = [], texts = [], contrastEls = [];
  const all = document.querySelectorAll('body *');
  let count = 0;
  for (const el of all) {
    if (overBudget()) break;
    if (count >= MAX_ELEMENTS) { truncated = true; break; }
    count++;
    const st = getComputedStyle(el);
    if (!isVisible(el, st)) continue;
    const tag = el.tagName.toLowerCase();
    const txt = directText(el).slice(0, 120);

    if (domBoxes.length < 1500) {
      domBoxes.push({ tag, ...rectOf(el), text: txt, selector: selectorOf(el) });
    }

    // Broken images
    if (tag === 'img') {
      if (el.complete && el.naturalWidth === 0) {
        broken.push({ tag, ...rectOf(el), text: el.getAttribute('src') || '', selector: selectorOf(el) });
      }
    }

    // Truncated DOM text: content wider than its box under a HARD clip with no ellipsis
    // (an ellipsis is usually intentional; a mid-word hard cut usually isn't).
    if (txt && txt.length >= 2 && clipped.length < 200) {
      const ox = st.overflowX !== 'visible' ? st.overflowX : st.overflow;
      const hardClip = (ox === 'hidden' || ox === 'clip');
      const ellipsis = (st.textOverflow === 'ellipsis');
      const overW = el.scrollWidth - el.clientWidth;
      if (hardClip && !ellipsis && overW > 2) {
        clipped.push({ ...rectOf(el), tag, text: txt.slice(0, 60),
                       selector: selectorOf(el), kind: 'truncated', overflow: overW });
      } else if (!clamped(st) && !(el instanceof SVGElement)) {   // SVG text: own pass below
        // Text PARTIALLY cut by the nearest hard-clipping box (itself or an ancestor, any
        // axis) — e.g. a headline in a fixed-height overflow:hidden card. Fully-hidden text
        // (an off-screen carousel slide) is intentional and skipped; line-clamp is intentional.
        const tr = textRect(el);
        let node = el, depth = 0;
        while (tr && node && node !== document.body && depth < 8) {
          const ns = node === el ? st : getComputedStyle(node);
          if (clamped(ns)) break;
          if (hardClips(ns.overflowX) || hardClips(ns.overflowY) || hardClips(ns.overflow)) {
            const nr = node.getBoundingClientRect();
            const sx = node.offsetWidth ? nr.width / node.offsetWidth : 1;
            const sy = node.offsetHeight ? nr.height / node.offsetHeight : 1;
            const cl = nr.left + node.clientLeft * sx, ct = nr.top + node.clientTop * sy;
            const cr = cl + node.clientWidth * sx, cb = ct + node.clientHeight * sy;
            if (node.clientWidth < 4 || node.clientHeight < 4) break;   // sr-only style
            const visible = tr.right > cl && tr.left < cr && tr.bottom > ct && tr.top < cb;
            const over = Math.max(
              hardClips(ns.overflowY) || hardClips(ns.overflow) ? Math.max(ct - tr.top, tr.bottom - cb) : 0,
              hardClips(ns.overflowX) || hardClips(ns.overflow) ? Math.max(cl - tr.left, tr.right - cr) : 0);
            if (visible && over > 2 && !ellipsis) {
              clipped.push({ x: tr.left + docX, y: tr.top + docY, w: tr.right - tr.left,
                             h: tr.bottom - tr.top, tag, text: txt.slice(0, 60),
                             selector: selectorOf(el), kind: 'container_clipped', overflow: over });
            }
            break;
          }
          node = node.parentElement; depth++;
        }
      }
    }

    if (txt && errorTexts.length < 50 && ERROR_RE.test(txt)) {
      errorTexts.push({ tag, ...rectOf(el), text: txt.slice(0, 120), selector: selectorOf(el) });
    }
    if (txt && texts.length < 1500) { const r0 = textRect(el); if (r0) texts.push({ el, tr: r0 }); }

    // Contrast: only for elements with their own visible text. Grade the colour actually
    // PAINTED: -webkit-text-fill-color overrides `color`, and a translucent foreground is
    // composited over the backdrop (rgba(0,0,0,.08) on white is near-invisible, not 21:1).
    if (txt && txt.length >= 2) {
      // SVG text paints with `fill` (times fill-opacity), not `color`.
      const isSvg = el instanceof SVGElement;
      const fillRaw = isSvg ? st.fill : st.webkitTextFillColor;
      const svgPaintServer = isSvg && (!fillRaw || fillRaw === 'none' || fillRaw.startsWith('url('));
      const fg0 = parseColor(svgPaintServer ? st.color
                             : (fillRaw && fillRaw !== st.color ? fillRaw : st.color));
      if (!fg0) continue;
      const fg = isSvg && !svgPaintServer
        ? { ...fg0, a: (fg0.a === undefined ? 1 : fg0.a) *
                       Math.max(0, Math.min(1, parseFloat(st.fillOpacity || '1'))) }
        : fg0;
      // A text halo (opaque, blurred or offset text-shadow that contrasts with the fill) is a
      // WCAG-recognised way to stay legible over photos: graded by the halo, not the backdrop.
      let halo = false;
      const ts = st.textShadow;
      let ownBgImage = false;
      for (let n = el; n && n !== document.body; n = n.parentElement) {
        const ns = n === el ? st : getComputedStyle(n);
        if (n !== el && !ns.display.startsWith('inline')) break;
        if (ns.backgroundImage && ns.backgroundImage !== 'none') { ownBgImage = true; break; }
      }
      if (ts && ts !== 'none') {
        const m = ts.match(/(rgba?\([^)]*\))\s+(-?[\d.]+)px\s+(-?[\d.]+)px\s+([\d.]+)px/);
        if (m) {
          const sc = parseColor(m[1]);
          const ox = Math.abs(parseFloat(m[2])), oy = Math.abs(parseFloat(m[3]));
          const blur = parseFloat(m[4]);
          const em = parseFloat(st.fontSize) || 16;
          // A halo hugs the glyphs: small offset, modest blur. A shadow thrown far away (or a
          // tiny one) is not a halo. Python still requires it to be visibly painted.
          const hugs = ox <= 0.25 * em && oy <= 0.25 * em && blur <= 0.6 * em && ox + oy + blur >= 1;
          // A texture painted in the text's own line box would read as "halo": no exemption.
          if (sc && sc.a >= 0.5 && hugs && ratio(fg, sc) >= 4.5 && !ownBgImage) halo = true;
        }
      }
      // effective background: walk ancestors for first opaque background-color. Anything that
      // changes the painted result beyond plain colours (filter, blend, text stroke, clip-to-
      // text) makes computed-style contrast unreliable -> low confidence -> pixel-graded.
      let bg = null, conf = 'high', node = el, effects = false;
      if ((parseFloat(st.webkitTextStrokeWidth) || 0) > 0) { conf = 'low'; effects = true; }
      if (ts && ts !== 'none') { conf = 'low'; effects = true; }        // shadow repaints glyphs
      if (svgPaintServer || (isSvg && st.stroke && st.stroke !== 'none')) { conf = 'low'; effects = true; }
      // Pass 1: find the backdrop (first opaque background), noting what dims or repaints.
      let opacityProduct = 1, opacityBelow = 1, chainClipped = false, otherFx = false;
      const noteEffects = (ns) => {
        opacityProduct *= Math.max(0, Math.min(1, parseFloat(ns.opacity || '1')));
        if ((ns.filter && ns.filter !== 'none') ||
            (ns.backdropFilter && ns.backdropFilter !== 'none') ||
            (ns.mixBlendMode && ns.mixBlendMode !== 'normal') ||
            (ns.webkitBackgroundClip || ns.backgroundClip) === 'text') { conf = 'low'; effects = true; otherFx = true; }
        if ((ns.clipPath && ns.clipPath !== 'none') ||
            ((ns.webkitMaskImage || ns.maskImage || 'none') !== 'none') ||
            (ns.clip && ns.clip !== 'auto')) chainClipped = true;
      };
      while (node && node !== document.documentElement) {
        const ns = node === el ? st : getComputedStyle(node);
        noteEffects(ns);
        const nodeOp = Math.max(0, Math.min(1, parseFloat(ns.opacity || '1')));
        if (ns.backgroundImage && ns.backgroundImage !== 'none') conf = 'low';
        const bc = parseColor(ns.backgroundColor);
        if (bc && bc.a >= 0.95) { bg = bc; node = node.parentElement; break; }
        opacityBelow *= nodeOp;   // dims the text but not the backdrop found further up
        if (bc && bc.a > 0) conf = 'low';
        node = node.parentElement;
      }
      // Pass 2: an effect or opacity ABOVE the backdrop still changes what is painted.
      while (node && node !== document.documentElement) { noteEffects(getComputedStyle(node)); node = node.parentElement; }
      // Opacity anywhere on the chain: computed colours overstate contrast -> pixel-graded.
      // When opacity is the ONLY effect, fold it into the text alpha so the computed ratio is
      // the visible one (black at opacity .4 is #999: 2.85:1, an ERROR like plain #999).
      // Fold only opacity that sits BELOW the backdrop (it dims text, not backdrop). Opacity on
      // or above the backdrop dims both against something unknown: pixels decide.
      const opacityOnly = opacityProduct < 0.95 && opacityProduct / Math.max(1e-6, opacityBelow) >= 0.95 &&
                          !otherFx && !(ts && ts !== 'none') &&
                          !((parseFloat(st.webkitTextStrokeWidth) || 0) > 0) && !svgPaintServer;
      if (opacityProduct < 0.95) { conf = 'low'; effects = !opacityOnly; }
      if (!bg) { bg = { r: 255, g: 255, b: 255, a: 1 }; conf = 'low'; }
      const fa = Math.max(0, Math.min(1, (fg.a === undefined ? 1 : fg.a) *
                                         (opacityOnly ? opacityBelow : 1)));
      const painted = { r: fg.r * fa + bg.r * (1 - fa), g: fg.g * fa + bg.g * (1 - fa),
                        b: fg.b * fa + bg.b * (1 - fa) };
      const fpx = parseFloat(st.fontSize) || 16;
      const bold = (parseInt(st.fontWeight) || 400) >= 700;
      const large = fpx >= 24 || (fpx >= 18.66 && bold);
      const cr = ratio(painted, bg);
      const aa = large ? cr >= 3 : cr >= 4.5;
      const aaa = large ? cr >= 4.5 : cr >= 7;
      contrast.push({
        ...rectOf(el), ratio: Math.round(cr * 100) / 100,
        fg: fillRaw && fillRaw !== st.color ? fillRaw : st.color,
        bg: 'rgb(' + bg.r + ',' + bg.g + ',' + bg.b + ')',
        fontPx: fpx, large, aa, aaa, confidence: conf, effects,
        halo: halo && !otherFx && opacityProduct >= 0.95 && fa >= 0.95,
        // The only effect is a text-shadow: the fill colour is still exact, so Python grades
        // the fill against the real backdrop (a texture can't pose as ink).
        shadowOnly: !!(ts && ts !== 'none') && !otherFx && opacityProduct >= 0.95 &&
                    !((parseFloat(st.webkitTextStrokeWidth) || 0) > 0) && !svgPaintServer,
        text: txt.slice(0, 120), selector: selectorOf(el),
        visibleFrac: Math.round(visibleFrac(el, textRect(el)) * 100) / 100,
        glyph: (() => { const g = textRect(el); return g ? { x: g.left + docX, y: g.top + docY,
                 w: g.right - g.left, h: g.bottom - g.top } : null; })(),
        glyphs: textRects(el),
        lineWords: [],
        // Smallest rendered line height in CSS px (transforms and zoom included): text too small
        // to read can't hide behind a normal computed font-size.
        minLineH: (() => { const r = textRects(el); return r.length ? Math.min(...r.map(q => q.h)) : 0; })(),
        effFontPx: (() => { const r = textRects(el);
                            const v = (st.writingMode || '').startsWith('vertical');
                            const mh = r.length ? Math.min(...r.map(q => v ? q.w : q.h)) : 0;
                            return effectiveFontPx(el, st, mh); })(),
        // Ruby annotation exempt only when it annotates a real base and is annotation-sized.
        inRuby: (() => {
          const rt = el.closest('rt,rp'); if (!rt) return false;
          const ruby = rt.closest('ruby'); if (!ruby) return false;
          let base = '';
          for (const n of ruby.childNodes) if (n.nodeType === 3 || (n.nodeType === 1 && !n.matches('rt,rp'))) base += n.textContent;
          base = base.replace(/[\s\u200b]/g, '');
          const ann = (rt.textContent || '').replace(/\s/g, '');
          return base.length > 0 && ann.length <= 3 * base.length + 2;
        })(),
        // A real super/subscript: actually raised/lowered (not a <sup> reset to baseline),
        // inside a block whose own text is clearly larger.
        supSub: (st.verticalAlign === 'super' || st.verticalAlign === 'sub' ||
                 (/^-?\d/.test(st.verticalAlign) && parseFloat(st.verticalAlign) !== 0)) &&
                (() => { const p = el.parentElement; if (!p) return false;
                         const ps = parseFloat(getComputedStyle(p).fontSize) || 0;
                         return ps >= (parseFloat(st.fontSize) || 0) * 1.2 && ps >= 8.5; })(),
        blockKey: blockKey(el),
        fgRgba: { r: fg.r, g: fg.g, b: fg.b, a: fa },
        inactive: inactiveControl(el)
      });
      contrastEls.push(el);
      // Words of each sampled line (by each word's own rect), for OCR-split checks.
      {
        const gl = contrast[contrast.length - 1].glyphs;
        const per = gl.map(() => []);
        let nw = 0;
        for (const n of el.childNodes) {
          if (n.nodeType !== 3 || nw > 300) continue;
          const t = n.textContent; const re = /[A-Za-z]{4,}/g; let m;
          while ((m = re.exec(t)) && nw <= 300) {
            nw++;
            const rg = document.createRange(); rg.setStart(n, m.index); rg.setEnd(n, m.index + m[0].length);
            const q = rg.getBoundingClientRect(); const qy = q.top + docY + q.height / 2;
            const qx = q.left + docX + q.width / 2;
            gl.forEach((g, k) => { if (qy >= g.y && qy <= g.y + g.h && qx >= g.x - 2 && qx <= g.x + g.w + 2) per[k].push(m[0].toLowerCase()); });
          }
        }
        contrast[contrast.length - 1].lineWords = per;
      }
    }
  }

  // SVG <text> clipped by its viewport. The outermost <svg> clips to its bounds by default,
  // so a label whose rendered rect extends past the viewport element is cut off — the exact
  // "truncated mid-word" / "leading glyph at negative x" defect. getBoundingClientRect reports
  // full geometry regardless of clipping, so the overflow is measurable from the snapshot.
  const svgTexts = document.querySelectorAll('svg text');
  let sc = 0;
  for (const t of svgTexts) {
    if (overBudget()) break;
    // Own list + cap: warning-level DOM clips must not crowd out these ERROR-level findings.
    if (sc >= 2000 || svgClipped.length >= 200) { truncated = true; break; }
    sc++;
    const vp = t.viewportElement;        // nearest ancestor establishing the SVG viewport
    if (!vp) continue;
    const vst = getComputedStyle(vp);
    // overflow:visible means the text is drawn (not cut) — a different defect, skip.
    if (vst.overflow === 'visible' || vst.overflowX === 'visible') continue;
    let tr, vr;
    try { tr = t.getBoundingClientRect(); vr = vp.getBoundingClientRect(); } catch (e) { continue; }
    if (tr.width < 1 && tr.height < 1) continue;
    const label = (t.textContent || '').trim();
    if (!label) continue;
    const over = Math.max(vr.left - tr.left, tr.right - vr.right,
                          vr.top - tr.top, tr.bottom - vr.bottom);
    if (over > 1.0) {
      svgClipped.push({ x: tr.left + docX, y: tr.top + docY, w: tr.width, h: tr.height,
                        tag: 'text', text: label.slice(0, 60), selector: selectorOf(t),
                        kind: 'svg_clipped', overflow: over });
    }
  }

  // Text covered by a positioned element (absolute/fixed): intersect each occluder with the
  // painted text rect, then confirm with a hit-test that the occluder really is on top.
  const overlaps = [];
  const vw = window.innerWidth, vh = window.innerHeight;
  // Bounded work: at most 150 occluders and 600 hit-tests in total. A pointer-events:none
  // overlay can never be the hit-test target, so it is skipped up front (it would otherwise
  // burn a hit-test on every text it intersects without ever counting toward the cap).
  let occ = 0, hits = 0;
  for (const o of all) {
    if (occ > 150 || overlaps.length >= 50 || hits >= 600 || overBudget()) break;
    const os = getComputedStyle(o);
    if (os.position !== 'absolute' && os.position !== 'fixed') continue;
    if (os.pointerEvents === 'none') continue;
    if (!isVisible(o, os)) continue;
    occ++;
    const orr = o.getBoundingClientRect();
    for (const { el: t, tr } of texts) {
      if (overlaps.length >= 50 || hits >= 600) break;
      if (t === o || o.contains(t)) continue;
      const ix = Math.max(orr.left, tr.left), iy = Math.max(orr.top, tr.top);
      const ix2 = Math.min(orr.right, tr.right), iy2 = Math.min(orr.bottom, tr.bottom);
      if (ix2 - ix < 2 || iy2 - iy < 2) continue;
      const inter = (ix2 - ix) * (iy2 - iy);
      const tarea = Math.max(1, (tr.right - tr.left) * (tr.bottom - tr.top));
      if (inter < 50 || inter / tarea < 0.05) continue;
      const cx = (ix + ix2) / 2, cy = (iy + iy2) / 2;
      if (cx < 0 || cy < 0 || cx >= vw || cy >= vh) continue;
      hits++;
      const hit = document.elementFromPoint(cx, cy);
      if (!hit || !(hit === o || o.contains(hit)) || t.contains(hit)) continue;
      overlaps.push({ tag: t.tagName.toLowerCase(), x: ix + docX, y: iy + docY, w: ix2 - ix,
                      h: iy2 - iy, text: directText(t).slice(0, 60), selector: selectorOf(o) });
    }
  }

  // Text under a fixed/sticky overlay (cookie banner, sticky bar, modal): the overlay is what
  // the capture shows there. Mark those samples so pixel grading leaves them to the overlap
  // check instead of calling the banner's pixels "unreadable text". The overlay's OWN text
  // is not under it and is graded normally.
  // Background colour an element paints at (px, py), or null: its own opaque-enough background
  // inside the box its background is clipped to (padding box excludes borders; a border only
  // counts when the border itself is painted).
  const paintsAt = (n, px, py) => {
    const ns = getComputedStyle(n);
    const bc = parseColor(ns.backgroundColor);
    const r = n.getBoundingClientRect();
    const bl = parseFloat(ns.borderLeftWidth) || 0, br = parseFloat(ns.borderRightWidth) || 0;
    const bt = parseFloat(ns.borderTopWidth) || 0, bb = parseFloat(ns.borderBottomWidth) || 0;
    const inPadding = px >= r.left + bl && px <= r.right - br && py >= r.top + bt && py <= r.bottom - bb;
    if (bc && bc.a >= 0.5 && (inPadding || ns.backgroundClip === 'border-box')) {
      if (ns.backgroundClip === 'content-box' || ns.backgroundClip === 'text') return null;
      return [bc.r, bc.g, bc.b, bc.a];
    }
    if (!inPadding) {
      const bcol = parseColor(ns.borderTopColor);
      if (bcol && bcol.a >= 0.5 && (bt || bb || bl || br)) return [bcol.r, bcol.g, bcol.b, bcol.a];
    }
    return null;
  };
  const overlayEls = [];
  for (const o of all) {
    if (overlayEls.length >= 50) break;
    const os = getComputedStyle(o);
    if (os.position !== 'fixed' && os.position !== 'sticky') continue;
    if (!isVisible(o, os)) continue;
    // A real overlay PAINTS: a solid background, not clipped, not faded along its chain.
    const ob = parseColor(os.backgroundColor);
    if (!(ob && ob.a >= 0.5)) continue;
    if (os.clipPath && os.clipPath !== 'none') continue;
    // It must PAINT its background over its whole box: no blend mode, no filter (on it or an
    // ancestor), background painted to the border/padding box, not faded.
    if (os.backgroundClip && os.backgroundClip !== 'border-box' && os.backgroundClip !== 'padding-box') continue;
    let op = 1, fx = false;
    for (let n = o; n && n !== document.documentElement; n = n.parentElement) {
      const ns = getComputedStyle(n);
      op *= parseFloat(ns.opacity || '1');
      if ((ns.mixBlendMode && ns.mixBlendMode !== 'normal') || (ns.filter && ns.filter !== 'none')) fx = true;
    }
    if (op < 0.5 || fx) continue;
    overlayEls.push(o);
  }
  // Per sample: which sampled LINES an overlay actually sits on top of. Confirmed by a
  // hit-test at the line centre (stacking order, clipping and z-index all respected), so an
  // element behind the content or off to the side can't switch grading off.
  for (let i = 0; i < contrast.length && i < contrastEls.length; i++) {
    const el = contrastEls[i];
    const own = overlayEls.find(o => o.contains(el));
    contrast[i].inOverlay = !!own;
    if (own || !overlayEls.length) continue;
    const covered = [], coverColors = [];
    (contrast[i].glyphs || []).forEach((g, k) => {
      // Covered = an overlay PAINTS over most of the line: a 3x3 grid of hit-tests, at least 6
      // of 9 landing on painted overlay area. A hit counts only on the overlay itself (inside
      // its painted background box) or on a descendant that paints its own opaque background:
      // a transparent child or transparent border is hit-testable but paints nothing.
      let onTop = 0, color = null;
      for (const fx of [0.15, 0.5, 0.85]) for (const fy of [0.2, 0.5, 0.8]) {
        const px = g.x - docX + g.w * fx, py = g.y - docY + g.h * fy;
        if (px < 0 || py < 0 || px >= window.innerWidth || py >= window.innerHeight) continue;
        const hit = document.elementFromPoint(px, py);
        if (!hit) continue;
        const o = overlayEls.find(ov => ov === hit || ov.contains(hit));
        if (!o) continue;
        const pc = paintsAt(hit === o ? o : hit, px, py);
        if (pc) { onTop++; color = pc; }
      }
      if (onTop >= 6) { covered.push(k); coverColors.push(color); }
    });
    if (covered.length) {
      contrast[i].coveredLines = covered;
      contrast[i].coverColors = coverColors;   // [r, g, b, a] of the paint actually hit
    }
  }

  // Page vocabulary for spelling severity: every visible text node once (no per-element caps
  // or ancestor duplication), fragments of one block joined with no separator so words split
  // across inline elements rejoin, all Unicode format characters stripped; plus visible,
  // non-secret form-control values. Bounded in size and by the time budget.
  const INVIS = /[\p{Cf}\u034F\u180E\uFE00-\uFE0F]/gu;
  const vparts = [];
  let vlen = 0, lastBlock = null;
  const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = tw.nextNode(); n && vlen < 300000; n = tw.nextNode()) {
    if (overBudget()) break;
    const p = n.parentElement;
    if (!p || p.closest('script,style,noscript,template')) continue;
    const t = (n.textContent || '').slice(0, 20000).replace(INVIS, '');
    if (!t) continue;
    const bk = blockKey(p);
    vparts.push(bk === lastBlock ? t : ' ' + t);
    lastBlock = bk; vlen += t.length;
  }
  for (const f of document.querySelectorAll('input,textarea,button')) {
    if (vlen >= 310000 || overBudget()) break;
    const ty = (f.type || '').toLowerCase();
    if (ty === 'password' || ty === 'hidden') continue;
    const v = ((f.value || f.textContent || '') + '').slice(0, 2000).replace(INVIS, '');
    vparts.push(' ' + v); vlen += v.length;
  }
  const vocabText = vparts.join('').slice(0, 320000);

  // Form fields: their value / placeholder text is not an own text node, so it never becomes a
  // contrast sample. Size-check it here.
  const tinyFields = [];
  for (const f of document.querySelectorAll('input,textarea,select')) {
    if (tinyFields.length >= 20 || overBudget()) break;
    const fs = getComputedStyle(f);
    if (!isVisible(f, fs)) continue;
    const listbox = f.tagName === 'SELECT' && (f.multiple || f.size > 1);
    const t = (listbox ? Array.from(f.options).map(o => o.text).join(' ')
               : (f.value || f.placeholder || (f.selectedOptions && f.selectedOptions[0] && f.selectedOptions[0].text) || '')).trim();
    if (t.replace(/\s/g, '').length < 3) continue;
    const r = f.getBoundingClientRect();
    tinyFields.push({ x: r.left + docX, y: r.top + docY, w: r.width, h: r.height,
                      text: t.slice(0, 80), effFontPx: effectiveFontPx(f, fs, 0), selector: selectorOf(f) });
  }

  // Document overflow signal (horizontal scrollbar = layout overflow)
  const de = document.documentElement;
  const overflowX = de.scrollWidth - de.clientWidth;
  return {
    domBoxes, contrast, broken, clipped: svgClipped.concat(clipped), overlaps, errorTexts, tinyFields,
    vocabText,
    truncated, elementsChecked: count,
    docWidth: de.scrollWidth, docHeight: de.scrollHeight,
    clientWidth: de.clientWidth, overflowX
  };
}
"""
