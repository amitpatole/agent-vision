"""In-page JavaScript that extracts DOM geometry, computed-style WCAG contrast, and
broken images. All rectangles are returned in DOCUMENT-space CSS pixels
(getBoundingClientRect + scroll offset); the Python side multiplies by device_scale to
reach image pixels.
"""

EXTRACT_JS = r"""
() => {
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
  const parseColor = (c) => {
    const m = (c || '').match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map(s => parseFloat(s.trim()));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
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

  const domBoxes = [], contrast = [], broken = [], clipped = [];
  const all = document.querySelectorAll('body *');
  let count = 0;
  for (const el of all) {
    if (count > 4000) break; count++;
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
      }
    }

    // Contrast: only for elements with their own visible text
    if (txt && txt.length >= 2) {
      const fg = parseColor(st.color);
      if (!fg) continue;
      // effective background: walk ancestors for first opaque background-color
      let bg = null, conf = 'high', node = el;
      while (node && node !== document.documentElement) {
        const ns = getComputedStyle(node);
        if (ns.backgroundImage && ns.backgroundImage !== 'none') conf = 'low';
        if (parseFloat(ns.opacity || '1') < 1) conf = 'low';
        const bc = parseColor(ns.backgroundColor);
        if (bc && bc.a >= 0.95) { bg = bc; break; }
        if (bc && bc.a > 0) conf = 'low';
        node = node.parentElement;
      }
      if (!bg) { bg = { r: 255, g: 255, b: 255, a: 1 }; conf = 'low'; }
      const fpx = parseFloat(st.fontSize) || 16;
      const bold = (parseInt(st.fontWeight) || 400) >= 700;
      const large = fpx >= 24 || (fpx >= 18.66 && bold);
      const cr = ratio(fg, bg);
      const aa = large ? cr >= 3 : cr >= 4.5;
      const aaa = large ? cr >= 4.5 : cr >= 7;
      contrast.push({
        ...rectOf(el), ratio: Math.round(cr * 100) / 100,
        fg: st.color, bg: 'rgb(' + bg.r + ',' + bg.g + ',' + bg.b + ')',
        fontPx: fpx, large, aa, aaa, confidence: conf,
        text: txt.slice(0, 60), selector: selectorOf(el)
      });
    }
  }

  // SVG <text> clipped by its viewport. The outermost <svg> clips to its bounds by default,
  // so a label whose rendered rect extends past the viewport element is cut off — the exact
  // "truncated mid-word" / "leading glyph at negative x" defect. getBoundingClientRect reports
  // full geometry regardless of clipping, so the overflow is measurable from the snapshot.
  const svgTexts = document.querySelectorAll('svg text');
  let sc = 0;
  for (const t of svgTexts) {
    if (sc > 500 || clipped.length >= 200) break; sc++;
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
      clipped.push({ x: tr.left + docX, y: tr.top + docY, w: tr.width, h: tr.height,
                     tag: 'text', text: label.slice(0, 60), selector: selectorOf(t),
                     kind: 'svg_clipped', overflow: over });
    }
  }

  // Document overflow signal (horizontal scrollbar = layout overflow)
  const de = document.documentElement;
  const overflowX = de.scrollWidth - de.clientWidth;
  return {
    domBoxes, contrast, broken, clipped,
    docWidth: de.scrollWidth, docHeight: de.scrollHeight,
    clientWidth: de.clientWidth, overflowX
  };
}
"""
