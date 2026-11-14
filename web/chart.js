// Hand-drawn canvas charts. No chart library. devicePixelRatio aware.
(function () {
  function setup(cv) {
    const dpr = window.devicePixelRatio || 1, r = cv.getBoundingClientRect();
    const w = Math.max(1, r.width), h = Math.max(1, r.height);
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    const c = cv.getContext('2d'); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, w, h);
    return [c, w, h];
  }
  const reduced = () => window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Home line chart: green line + gradient fill, dashed start line, marks that never overlap.
  function line(cv, data, opts) {
    const st = cv._st || (cv._st = {n: 0});
    const pts = data.points || [];
    const draw = (slide, markAlpha) => {
      const [c, w, h] = setup(cv);
      const padT = 64, padB = 10;
      const start = data.start_value;
      if (!pts.length) {
        const y = h / 2; c.setLineDash([4, 5]); c.strokeStyle = 'rgba(235,235,245,0.3)'; c.lineWidth = 1;
        c.beginPath(); c.moveTo(0, y); c.lineTo(w, y); c.stroke(); c.setLineDash([]); return;
      }
      let t0 = pts[0][0], t1 = pts[pts.length - 1][0]; if (t1 === t0) t1 = t0 + 60;
      let lo = Math.min(start ?? Infinity, ...pts.map(p => p[1])), hi = Math.max(start ?? -Infinity, ...pts.map(p => p[1]));
      if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
      const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
      const X = t => (t - t0) / (t1 - t0) * w, Y = v => padT + (1 - (v - lo) / (hi - lo)) * (h - padT - padB);
      // slide in the newest point
      let n = pts.length; let last = pts[n - 1];
      if (slide < 1 && n > 1) { const p = pts[n - 2]; last = [p[0] + (last[0] - p[0]) * slide, p[1] + (last[1] - p[1]) * slide]; }
      const P = pts.slice(0, n - 1).concat([last]);
      if (start != null) { c.setLineDash([4, 5]); c.strokeStyle = 'rgba(235,235,245,0.3)'; c.lineWidth = 1; c.beginPath(); c.moveTo(0, Y(start)); c.lineTo(w, Y(start)); c.stroke(); c.setLineDash([]); }
      const g = c.createLinearGradient(0, padT, 0, h); g.addColorStop(0, 'rgba(0,211,90,0.28)'); g.addColorStop(1, 'rgba(0,211,90,0)');
      c.beginPath(); P.forEach((p, i) => i ? c.lineTo(X(p[0]), Y(p[1])) : c.moveTo(X(p[0]), Y(p[1]))); c.lineTo(X(last[0]), h); c.lineTo(X(P[0][0]), h); c.closePath(); c.fillStyle = g; c.fill();
      c.beginPath(); P.forEach((p, i) => i ? c.lineTo(X(p[0]), Y(p[1])) : c.moveTo(X(p[0]), Y(p[1]))); c.strokeStyle = '#00d35a'; c.lineWidth = 2; c.lineJoin = 'round'; c.stroke();
      // marks above the line; a later mark moves up a row when it would overlap
      c.font = '600 11px -apple-system, "SF Pro Text", sans-serif'; c.globalAlpha = markAlpha;
      const rows = [];
      (data.marks || []).filter(m => m.ts >= t0 && m.ts <= t1).forEach(m => {
        const x = X(m.ts), tw = c.measureText(m.text).width + 12, x0 = Math.min(Math.max(2, x - tw / 2), w - tw - 2);
        let row = 0; while ((rows[row] || []).some(([a, b]) => !(x0 + tw < a || x0 > b))) row++;
        (rows[row] = rows[row] || []).push([x0, x0 + tw]);
        const y = 6 + row * 22; c.fillStyle = m.color; c.globalAlpha = markAlpha * 0.18; roundRect(c, x0, y, tw, 18, 9); c.fill();
        c.globalAlpha = markAlpha; c.fillStyle = m.color; c.fillText(m.text, x0 + 6, y + 13);
        c.globalAlpha = markAlpha * 0.5; c.strokeStyle = m.color; c.lineWidth = 1; c.beginPath(); c.moveTo(x, y + 18); c.lineTo(x, Y(valueAt(pts, m.ts))); c.stroke(); c.globalAlpha = markAlpha;
      });
      c.globalAlpha = 1;
    };
    const grew = pts.length > st.n && st.n > 0; const newMarks = (data.marks || []).length > (st.m || 0);
    st.n = pts.length; st.m = (data.marks || []).length;
    if (reduced() || (!grew && !newMarks)) return draw(1, 1);
    const t0 = performance.now();
    const step = now => { const k = Math.min(1, (now - t0) / 250), km = newMarks ? Math.min(1, (now - t0) / 200) : 1; draw(grew ? k : 1, km); if (k < 1 || km < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }
  function valueAt(pts, t) { let v = pts[0][1]; for (const p of pts) { if (p[0] <= t) v = p[1]; else break; } return v; }
  function roundRect(c, x, y, w, h, r) { c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); }

  // Coin screen: 1-minute OHLC candles + volume bars + orange dashed exit line.
  function candles(cv, cs, exitLine) {
    const [c, w, h] = setup(cv);
    if (!cs || !cs.length) { c.fillStyle = 'rgba(235,235,245,0.6)'; c.font = '14px -apple-system, sans-serif'; c.textAlign = 'center'; c.fillText('No candles yet', w / 2, h / 2); return; }
    const volH = h * 0.18, top = 8, bot = h - volH - 6;
    let lo = Math.min(...cs.map(k => k.l)), hi = Math.max(...cs.map(k => k.h));
    if (exitLine) { lo = Math.min(lo, exitLine); hi = Math.max(hi, exitLine); }
    if (hi - lo < hi * 1e-6) { hi *= 1.01; lo *= 0.99; }
    const Y = v => top + (1 - (v - lo) / (hi - lo)) * (bot - top);
    const n = Math.max(cs.length, 30), cw = w / n, bw = Math.max(1, cw * 0.62), vmax = Math.max(1e-9, ...cs.map(k => k.v));
    cs.forEach((k, i) => {
      const x = (n - cs.length + i) * cw + cw / 2, up = k.c >= k.o, col = up ? '#00d35a' : '#ff453a';
      c.strokeStyle = col; c.fillStyle = col; c.lineWidth = 1;
      c.beginPath(); c.moveTo(x, Y(k.h)); c.lineTo(x, Y(k.l)); c.stroke();
      const y1 = Y(Math.max(k.o, k.c)), y2 = Y(Math.min(k.o, k.c)); c.fillRect(x - bw / 2, y1, bw, Math.max(1, y2 - y1));
      c.globalAlpha = 0.45; const vh = (k.v / vmax) * volH; c.fillRect(x - bw / 2, h - vh, bw, vh); c.globalAlpha = 1;
    });
    if (exitLine) {
      const y = Y(exitLine); c.setLineDash([6, 5]); c.strokeStyle = '#ff9f0a'; c.lineWidth = 1.5; c.beginPath(); c.moveTo(0, y); c.lineTo(w, y); c.stroke(); c.setLineDash([]);
      c.fillStyle = '#ff9f0a'; c.font = '600 11px -apple-system, sans-serif'; c.textAlign = 'left'; c.fillText('Risk trailing stop', 6, y - 5);
    }
  }

  // Analyst score ring 0-100, green from min_score.
  function ring(cv, score, minScore) {
    const [c, w, h] = setup(cv); const r = Math.min(w, h) / 2 - 7, cx = w / 2, cy = h / 2;
    c.lineWidth = 10; c.lineCap = 'round'; c.strokeStyle = '#2c2c2e'; c.beginPath(); c.arc(cx, cy, r, 0, Math.PI * 2); c.stroke();
    if (score != null) { c.strokeStyle = score >= minScore ? '#00d35a' : '#ffd60a'; c.beginPath(); c.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * score / 100); c.stroke(); }
    c.fillStyle = '#fff'; c.font = '600 30px -apple-system, "SF Pro Display", sans-serif'; c.textAlign = 'center'; c.textBaseline = 'middle';
    c.fillText(score == null ? '–' : String(score), cx, cy);
  }
  window.Charts = {line, candles, ring};
})();
