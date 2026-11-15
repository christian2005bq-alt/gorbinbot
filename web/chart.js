// Hand-drawn canvas charts (no library), devicePixelRatio aware. Styled after the fomo/Grok Bot iPhone app.
(function () {
  'use strict';
  const G = '#34C759', R = '#FF3B30', B = '#0A84FF';
  const FONT = '-apple-system,BlinkMacSystemFont,"SF Pro Text",Roboto,"Helvetica Neue",Arial,sans-serif';
  const reduced = () => window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  function setup(cv) {
    const dpr = window.devicePixelRatio || 1, r = cv.getBoundingClientRect();
    const w = Math.max(1, r.width), h = Math.max(1, r.height);
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    const c = cv.getContext('2d'); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, w, h);
    return [c, w, h];
  }
  const rgba = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; };
  function rr(c, x, y, w, h, r) { c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); }

  // Floating marker pill: line 1 = ticker (white, bold), line 2 = "<verb> <amount>" (verb tinted, amount white).
  function pillSize(c, m) {
    c.font = `600 12px ${FONT}`; const wv = c.measureText((m.verb || '') + ' ').width; c.font = `700 13px ${FONT}`; const wa = c.measureText(m.amount || '').width;
    c.font = `700 12px ${FONT}`; const w1 = c.measureText(m.name || '').width;
    return [Math.max(w1, wv + wa) + 20, m.name ? 38 : 24, wv];
  }
  function pill(c, px, py, m, color) {
    const [pw, ph, wv] = pillSize(c, m);
    rr(c, px, py, pw, ph, 9); c.fillStyle = 'rgba(0,0,0,0.82)'; c.fill();
    rr(c, px, py, pw, ph, 9); c.fillStyle = rgba(color, 0.22); c.fill(); c.lineWidth = 1.2; c.strokeStyle = rgba(color, 0.9); c.stroke();
    c.textBaseline = 'middle'; let ly = py + ph / 2;
    if (m.name) { c.font = `700 12px ${FONT}`; c.fillStyle = '#fff'; c.fillText(m.name, px + 10, py + 12); ly = py + 27; }
    c.font = `600 12px ${FONT}`; c.fillStyle = color === B ? '#8fc3ff' : color; c.fillText(m.verb || '', px + 10, ly);
    c.font = `700 13px ${FONT}`; c.fillStyle = '#fff'; c.fillText(m.amount || '', px + 10 + wv, ly);
  }
  // Place pills without overlap: try above, higher, below; skip the pill (keep the dot) if nothing fits.
  function placePills(c, items, w, h, minY = 2, maxY = h) {
    const rects = [];
    items.forEach(it => {
      const [pw, ph] = pillSize(c, it.m);
      const px = Math.min(Math.max(4, it.x - pw / 2), w - pw - 4);
      const cands = it.prefer === 'below' ? [it.y + 16, it.y - ph - 18, it.y + 62] : [it.y - ph - 26, it.y - ph - 72, it.y + 18, it.y - ph - 118];
      const hit = (y) => rects.some(r => px < r[0] + r[2] + 4 && px + pw + 4 > r[0] && y < r[1] + r[3] + 4 && y + ph + 4 > r[1]);
      const py = cands.find(y => y >= minY && y + ph <= maxY - 2 && !hit(y));
      c.beginPath(); c.arc(it.x, it.y, 9, 0, 7); c.fillStyle = rgba(it.col, 0.2); c.fill();
      if (it.letter) { c.beginPath(); c.arc(it.x, it.y, 7, 0, 7); c.fillStyle = it.col; c.fill(); c.fillStyle = '#fff'; c.font = `800 9px ${FONT}`; c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText(it.letter, it.x, it.y + .5); c.textAlign = 'left'; }
      else { c.beginPath(); c.arc(it.x, it.y, 3.5, 0, 7); c.fillStyle = it.col; c.fill(); }
      if (py == null) return;
      rects.push([px, py, pw, ph]);
      const ey = py > it.y ? py : py + ph;
      c.setLineDash([2, 3]); c.strokeStyle = rgba(it.col, 0.6); c.lineWidth = 1; c.beginPath(); c.moveTo(it.x, ey); c.lineTo(it.x, it.y + (py > it.y ? 9 : -9)); c.stroke(); c.setLineDash([]);
      pill(c, px, py, it.m, it.col);
    });
  }

  // Home balance line: green line + green->black gradient, drawn left-to-right, marker pills above the line.
  function line(cv, data, opts = {}) {
    const pts = (data.points || []).slice();
    const st = cv._st || (cv._st = {});
    const draw = k => {
      const [c, w, h] = setup(cv);
      const padT = 58, padB = 14;
      const flat = pts.length < 2;
      let t0, t1, lo, hi;
      if (flat) { t0 = 0; t1 = 1; lo = 0; hi = 2; }
      else {
        t0 = pts[0][0]; t1 = pts[pts.length - 1][0]; if (t1 === t0) t1 = t0 + 60;
        lo = Math.min(...pts.map(p => p[1])); hi = Math.max(...pts.map(p => p[1]));
        if (hi - lo < 1e-9) { hi += 1; lo -= 1; } else { const pd = (hi - lo) * 0.1; lo -= pd; hi += pd; }
      }
      const X = t => (t - t0) / (t1 - t0) * (w - 14), Y = v => padT + (1 - (v - lo) / (hi - lo)) * (h - padT - padB);
      const P = flat ? [[0, 1], [1, 1]] : pts;
      const xEnd = (w - 14) * k;
      // path
      c.save(); c.beginPath(); c.rect(0, 0, xEnd + 1, h); c.clip();
      c.beginPath(); P.forEach((p, i) => { const x = X(p[0]), y = Y(p[1]); i ? c.lineTo(x, y) : c.moveTo(x, y); });
      const lastX = X(P[P.length - 1][0]);
      c.lineTo(lastX, h); c.lineTo(X(P[0][0]), h); c.closePath();
      const g = c.createLinearGradient(0, padT, 0, h); g.addColorStop(0, flat ? 'rgba(52,199,89,0.10)' : 'rgba(52,199,89,0.32)'); g.addColorStop(1, 'rgba(52,199,89,0)');
      c.fillStyle = g; c.fill();
      c.beginPath(); P.forEach((p, i) => { const x = X(p[0]), y = Y(p[1]); i ? c.lineTo(x, y) : c.moveTo(x, y); });
      c.strokeStyle = G; c.lineWidth = 2.2; c.lineJoin = 'round'; c.shadowColor = 'rgba(52,199,89,0.6)'; c.shadowBlur = 8; c.stroke(); c.shadowBlur = 0;
      c.restore();
      // live dot at the head
      if (k >= 1) {
        const lp = P[P.length - 1], x = X(lp[0]), y = Y(lp[1]);
        const pulse = (Math.sin(performance.now() / 380) + 1) / 2;
        c.beginPath(); c.arc(x, y, 6 + pulse * 6, 0, 7); c.fillStyle = `rgba(52,199,89,${0.25 - pulse * 0.2})`; c.fill();
        c.beginPath(); c.arc(x, y, 4.5, 0, 7); c.fillStyle = G; c.fill();
      }
      // markers (newest first so the newest gets the best spot)
      if (!flat && k >= 1) {
        const items = (data.marks || []).filter(m => m.ts >= t0 - 1).slice(-4).reverse().map(m => {
          let i = pts.findIndex(p => p[0] >= m.ts); if (i < 0) i = pts.length - 1;
          return {m, x: X(Math.min(Math.max(m.ts, t0), t1)), y: Y(pts[i][1]), col: m.kind === 'bought' ? B : (m.kind === 'stopped' || m.loss) ? R : G};
        });
        placePills(c, items, w, h);
      }
    };
    cancelAnimationFrame(st.raf);
    const animate = opts.animate && !reduced();
    const t0 = performance.now(), dur = 900;
    const loop = now => {
      if (!cv.isConnected) return;
      const k = animate ? Math.min(1, (now - t0) / dur) : 1;
      draw(1 - Math.pow(1 - k, 3));
      if (!reduced()) st.raf = requestAnimationFrame(loop);
    };
    loop(performance.now());
  }

  // Coin chart: candles + volume, blue dashed entry line, green dashed last price with a price tag, marker pills.
  function candles(cv, cs, o = {}) {
    const [c, w, h] = setup(cv);
    if (!cs || cs.length < 2) {
      c.strokeStyle = 'rgba(52,199,89,0.5)'; c.lineWidth = 2; c.beginPath(); c.moveTo(0, h * 0.55); c.lineTo(w, h * 0.55); c.stroke(); return false;
    }
    const data = cs.slice(-60);
    const volH = 46, padT = 46, padR = 64, chartH = h - volH - 10 - padT;
    let lo = Math.min(...data.map(d => d.l)), hi = Math.max(...data.map(d => d.h));
    [o.entry && o.entry.price, o.exit && o.exit.price].forEach(p => { if (p) { lo = Math.min(lo, p); hi = Math.max(hi, p); } });
    if (hi - lo < 1e-15) { hi *= 1.01; lo *= 0.99; }
    const pd = (hi - lo) * 0.06; lo -= pd; hi += pd;
    const cw = (w - padR) / data.length, Y = v => padT + (1 - (v - lo) / (hi - lo)) * chartH;
    const vmax = Math.max(1e-9, ...data.map(d => d.v || 0));
    const tX = ts => { let i = data.findIndex(d => d.t + 60 > ts); if (i < 0) i = data.length - 1; return [i * cw + cw / 2, i]; };
    // grid
    c.strokeStyle = 'rgba(255,255,255,0.05)'; c.lineWidth = 1;
    for (let i = 0; i <= 3; i++) { const y = padT + chartH * i / 3; c.beginPath(); c.moveTo(0, y); c.lineTo(w - padR, y); c.stroke(); }
    data.forEach((d, i) => {
      const x = i * cw + cw / 2, up = d.c >= d.o, col = up ? G : R;
      c.strokeStyle = col; c.lineWidth = 1; c.beginPath(); c.moveTo(x, Y(d.h)); c.lineTo(x, Y(d.l)); c.stroke();
      const y1 = Y(Math.max(d.o, d.c)), y2 = Y(Math.min(d.o, d.c));
      c.fillStyle = col; c.fillRect(x - Math.max(1, cw * 0.32), y1, Math.max(2, cw * 0.64), Math.max(1.5, y2 - y1));
      const vh = (d.v || 0) / vmax * volH; c.fillStyle = rgba(col, 0.45); c.fillRect(x - Math.max(1, cw * 0.32), h - vh, Math.max(2, cw * 0.64), vh);
    });
    const hline = (p, col) => { c.setLineDash([3, 4]); c.strokeStyle = rgba(col, 0.8); c.lineWidth = 1; c.beginPath(); c.moveTo(0, Y(p)); c.lineTo(w - padR + 4, Y(p)); c.stroke(); c.setLineDash([]); };
    const last = data[data.length - 1].c;
    if (o.entry && o.entry.price) hline(o.entry.price, B);
    hline(last, G);
    c.font = `700 11px ${FONT}`; const lab = o.lastLabel || '';
    if (lab) { const tw = c.measureText(lab).width + 12; rr(c, w - padR + 6, Y(last) - 10, Math.min(tw, padR - 8), 20, 6); c.fillStyle = G; c.fill(); c.fillStyle = '#000'; c.textBaseline = 'middle'; c.fillText(lab, w - padR + 12, Y(last)); }
    const items = [];
    const at = (m, col, letter, prefer) => { const [x, i] = tX(m.ts); items.push({m, x, y: Y(m.price || data[i].c), col, letter, prefer}); };
    if (o.exit) at(o.exit, o.exit.loss ? R : G, 'S', 'above');
    if (o.entry) at(o.entry, B, 'B', 'below');
    placePills(c, items, w - padR, h, 2, h - volH - 6);
    return true;
  }

  // Analyst ring: track + arc, color by pass/fail.
  function ring(cv, score, min, passed) {
    const [c, w, h] = setup(cv); const r = Math.min(w, h) / 2 - 5, cx = w / 2, cy = h / 2;
    c.lineWidth = 6; c.lineCap = 'round';
    c.strokeStyle = '#2C2C2E'; c.beginPath(); c.arc(cx, cy, r, 0, Math.PI * 2); c.stroke();
    if (score == null) { c.fillStyle = '#FFD60A'; c.beginPath(); c.arc(cx, cy - r, 3.5, 0, 7); c.fill(); return; }
    const col = passed === false || score < min ? R : G;
    c.strokeStyle = col; c.beginPath(); c.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.min(1, Math.max(0.02, score / 100))); c.stroke();
  }

  window.Charts = {line, candles, ring};
})();
