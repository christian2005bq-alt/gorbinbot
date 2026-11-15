// Grok Bot desk app v2 (redesign 2026-11-14). Plain JS, no framework, no build step.
// Same APIs, same auth (#t= plan A / #d= plan B in localStorage), same PAPER/LIVE rules as v1. Only the look changed.
(function () {
  'use strict';
  const $ = (s, el = document) => el.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const reduced = () => window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const usd = (v, d = 2) => v == null ? 'n/a' : (v < 0 ? '-' : '') + '$' + Math.abs(v).toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d});
  const kfmt = v => v == null ? 'n/a' : v >= 1e9 ? '$' + (v / 1e9).toFixed(2) + 'B' : v >= 1e6 ? '$' + (v / 1e6).toFixed(2) + 'M' : v >= 1e3 ? '$' + (v / 1e3).toFixed(1) + 'K' : '$' + v.toFixed(0);
  const price = v => v == null ? 'n/a' : v >= 1 ? '$' + v.toFixed(4) : '$' + Number(v.toPrecision(4)).toString();
  const TZ = 'America/Guayaquil';
  const t12 = ts => ts ? new Date(ts * 1000).toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit', timeZone: TZ}) : '';
  const hms = ts => ts ? new Date(ts * 1000).toLocaleTimeString('es-EC', {hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZone: TZ}) : '';
  const ago = s => s == null ? '–' : s < 60 ? `${Math.max(0, Math.round(s))}s` : s < 3600 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`;
  const dur = s => s == null ? '' : `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m`;
  const cap = s => s ? s[0].toUpperCase() + s.slice(1) : '';
  const fmtInt = n => (n || 0).toLocaleString('en-US');

  // ---- auth: #t={APP_TOKEN} (plan A) or #d={DATA_PATH} (plan B), kept in localStorage, fragment removed at once
  const h0 = location.hash;
  if (h0.startsWith('#t=')) { localStorage.setItem('desk_t', decodeURIComponent(h0.slice(3))); localStorage.removeItem('desk_d'); history.replaceState(null, '', location.pathname + '#/home'); }
  if (h0.startsWith('#d=')) { localStorage.setItem('desk_d', decodeURIComponent(h0.slice(3))); localStorage.removeItem('desk_t'); history.replaceState(null, '', location.pathname + '#/home'); }
  const TOKEN = localStorage.getItem('desk_t'), DP = localStorage.getItem('desk_d');
  const PLAN = DP ? 'B' : 'A';

  const cache = {}; let lastOk = 0, failing = 0, retryAt = 0;
  function planBPath(p) {
    const [path, q] = p.split('?'); const qs = new URLSearchParams(q || '');
    const m = path.match(/^\/(state|activity|account|settings)$/); if (m) return [m[1] + '.json'];
    if (path === '/chart') return ['chart.json', j => j[(qs.get('range') || 'LIVE').toUpperCase()]];
    let mm = path.match(/^\/coin\/(.+)$/); if (mm) return ['coin/' + mm[1] + '.json'];
    mm = path.match(/^\/audit\/(.+)$/); if (mm) return ['audit/' + mm[1] + '.json'];
    mm = path.match(/^\/agents\/(\w+)\/decisions$/); if (mm) return ['agents/' + mm[1] + '.json'];
    return [null];
  }
  async function api(p, opts = {}) {
    let r;
    try {
      if (PLAN === 'B') {
        if (opts.method && opts.method !== 'GET') throw Object.assign(new Error('read-only'), {readonly: true});
        const [file, pick] = planBPath(p); if (!file) throw new Error('not in plan B');
        r = await fetch('d/' + DP + '/' + file + '?_=' + Date.now(), {cache: 'no-store'});
        if (r.status === 404 && /^\/(coin|audit)\//.test(p)) return null;
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const j = await r.json(); ok(); return pick ? pick(j) : j;
      }
      r = await fetch('api' + p, {method: opts.method || 'GET', cache: 'no-store',
        headers: Object.assign({'Authorization': 'Bearer ' + (TOKEN || '')}, opts.body ? {'Content-Type': 'application/json'} : {}),
        body: opts.body ? JSON.stringify(opts.body) : undefined});
    } catch (e) { if (e.readonly) throw e; fail(); throw e; }
    if (r.status === 401) { showAuth(); throw new Error('401'); }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(j.error || ('HTTP ' + r.status)); e.body = j; if (r.status >= 500) fail(); throw e; }
    ok(); return j;
  }
  function ok() { lastOk = Date.now(); failing = 0; $('#err').hidden = true; }
  function fail() { failing++; const n = Math.min(30, 2 ** Math.min(failing, 5)); retryAt = Date.now() + n * 1000; renderErr(); }
  function renderErr() {
    if (!failing) return; const e = $('#err'); e.hidden = false;
    const n = Math.max(0, Math.ceil((retryAt - Date.now()) / 1000));
    e.textContent = `Desk offline · retrying in ${n}s · last ${lastOk ? new Date(lastOk).toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit'}) : 'never'}`;
  }
  setInterval(renderErr, 1000);
  function showAuth() {
    $('#tabs').hidden = true;
    $('#view').innerHTML = `<div class="fade-in" style="min-height:80vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;gap:14px">
      <div class="av" style="width:72px;height:72px">${LOGO.replace('width="22"', '')}</div><div style="font-size:26px;font-weight:800">Grok Bot</div>
      <div class="muted" style="max-width:290px;line-height:1.45">Open the app once with the private link Grok Bot sent you on Telegram (it ends in #t=… or #d=…).</div></div>`;
  }
  function toast(t) { const d = document.createElement('div'); d.className = 'toast'; d.textContent = t; document.body.appendChild(d); setTimeout(() => d.remove(), 2400); }

  // ---- visual helpers
  const LOGO = `<svg viewBox="0 0 24 24" width="22"><path fill="#000" d="M12 2.5a9.5 9.5 0 1 0 0 19 9.5 9.5 0 0 0 0-19Zm-4.6 6.3a2 2 0 1 1 0 4 2 2 0 0 1 0-4Zm9.2 0a2 2 0 1 1 0 4 2 2 0 0 1 0-4ZM7 15.2c1.3 1.5 3 2.3 5 2.3s3.7-.8 5-2.3"/><circle cx="7.4" cy="10.8" r="1" fill="#fff"/><circle cx="16.6" cy="10.8" r="1" fill="#fff"/></svg>`;
  const ICON = {
    scanner: ['#30D5C8', '<path d="M12 2l2.2 4.3 4.8-.9-1.6 4.6L21 13.6l-4.7 1.3-.6 4.9L12 16.6l-3.7 3.2-.6-4.9L3 13.6l3.6-3.6L5 5.4l4.8.9z"/><circle cx="9.8" cy="11.5" r="1.1" fill="#1C1C1E"/><circle cx="14.2" cy="11.5" r="1.1" fill="#1C1C1E"/>'],
    auditor: ['#64A8FF', '<path d="M12 2.5l8 3v6c0 5-3.4 8.6-8 10-4.6-1.4-8-5-8-10v-6z"/><path d="M8.5 12l2.4 2.4 4.6-4.8" stroke="#1C1C1E" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'],
    analyst: ['#FF3B30', '<path d="M5 4h14l-2 14-5 3-5-3z"/><path d="M9.5 9.5l5 5M14.5 9.5l-2 2" stroke="#1C1C1E" stroke-width="2.2" stroke-linecap="round"/>'],
    executor: ['#AF52DE', '<path d="M6 8.5C6 5.5 8.7 3.5 12 3.5s6 2 6 5c2 .3 3.5 2 3.5 4 0 2.5-2 4.5-4.5 4.5H7a4.5 4.5 0 0 1-1-8.5z"/><circle cx="10" cy="12" r="1.3" fill="#1C1C1E"/><circle cx="14" cy="12" r="1.3" fill="#1C1C1E"/>'],
    risk: ['#FF9F0A', '<path d="M12 5c-5 0-8.5 3.3-8.5 7.6S7 20.5 12 20.5s8.5-3.6 8.5-7.9S17 5 12 5z"/><path d="M12 5c0-1.5.8-2.5 2.3-2.8" stroke="#FF9F0A" stroke-width="1.8" fill="none" stroke-linecap="round"/><circle cx="9.3" cy="12.3" r="1.4" fill="#1C1C1E"/><circle cx="14.7" cy="12.3" r="1.4" fill="#1C1C1E"/>'],
    brain: ['#BF5AF2', '<path d="M9 3.5a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V5a2.5 2.5 0 0 0-3-1.5zM15 3.5a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1V5a2.5 2.5 0 0 1 3-1.5z"/>'],
    action: ['#34C759', '<circle cx="12" cy="12" r="9"/><path d="M7.5 12.3l3 3 6-6.3" stroke="#1C1C1E" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'],
  };
  const tile = (k, cls = '') => `<div class="tile ${cls}"><svg viewBox="0 0 24 24" fill="${ICON[k][0]}">${ICON[k][1]}</svg></div>`;
  const AGC = {scanner: '#64D2FF', auditor: '#ffffff', analyst: '#FFD60A', brain: '#BF5AF2', executor: '#34C759', risk: '#FF6B9A'};
  const PALETTE = ['#FF9F0A', '#0A84FF', '#AF52DE', '#34C759', '#FF375F', '#64D2FF', '#FFD60A', '#5E5CE6', '#30D5C8', '#FF6B3D'];
  function hash(s) { let h = 0; for (const ch of String(s || '')) h = (h * 31 + ch.charCodeAt(0)) | 0; return Math.abs(h); }
  function coinIcon(name, mint, size = 40) {
    const n = String(name || mint || '?').replace(/^\$/, ''); const c1 = PALETTE[hash(mint || n) % PALETTE.length], c2 = PALETTE[(hash(mint || n) >> 3) % PALETTE.length];
    const letter = esc([...n][0] || '?');
    return `<span class="ci s${size}" style="background:linear-gradient(135deg,${c1},${c2})">${letter}</span>`;
  }
  const BADGE = {
    bought: ['#0A84FF', '<path d="M7 17L17 7M9 7h8v8"/>'], soldUp: ['#34C759', '<path d="M17 7L7 17M15 17H7V9"/>'], soldDown: ['#FF3B30', '<path d="M17 7L7 17M15 17H7V9"/>'],
    stopped: ['#FF3B30', '<path d="M7 7l10 10M17 7L7 17"/>'], rejected: ['#48484A', '<path d="M6 12h12"/>']};

  function animateNum(el, to, fmt, dur = 900) {
    const from = el._v == null ? to : el._v; el._v = to;
    const paint = v => { const s = fmt(v), i = s.lastIndexOf('.'); el.innerHTML = i > 0 ? esc(s.slice(0, i)) + '<span class="c">' + esc(s.slice(i)) + '</span>' : esc(s); };
    if (reduced() || from === to) return paint(to);
    const t0 = performance.now();
    const step = now => { const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3); paint(from + (to - from) * e); if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }

  // ---- activity rows: turn the server's title/subtitle/value strings into the app look
  function actView(r) {
    const [v1 = '', v2 = ''] = String(r.value || '').split(' · ');
    const name = String(r.title || '').split(' ').slice(1).join(' ') || (r.mint || '').slice(0, 6);
    const tm = t12(r.ts);
    let sub = String(r.subtitle || '');
    sub = /\d{1,2}:\d{2}$/.test(sub) ? sub.replace(/\d{1,2}:\d{2}$/, tm) : (sub ? sub + ' · ' + tm : cap(r.agent) + ' · ' + tm);
    let col = '#fff', right = v1, rsub = '', badge = BADGE.rejected;
    if (r.kind === 'bought') { rsub = 'on fomo'; badge = BADGE.bought; }
    else if (r.kind === 'sold') { const up = !v1.startsWith('-'); col = up ? 'var(--green)' : 'var(--red)'; rsub = v2; badge = up ? BADGE.soldUp : BADGE.soldDown; }
    else if (r.kind === 'stopped') { col = 'var(--red)'; rsub = ((r.subtitle || '').match(/-\d+(?:\.\d+)?%/) || [''])[0]; badge = BADGE.stopped; }
    else { col = 'var(--sec)'; right = 'Skipped'; }
    return {name, sub, col, right, rsub, badge};
  }
  function actRow(r) {
    const a = actView(r), href = r.kind === 'rejected' ? `#/audit/${esc(r.mint)}` : `#/coin/${esc(r.mint)}`;
    return `<a class="row" href="${href}"><div class="ico">${coinIcon(a.name, r.mint, 40)}<span class="badge" style="background:${a.badge[0]}"><svg viewBox="0 0 24 24">${a.badge[1]}</svg></span></div>
      <div class="mid"><div class="t">${esc(r.title)}</div><div class="s">${esc(a.sub)}</div></div>
      <div class="v"><b style="color:${a.col}">${esc(a.right)}</b>${a.rsub ? `<span>${esc(a.rsub)}</span>` : ''}</div></a>`;
  }
  const isTrade = r => ['bought', 'sold', 'stopped'].includes(r.kind);
  function noTrades(st) {
    const sc = st && st.agents.find(a => a.name === 'scanner');
    return `<div class="emptycard"><div class="pulse"></div><b>No trades yet tonight</b>Scanner has checked ${fmtInt(sc ? sc.pools : 0)} pools. Every buy and sell shows up here the second it happens.</div>`;
  }

  // ---- banners + confetti
  const seenAct = new Set(); let actPrimed = false;
  function noteActivity(rows, announce) {
    rows.forEach(r => { if (!seenAct.has(r.id)) { seenAct.add(r.id); if (announce && actPrimed && isTrade(r) && Date.now() / 1000 - r.ts < 600) banner(r); } });
    actPrimed = true;
  }
  function banner(r) {
    const a = actView(r), host = $('#banners');
    let t, s;
    if (r.kind === 'bought') { t = `Bought ${a.right} ${a.name}`; s = `Executor · on fomo${r.mode === 'PAPER' || (cache.state && cache.state.mode === 'PAPER') ? ' · PAPER' : ''}`; }
    else if (r.kind === 'sold') { t = `Sold ${a.name} · ${a.right}`; s = `${a.rsub ? a.rsub + ' · ' : ''}${(r.subtitle || '').replace(/^Risk · /, '')}`; }
    else { t = `Stopped ${a.name} · ${a.right}`; s = (r.subtitle || '').replace(/^Risk · /, '') || 'Risk'; }
    const el = document.createElement('a'); el.className = 'bn'; el.href = '#/coin/' + r.mint;
    el.innerHTML = `${coinIcon(a.name, r.mint, 40)}<div class="mid"><div class="t" style="${r.kind === 'bought' ? '' : `color:${a.col}`}">${esc(t)}</div><div class="s">${esc(s)}</div></div><div class="now">now</div>`;
    host.prepend(el); while (host.children.length > 3) host.lastChild.remove();
    const pct = parseFloat((a.rsub || '').replace('%', ''));
    if (r.kind === 'sold' && pct >= 100) confetti();
    setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 320); }, 5000);
    if (navigator.vibrate) try { navigator.vibrate(18); } catch (e) {}
  }
  function confetti() {
    if (reduced()) return; const cv = $('#confetti'), dpr = window.devicePixelRatio || 1;
    cv.width = innerWidth * dpr; cv.height = innerHeight * dpr; const c = cv.getContext('2d'); c.setTransform(dpr, 0, 0, dpr, 0, 0);
    const cols = ['#34C759', '#FFD60A', '#0A84FF', '#FF375F', '#AF52DE', '#fff'];
    const ps = Array.from({length: 140}, () => ({x: innerWidth / 2 + (Math.random() - .5) * 80, y: innerHeight * .28, vx: (Math.random() - .5) * 13, vy: -Math.random() * 13 - 4, r: Math.random() * 6.28, vr: (Math.random() - .5) * .4, w: 6 + Math.random() * 5, h: 3 + Math.random() * 4, c: cols[Math.random() * cols.length | 0]}));
    const t0 = performance.now();
    const step = now => {
      c.clearRect(0, 0, innerWidth, innerHeight); const k = (now - t0) / 2600;
      ps.forEach(p => { p.vy += .32; p.vx *= .99; p.x += p.vx; p.y += p.vy; p.r += p.vr; c.save(); c.globalAlpha = Math.max(0, 1 - k); c.translate(p.x, p.y); c.rotate(p.r); c.fillStyle = p.c; c.fillRect(-p.w / 2, -p.h / 2, p.w, p.h); c.restore(); });
      if (k < 1) requestAnimationFrame(step); else c.clearRect(0, 0, innerWidth, innerHeight);
    };
    requestAnimationFrame(step);
  }

  // ---- LIVE: status strip + decision feed (every Scanner/Auditor/Analyst/Brain/Executor/Risk decision)
  const AG_ES = {scanner: 'Scanner', auditor: 'Auditor', analyst: 'Analyst', brain: 'Brain', executor: 'Executor', risk: 'Risk'};
  const vColor = v => /kill|reject|skip|failed|missed|stop/.test(v) ? 'var(--red)' : /pass|bought|size/.test(v) ? 'var(--green)' : /waiting/.test(v) ? '#64D2FF' : 'var(--sec)';
  function stripHtml(L) {
    if (!L) return '<div class="lstrip skel" style="height:96px"></div>';
    const w = L.window, c = L.counts, now = Date.now() / 1000, skew = now - L.now;
    const ag = L.agents.map(a => { const age = a.heartbeat ? now - skew - a.heartbeat : null, ok = a.heartbeat && age < 150;
      return `<span class="hb ${a.paused ? 'pz' : ok ? 'ok' : 'bad'}" data-hb="${a.heartbeat || ''}"><i></i>${AG_ES[a.name]} <em>${a.paused ? 'pausado' : ago(age)}</em></span>`; }).join('');
    const win = w.open ? `<b class="wo">Ventana abierta</b> ${esc(w.start)}–${esc(w.end)} · cierra en ${dur(w.closes_in_s)}` : `<b class="wc">Ventana cerrada</b> abre a las ${esc(w.start)} (en ${dur(w.opens_in_s)})`;
    const tk = (L.top_kills || []).map(k => `${esc(k.reason)} ${k.n}`).join(' · ');
    return `<div class="lstrip"><div class="lwin">${win} <span class="muted">· ${esc(L.mode)} · hora Ecuador</span></div>
      <div class="lcnt"><div><b>${fmtInt(c.seen)}</b><span>vistas</span></div><div><b>${fmtInt(c.scanned)}</b><span>revisadas</span></div><div><b class="dn">${fmtInt(c.killed)}</b><span>descartadas</span></div><div><b class="upc">${fmtInt(c.passed)}</b><span>pasan</span></div><div><b>${fmtInt(c.waiting)}</b><span>en espera</span></div></div>
      <div class="lhb">${ag}</div>
      ${L.box && L.box.sleeps ? `<div class="lrule" style="color:var(--orange)">La computadora del bot se pausó ${L.box.sleeps} ${L.box.sleeps === 1 ? 'vez' : 'veces'} esta noche (${L.box.slept_min} min en total; última ${L.box.last_sleep_min} min, despertó ${t12(L.box.last_wake_ts)}). En pausa nadie vigila.</div>` : ''}
      <div class="lrule muted">Regla Scanner: liquidez ≥ ${kfmt(L.rules.min_liquidity_usd)} · top10 ≤ ${L.rules.max_top10_pct}% · 1h ≤ +${L.rules.max_h1_change_pct}%${tk ? ' · motivos: ' + tk : ''}</div></div>`;
  }
  function feedRow(f) {
    const href = f.agent === 'scanner' || f.verdict === 'reject' ? `#/audit/${esc(f.mint)}` : `#/coin/${esc(f.mint)}`;
    const strike = f.verdict === 'kill' ? ' kill' : '';
    return `<a class="frow${strike}" href="${f.mint ? href : '#/activity'}"><span class="ft">${esc(f.time || hms(f.ts))}</span><span class="fa" style="color:${AGC[f.agent] === '#ffffff' ? '#64A8FF' : (AGC[f.agent] || '#fff')}">${esc(AG_ES[f.agent] || f.agent)}</span>
      <span class="fn">${esc(f.name || f.short || '')}</span><span class="fv" style="color:${vColor(f.verdict)}">${esc(f.verdict_es || f.verdict)}</span><span class="fr">${esc(f.reason || '')}</span></a>`;
  }
  function tickLive() {   // every second: heartbeat ages + 'actualizado hace Xs' without refetching
    const now = Date.now() / 1000, L = cache.live, skew = L ? now - L.now : 0;
    document.querySelectorAll('.hb[data-hb]').forEach(el => { const t = +el.dataset.hb; if (!t || el.classList.contains('pz')) return; const age = now - skew - t;
      el.querySelector('em').textContent = ago(age); el.classList.toggle('ok', age < 150); el.classList.toggle('bad', age >= 150); });
    const fa = cache.fomo, el = $('#fomo-ago'); if (fa && el && fa.synced_at) el.textContent = 'actualizado hace ' + ago(now - (fa._skew || 0) - fa.synced_at);
  }
  setInterval(tickLive, 1000);
  function fomoCard() {
    const f = cache.fomo; if (!f) return '<div class="fomo skel" style="height:120px"></div>';
    const has = f.cash != null;
    const pos = (f.positions || []).length ? f.positions.map(p => `<div class="fp">${coinIcon(p.symbol, p.mint, 18)}<span>${esc(p.symbol || (p.mint || '').slice(0, 6))}</span><b>${p.value_usd != null ? usd(p.value_usd) : fmtInt(Math.round(p.tokens || 0)) + ' tokens'}</b></div>`).join('') : '<div class="muted fs">Sin monedas · todo en efectivo</div>';
    const tr = (f.trades || []).slice(0, 4).map(t => `<div class="ftr"><span>${esc(t.when || hms(t.ts))}</span><span>${esc(t.side ? (t.side === 'buy' ? 'Compra' : 'Venta') + ' ' + (t.symbol || '') : (t.sig ? 'tx ' + t.sig.slice(0, 6) + '…' : ''))}</span><b>${t.usd != null ? usd(t.usd) : (t.ok === false ? 'falló' : '')}</b></div>`).join('');
    const src = f.live ? `en vivo · cada ${f.poll_s}s · cadena Solana` : f.source === 'screen' ? 'leído de la pantalla de FOMO (no en vivo)' : 'sin datos';
    return `<div class="fomo"><div class="fh"><span class="fl">FO</span><b>Cuenta FOMO</b><span class="real">real</span><span class="r" id="fomo-ago">${f.synced_at ? 'actualizado hace ' + ago(f.age_s) : ''}</span></div>
      <div class="fcash">${has ? usd(f.cash) : 'n/a'}<span> efectivo</span></div>
      ${has ? `<div class="muted fs">Total ${usd(f.total_usd)} · monedas ${usd(f.holdings_usd)}${f.handle ? ' · @' + esc(f.handle) : ''}</div>` : ''}
      <div class="fpos">${pos}</div>${tr ? `<div class="ftrs"><div class="muted fs">Últimos trades en FOMO</div>${tr}</div>` : ''}
      <div class="muted fsrc">${esc(src)}${f.error ? ' · ' + esc(f.error) : ''}${f.note ? ' · ' + esc(f.note) : ''} · solo lectura</div></div>`;
  }
  function setFomo(j) { if (!j) return; j._skew = Date.now() / 1000 - (j.synced_at && j.age_s != null ? j.synced_at + j.age_s : Date.now() / 1000); cache.fomo = j; const el = $('#fomo-wrap'); if (el) el.innerHTML = fomoCard(); }

  // ---- router
  let S = {range: 'LIVE', screen: null, animChart: true};
  const routes = {home, agents, activity, account, coin, audit, picks};
  async function route() {
    if (!TOKEN && !DP) return showAuth();
    const [, name = 'home', arg] = (location.hash.match(/^#\/(\w+)(?:\/(.+))?/) || []);
    const prev = S.screen; S.screen = name; S.arg = arg;
    document.querySelectorAll('.tabs a').forEach(a => a.classList.toggle('on', a.dataset.tab === (name === 'coin' || name === 'audit' ? 'home' : name === 'picks' ? 'account' : name)));
    $('#tabs').hidden = false;
    window.scrollTo(0, 0);
    if (name === 'home' && prev !== 'home') S.animChart = true;
    await (routes[name] || home)(arg);
  }
  window.addEventListener('hashchange', route);

  // ---- HOME
  function homeSkeleton() {
    return `<div class="hd"><div class="skel" style="width:140px;height:34px;border-radius:17px"></div><div class="skel" style="width:84px;height:32px;border-radius:16px"></div></div>
      <div class="skel" style="height:56px;width:62%;margin-top:18px"></div><div class="skel" style="height:22px;width:45%;margin-top:10px"></div>
      <div class="skel" style="height:210px;margin:16px 0"></div><div class="skel" style="height:32px"></div>
      <div style="display:flex;gap:10px;margin-top:24px"><div class="skel" style="height:170px;flex:0 0 62%;border-radius:18px"></div><div class="skel" style="height:170px;flex:1;border-radius:18px"></div></div>`;
  }
  async function home() {
    const v = $('#view');
    if (!cache.state) v.innerHTML = homeSkeleton();
    try { cache.state = await api('/state'); } catch (e) { if (!cache.state) { v.innerHTML = homeSkeleton(); return; } }
    const jobs = [
      api('/chart?range=' + S.range).then(j => cache['chart' + S.range] = j),
      api('/activity').then(j => { cache.activity = j; noteActivity(j.rows, true); }),
      ...['analyst', 'executor', 'risk'].map(n => api(`/agents/${n}/decisions`).then(j => cache['dec_' + n] = j)),
      PLAN === 'A' ? api('/live').then(j => cache.live = j) : Promise.resolve(),
      PLAN === 'A' ? api('/fomo_account').then(j => setFomo(j)) : Promise.resolve(),
    ];
    await Promise.allSettled(jobs);
    if (S.screen !== 'home') return;
    renderHome();
  }
  function enrichMarks(marks) {
    const rows = (cache.activity || {rows: []}).rows;
    return (marks || []).map(m => {
      const r = rows.find(x => Math.abs(x.ts - m.ts) < 1 && x.kind === m.kind);
      if (r) { const a = actView(r); return {...m, name: a.name, verb: m.kind === 'bought' ? 'bought' : m.kind === 'stopped' ? 'stop' : 'sold', amount: a.right, loss: a.right.startsWith('-')}; }
      if (m.kind === 'bought') return {...m, name: (m.text || '').replace(/^Bought /, ''), verb: 'bought', amount: ''};
      const amt = (m.text || '').split(' · ').pop(); return {...m, name: '', verb: m.kind === 'stopped' ? 'stop' : 'sold', amount: amt, loss: amt.startsWith('-')};
    });
  }
  function renderHome() {
    const st = cache.state, v = $('#view'); if (!st) return;
    if (!$('#home-root')) {
      v.innerHTML = `<div id="home-root" class="fade-in">
      <div class="hd"><a class="who" href="#/account"><div class="av">${LOGO}</div>Grok Bot<span class="chev">›</span></a><a href="#/account" class="modepill" id="mode"><i></i><span></span></a></div>
      <div class="subhd"><span class="fl">FO</span><b>fomo</b> trading · <span id="nopen"></span> open <span class="gd"></span><span class="tm" id="clock"></span></div>
      <div id="strip"></div>
      <div class="ballab" id="ballab"></div>
      <div class="bal" id="bal"></div>
      <div class="chg" id="chg"><span id="delta"></span><span class="mult" id="mult"></span></div>
      <div class="chart"><canvas id="line"></canvas><div class="wait" id="wait" hidden>Waiting for the first trade</div></div>
      <div class="ranges" id="ranges">${['LIVE', '1H', '4H', '1D', '1W', 'ALL'].map(r => `<button data-r="${r}">${r}</button>`).join('')}</div>
      <div id="fomo-wrap"></div>
      <div class="livecard" id="livecard"><img id="liveimg" alt=""><div class="lvtop"><span id="lvdot" class="lvdot"></span><span id="lvtxt">Live screen off</span><span class="lvr" id="lvwho"></span></div><div class="lvlast" id="lvlast"></div></div>
      <div class="sec"><h2>Agents</h2><a class="r" href="#/agents" id="running"></a></div>
      <div class="car" id="cards"></div><div class="dots" id="dots"></div>
      <div class="sec"><h2>Activity</h2><a class="r" href="#/activity">See all</a></div>
      <div id="act5"></div>
      <div class="sec"><h2>En vivo · decisiones</h2><a class="r" href="#/activity" id="seelive">Ver todo</a></div>
      <div id="feed8"></div></div>`;
      $('#ranges').onclick = e => { const r = e.target.closest('button'); if (!r) return; S.range = r.dataset.r; S.animChart = true;
        api('/chart?range=' + S.range).then(j => { cache['chart' + S.range] = j; renderHome(); }).catch(() => renderHome()); };
      $('#cards').addEventListener('scroll', syncDots, {passive: true});
    }
    const live = st.mode === 'LIVE', m = $('#mode'); m.className = 'modepill' + (live ? '' : ' paper'); m.querySelector('span').textContent = live ? 'LIVE' : 'PAPER';
    $('#ballab').innerHTML = live ? 'Saldo del desk (LIVE)' : '<span class="pillp">PAPER</span> PAPER (simulado) · no es tu dinero real';
    $('#strip').innerHTML = stripHtml(cache.live);
    $('#fomo-wrap').innerHTML = fomoCard();
    const fd = (cache.live && cache.live.feed) || [];
    $('#feed8').innerHTML = fd.length ? `<div class="feed2">${fd.slice(0, 8).map(feedRow).join('')}</div>` : '<div class="emptycard"><b>Nada todavía esta noche</b>Cada moneda que revise el Scanner aparece aquí al instante.</div>';
    const risk = st.agents.find(a => a.name === 'risk'); $('#nopen').textContent = risk ? risk.open : 0;
    $('#clock').textContent = new Date().toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit'});
    animateNum($('#bal'), st.balance, x => usd(x));
    const delta = st.balance - st.start_balance, up = delta >= 0;
    $('#delta').className = up ? 'up' : 'down';
    $('#delta').textContent = `${up ? '▲' : '▼'} ${usd(Math.abs(delta))} (${Math.abs(st.today_pct).toFixed(2)}%)`;
    $('#mult').className = 'mult' + (st.multiplier < 1 ? ' down' : ''); $('#mult').textContent = st.multiplier.toFixed(2) + 'x';
    const running = st.agents.filter(a => !a.paused).length; $('#running').textContent = `${running} running`;
    document.querySelectorAll('#ranges button').forEach(b => b.classList.toggle('on', b.dataset.r === S.range));
    const ch = cache['chart' + S.range] || {points: [], marks: []};
    const rows = (cache.activity || {rows: []}).rows, trades = rows.filter(isTrade);
    const marks = enrichMarks(ch.marks);
    $('#wait').hidden = marks.length > 0 || trades.length > 0;
    let pts = ch.points || [];
    if (!marks.length && !trades.length) pts = [];  // nothing traded: a calm flat line, not paper-cash noise
    Charts.line($('#line'), {points: pts, marks, start_value: ch.start_value}, {animate: S.animChart}); S.animChart = false;
    paintLive(st);
    const keep = $('#cards').scrollLeft;
    $('#cards').innerHTML = st.agents.map(agentCard).join(''); $('#cards').scrollLeft = keep;
    $('#dots').innerHTML = st.agents.map((_, i) => `<i class="${i === 0 ? 'on' : ''}"></i>`).join(''); syncDots();
    const an = st.agents.find(a => a.name === 'analyst'); const rc = $('#ring'); if (rc && an) Charts.ring(rc, an.score, an.min_score, an.passed);
    $('#act5').innerHTML = trades.length ? `<div class="rows">${trades.slice(0, 5).map(actRow).join('')}</div>`
      : rows.length ? `<div class="rows">${rows.slice(0, 3).map(actRow).join('')}</div><div style="height:10px"></div>${noTrades(st)}` : noTrades(st);
  }
  // ---- LIVE SCREEN (the bot's Chrome, 1 frame/s, double buffered; only when desk.autoclick is dryrun|on)
  let liveTimer = null, liveUrl = null;
  function paintLive(st) {
    const L = st.lane || {mode: 'off'}, card = $('#livecard'); if (!card) return;
    const fresh = L.last_frame_ts && (Date.now() / 1000 - L.last_frame_ts) < 5;
    $('#lvdot').className = 'lvdot' + (fresh ? ' on' : '');
    $('#lvtxt').textContent = L.mode === 'off' ? 'Live screen off · auto-click off' : L.private ? 'Paused · private' : fresh ? 'Live · Bot\'s computer' : (L.last_frame_ts ? 'Last frame ' + t12(L.last_frame_ts) : (L.status || 'waiting for Chrome'));
    $('#lvwho').textContent = L.holder ? `${cap(L.holder[0])} · ${L.holder[1] === 'buy' ? 'buying' : 'selling'}` : 'Idle';
    $('#lvwho').style.color = L.holder ? (AGC[L.holder[0]] || '#fff') : '';
    const lo = st.last_order; $('#lvlast').innerHTML = lo ? `${esc(cap(lo.side))} ${esc(lo.name || '')} · ${usd(lo.usd)} · ${esc(lo.status)} <span class="ck">${['screen_ok', 'api_ok', 'chain_ok'].map(k => lo[k] ? '✓' : '·').join(' ')}</span>` : (L.mode === 'off' ? 'Clicks are off. Grok Bot only shows FOMO links.' : 'No order yet');
    if (L.mode !== 'off' && PLAN === 'A' && !liveTimer) liveTimer = setInterval(pullFrame, 1000);
    if ((L.mode === 'off' || PLAN !== 'A') && liveTimer) { clearInterval(liveTimer); liveTimer = null; }
  }
  async function pullFrame() {
    if (S.screen !== 'home' || document.hidden) return;
    try {
      const r = await fetch('api/screen.jpg?_=' + Date.now(), {cache: 'no-store', headers: {'Authorization': 'Bearer ' + (TOKEN || '')}});
      if (!r.ok) return; const b = await r.blob(); const u = URL.createObjectURL(b);
      const pre = new Image(); pre.onload = () => { const im = $('#liveimg'); if (im) { im.src = u; im.classList.add('on'); } if (liveUrl) URL.revokeObjectURL(liveUrl); liveUrl = u; }; pre.src = u;
    } catch (e) {}
  }
  function syncDots() {
    const c = $('#cards'); if (!c || !c.firstElementChild) return; const w = c.firstElementChild.offsetWidth + 10;
    const i = c.scrollLeft + c.clientWidth >= c.scrollWidth - 4 ? c.children.length - 1 : Math.round(c.scrollLeft / w);
    document.querySelectorAll('#dots i').forEach((d, k) => d.classList.toggle('on', k === i));
  }
  function decTop(n) { const d = cache['dec_' + n]; return d && d.rows && d.rows[0]; }
  const coinLabel = r => r ? (r.symbol || r.name || (r.mint || '').slice(0, 6)) : '';
  function agentCard(a) {
    const off = a.paused ? ' off' : '';
    const head = (k, status) => `<div class="ah">${tile(k)}<div><div class="an">${cap(k)}</div><div class="st${off}" style="color:${AGC[k] === '#ffffff' ? '#64A8FF' : AGC[k]}">${a.paused ? 'paused' : status}</div></div></div>`;
    const box = inner => `<a class="acard" href="#/agents">${inner}</a>`;
    if (a.name === 'scanner') {
      const feed = a.feed.slice(0, 3).map(f => f.verdict === 'kill'
        ? `<div class="r kill">${coinIcon(f.symbol || f.name, f.mint, 18)}<span class="nm">${esc(f.symbol || f.name || f.mint.slice(0, 6))}</span><span class="tag rd">${esc(f.reason || 'killed')}</span></div>`
        : `<div class="r">${coinIcon(f.symbol || f.name, f.mint, 18)}<span class="nm">${esc(f.symbol || f.name)}</span><span class="tag g">→ auditor</span></div>`).join('');
      return box(head('scanner', `${fmtInt(a.pools)} pools`) + `<div class="feed">${feed || '<div class="muted" style="font-size:13px">Listening for graduations…</div>'}</div>`);
    }
    if (a.name === 'auditor') {
      const strips = a.strips.map(s => `<i class="${s === true ? 'ok' : s === false ? 'no' : ''}"></i>`).join('');
      const line = a.running ? 'taking apart…' : (a.result || 'No coin taken apart yet');
      return box(head('auditor', `${a.taken_apart} taken apart`) + `<div class="strips">${strips}</div>
        <div class="mini">${a.name_coin ? coinIcon(a.name_coin, a.mint, 28) : ''}<div style="min-width:0"><div class="t">${esc(a.name_coin || 'Waiting')}</div><div class="s">${esc(line)}</div></div></div>
        <div class="muted" style="margin-top:auto;font-size:12px">${a.rejected} rejected tonight</div>`);
    }
    if (a.name === 'analyst') {
      const r = decTop('analyst'), nm = r && r.mint === a.mint ? coinLabel(r) : (a.mint ? a.mint.slice(0, 6) : '');
      const res = a.score == null ? `<div class="t muted">No coin yet</div><div class="s muted">waiting…</div>`
        : `${coinIcon(nm, a.mint, 28)}<div class="t">${esc(nm)}</div><div class="s ${a.passed ? 'up' : 'down'}">${a.passed ? 'passed' : 'rejected'}</div>`;
      return box(head('analyst', a.mode === 'rules' ? 'Scoring · rules' : 'Scoring') + `<div class="anrow"><div class="ringw"><canvas id="ring"></canvas><b>${a.score == null ? '–' : Math.round(a.score)}</b></div><div class="who2">${res}</div></div>`);
    }
    if (a.name === 'brain') {
      const line = a.size ? `${usd(a.size)} · ${a.pct}% of cash` : 'No coin sized yet';
      return box(head('brain', 'Sizing') + `<div class="mini"><div style="min-width:0"><div class="t">${esc(line)}</div><div class="s">${a.cap && a.cap !== 'none' ? 'cap: ' + esc(a.cap) : 'free cash ' + usd(a.free_cash)}</div></div></div>
        <div class="chips"><span class="chip g">${a.full_score}+ = full size</span><span class="chip y">under = half</span></div>
        <div class="muted" style="margin-top:auto;font-size:12px">${a.trades}/${a.max_trades} trades tonight${a.block ? ' · ' + esc(a.block) : ''}</div>`);
    }
    if (a.name === 'executor') {
      const r = decTop('executor');
      if (a.waiting) return box(head('executor', `${a.trades} trades`) + (r ? `<div class="mini">${coinIcon(coinLabel(r), r.mint, 28)}<div style="min-width:0"><div class="t">${esc(coinLabel(r))}</div><div class="s">${esc(r.reason || '')}</div></div></div>` : '') + `<div class="fillbtn idle">Waiting for a dip -${a.dip_pct}% · ${a.waiting}</div>`);
      const fresh = a.state_ts && (Date.now() / 1000 - a.state_ts) < 30;
      const btn = a.state === 'executing' ? `<div class="fillbtn">${a.autoclick === 'on' ? 'Clicking Buy…' : 'Buying…'}</div>` : a.trades || (a.state === 'filled' && fresh) ? `<div class="fillbtn">✓ Filled</div>` : `<div class="fillbtn idle">Waiting for a cleared coin</div>`;
      const mini = r ? `<div class="mini">${coinIcon(coinLabel(r), r.mint, 28)}<div style="min-width:0"><div class="t">${esc(coinLabel(r))}</div><div class="s">${esc(r.reason || '')} · on fomo</div></div></div>`
        : `<div class="mini"><div style="min-width:0"><div class="t muted">No buys yet</div><div class="s">Brain sizes · auto-click ${esc(a.autoclick || 'off')}</div></div></div>`;
      return box(head('executor', `${a.trades} trades`) + mini + btn);
    }
    const r = decTop('risk');
    const lastLine = r ? `<div class="mini">${coinIcon(coinLabel(r), r.mint, 28)}<div style="min-width:0"><div class="t">${esc(a.last_exit || cap(r.verdict))}</div><div class="s ${/-\$/.test(r.reason || '') ? 'down' : 'up'}">${esc(r.reason || '')}</div></div></div>`
      : `<div class="mini"><div style="min-width:0"><div class="t">${a.open ? a.open + ' open · watching' : 'Nothing to guard'}</div><div class="s">exits every trade on its own</div></div></div>`;
    return box(head('risk', a.open ? `Guarding ${a.open}` : 'Guarding') + lastLine + `<div class="chips"><span class="chip r">stop -${a.stop_pct}%</span><span class="chip y">trail ${a.trail_pct}%</span></div>`);
  }

  // ---- ACTIVITY TAB
  async function activity() {
    const v = $('#view'); S.filter = S.filter || (PLAN === 'A' ? 'live' : 'all');
    v.innerHTML = `<div class="fade-in"><div class="ttl"><h1>Activity</h1></div>
      <div class="seg2" id="flt">${[...(PLAN === 'A' ? [['live', 'En vivo']] : []), ['all', 'All'], ['trades', 'Trades'], ['skipped', 'Skipped']].map(([k, l]) => `<button data-f="${k}" class="${S.filter === k ? 'on' : ''}">${l}</button>`).join('')}</div>
      <div id="acts">${cache.activity ? '' : '<div class="skel" style="height:360px"></div>'}</div><div id="more"></div></div>`;
    let all = cache.activity ? cache.activity.rows.slice() : [], next = null, lfeed = null, lnext = null;
    const paint = () => {
      if (S.filter === 'live') {
        const L = cache.live; lfeed = lfeed || (L ? L.feed.slice() : []); if (lnext === null && L) lnext = L.next;
        $('#acts').innerHTML = stripHtml(L) + (lfeed.length ? `<div class="feed2">${lfeed.map(feedRow).join('')}</div>` : '<div class="emptycard"><b>Nada todavía esta noche</b>Cada decisión de los agentes aparece aquí al instante.</div>');
        $('#more').innerHTML = lnext ? `<button class="morebtn" id="load-more">Cargar más</button>` : '';
        if (lnext) $('#load-more').onclick = async () => { const j = await api('/live?before=' + lnext); lnext = j.next; lfeed = lfeed.concat(j.feed); paint(); };
        return;
      }
      const rows = all.filter(r => S.filter === 'all' || (S.filter === 'trades' ? isTrade(r) : r.kind === 'rejected'));
      $('#acts').innerHTML = rows.length ? `<div class="rows">${rows.map(actRow).join('')}</div>` : (S.filter === 'skipped' ? `<div class="emptycard"><b>Nothing skipped</b>Coins the Auditor or Analyst turn down show up here.</div>` : noTrades(cache.state));
      $('#more').innerHTML = next ? `<button class="morebtn" id="load-more">Load more</button>` : '';
      if (next) $('#load-more').onclick = async () => { const j = await api('/activity?before=' + next); next = j.next; all = all.concat(j.rows); paint(); };
    };
    $('#flt').onclick = e => { const b = e.target.closest('button'); if (!b) return; S.filter = b.dataset.f; document.querySelectorAll('#flt button').forEach(x => x.classList.toggle('on', x === b)); paint(); };
    if (cache.activity) paint();
    try { const [a, L] = await Promise.all([api('/activity'), PLAN === 'A' ? api('/live').catch(() => cache.live) : Promise.resolve(null)]); cache.activity = a; if (L) cache.live = L; noteActivity(cache.activity.rows, true); if (!cache.state) cache.state = await api('/state').catch(() => null); } catch (e) { return; }
    if (S.screen !== 'activity') return;
    all = cache.activity.rows.slice(); next = cache.activity.next; lfeed = null; lnext = null; paint();
  }

  // ---- AGENTS TAB
  async function agents() {
    const v = $('#view');
    v.innerHTML = `<div class="fade-in"><div class="ttl"><h1>Agents</h1><span class="r" id="ag-run"></span></div><div id="ag">${'<div class="skel" style="height:150px;margin-top:12px;border-radius:18px"></div>'.repeat(6)}</div></div>`;
    const names = ['scanner', 'auditor', 'analyst', 'brain', 'executor', 'risk'];
    let data, st;
    try { [st, ...data] = await Promise.all([api('/state'), ...names.map(n => api(`/agents/${n}/decisions`))]); cache.state = st; } catch (e) { return; }
    if (S.screen !== 'agents') return;
    const A = Object.fromEntries(st.agents.map(a => [a.name, a]));
    const status = n => { const a = A[n] || {};
      return {scanner: `${fmtInt(a.pools)} pools · ${a.waiting} waiting`, auditor: `${a.taken_apart} taken apart · ${a.rejected} rejected`, analyst: `${a.scored} scored · passes from ${a.min_score}`,
        brain: `${a.trades}/${a.max_trades} trades · free ${usd(a.free_cash)}`,
        executor: `${a.trades} trades · ${a.waiting || 0} waiting for a dip`, risk: `${a.open} open · stop -${a.stop_pct}% · trail ${a.trail_pct}%`}[n]; };
    const role = {scanner: 'Watches every new pool on Solana', auditor: 'Takes each coin apart in 8 checks', analyst: 'Scores what is left, 0 to 100', brain: 'Sizes each buy: 3% risk of cash, $2 to $50', executor: 'Waits for a -15% dip, buys, takes profit at 2x', risk: 'Stop -25%, 40% trail, dead money, pulled liquidity'};
    $('#ag-run').textContent = `${st.agents.filter(a => !a.paused).length} running`;
    const vcls = vd => /kill|reject|stop|pulled/.test(vd) ? 'r' : /pass|bought|trail|sent/.test(vd) ? 'g' : 'b';
    $('#ag').innerHTML = data.map(d => `<div class="agc" id="ag-${d.agent}"><div class="top">${tile(d.agent)}<div class="mid"><div class="nm">${cap(d.agent)}</div>
        <div class="st${d.paused ? ' off' : ''}" style="color:${AGC[d.agent] === '#ffffff' ? '#64A8FF' : AGC[d.agent]}">${d.paused ? 'paused' : esc(status(d.agent))}</div></div>
        <button class="switch ${d.paused ? '' : 'on'} ${d.locked ? 'locked' : ''}" data-agent="${d.agent}" aria-label="pause or resume"></button></div>
      ${d.rows.length ? d.rows.slice(0, 4).map(r => `<a class="dec" href="${r.verdict === 'kill' || r.verdict === 'reject' ? '#/audit/' : '#/coin/'}${esc(r.mint)}"><span class="tm">${t12(r.ts)}</span><span class="cn">${esc(coinLabel(r))}</span><span class="chip ${vcls(r.verdict)}">${esc(r.verdict)}</span><span class="rs">${esc(r.reason || '')}</span></a>`).join('')
        : `<div class="line muted" style="font-weight:500">${role[d.agent]} · nothing yet tonight</div>`}
      <div class="foot"><span class="muted">${d.today} today${d.locked ? ' · locked, a trade is open' : ''}</span><a href="#/account" data-sec="${d.agent}">Settings ›</a></div></div>`).join('');
    v.querySelectorAll('.switch').forEach(b => b.onclick = async () => {
      if (PLAN === 'B') return toast('Read-only: pause with Telegram, "pause ' + b.dataset.agent + '"');
      if (b.classList.contains('locked')) return toast('Risk is locked while a position is open');
      const on = b.classList.contains('on');
      try { await api(`/agents/${b.dataset.agent}/${on ? 'pause' : 'resume'}`, {method: 'POST'}); agents(); } catch (e) { toast(e.message); }
    });
    v.querySelectorAll('[data-sec]').forEach(a => a.onclick = () => { S.scrollTo = a.dataset.sec; });
  }

  const backBtn = (label = 'Home') => `<a class="back" href="javascript:history.length>1?history.back():location.hash='#/home'"><svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg>${label}</a>`;

  // ---- AUDITOR SCREEN
  async function audit(mint) {
    const v = $('#view');
    v.innerHTML = `<div class="slide-in"><div class="nav">${backBtn()}<span class="muted" style="font-weight:600">Auditor</span></div><div id="au"><div class="skel" style="height:300px"></div><div class="skel" style="height:300px;margin-top:12px"></div></div></div>`;
    let d; try { d = await api('/audit/' + mint); } catch (e) { return; }
    if (S.screen !== 'audit') return;
    if (!d || !d.layers || !d.layers.length) {
      $('#au').innerHTML = `<div class="emptycard" style="margin-top:20px"><b>Not taken apart yet</b>The Auditor hasn't checked this coin.</div>${d ? `<a class="buy" href="${esc(d.coin_url)}" target="_blank" rel="noopener">Open on FOMO</a>` : ''}`; return;
    }
    $('#au').innerHTML = `<div class="th">${coinIcon(d.name, mint, 48)}<div style="min-width:0"><div class="t">${esc(d.name)}</div><div class="s">${esc(d.name)} · Solana · 8 checks</div></div></div>
      <div class="discs" id="discs">${d.layers.map((l, i) => `<div class="disc" style="top:${i * 34}px;z-index:${10 - i}" id="disc${l.n}">${l.n} · ${esc(l.name)}</div>`).join('')}<div class="beam" id="beam"></div></div>
      <div id="verdict"></div><div class="list" id="lrows" style="margin-top:14px"></div>
      <div class="list" style="margin-top:14px"><div class="li"><div class="mid"><div class="t">Take apart before buying</div></div><button class="switch ${d.enabled ? 'on' : ''}" id="au-toggle"></button></div></div>
      <a class="buy" href="${esc(d.coin_url)}" target="_blank" rel="noopener">Open on FOMO</a>`;
    const beam = $('#beam'), rows = $('#lrows');
    const show = l => {
      const disc = $('#disc' + l.n); disc.classList.add(l.pass === true ? 'ok' : l.pass === false ? 'no' : 'nc');
      rows.insertAdjacentHTML('beforeend', `<div class="lrow"><span class="k">${l.n} ${esc(l.name)}</span><span class="val ${l.pass === true ? 'ok' : l.pass === false ? 'no' : 'nc'}">${l.pass === true ? '✓ ' : l.pass === false ? '✗ ' : ''}${esc(l.value)}</span></div>`);
    };
    const finish = () => {
      $('#verdict').innerHTML = d.status === 'rejected' ? `<div class="verdict no">Rejected · ${esc(d.reason)}</div><div class="muted">Grok Bot won't buy ${esc(d.name)}</div>`
        : d.status === 'cleared' ? `<div class="verdict ok">Cleared · 8/8 checks</div><div class="muted">Sent to Executor${d.sent_size ? ' · ' + usd(d.sent_size) : ''}</div>` : `<div class="verdict">taking apart…</div>`;
    };
    if (reduced()) { d.layers.forEach(show); finish(); }
    else {
      beam.style.opacity = 1; let i = 0;
      const next = () => { if (i >= d.layers.length) { beam.style.opacity = 0; return finish(); } const l = d.layers[i]; beam.style.top = (i * 34 + 15) + 'px';
        setTimeout(() => { setTimeout(() => { show(l); i++; next(); }, 150); }, 350); };
      next();
    }
    $('#au-toggle').onclick = async e => {
      const b = e.currentTarget; const on = b.classList.contains('on');
      if (PLAN === 'B') return toast('Read-only: change it with Telegram');
      if (on && !(confirm('Turn off "Take apart before buying"? Coins would reach Analyst unchecked.') && confirm('Sure? Every coin skips all 8 checks.'))) return;
      try { await api('/settings', {method: 'POST', body: {'auditor.enabled': !on}}); b.classList.toggle('on'); } catch (err) { toast(err.message); }
    };
  }

  // ---- COIN (token detail) SCREEN
  async function coin(mint) {
    const v = $('#view');
    const cached = cache['coin' + mint];
    if (!cached) v.innerHTML = `<div class="slide-in"><div class="nav">${backBtn()}</div><div class="th"><div class="skel" style="width:48px;height:48px;border-radius:24px"></div><div class="skel" style="width:160px;height:40px"></div></div>
      <div class="skel" style="height:54px;width:60%;margin-top:16px"></div><div class="skel" style="height:280px;margin-top:14px"></div><div class="skel" style="height:70px;margin-top:12px;border-radius:16px"></div></div>`;
    let d; try { d = await api('/coin/' + mint); } catch (e) { d = cached; if (!d) return; }
    if (S.screen !== 'coin' || S.arg !== mint) return;
    if (!d) { v.innerHTML = `<div class="nav">${backBtn()}</div><div class="emptycard" style="margin-top:20px"><b>No data for this coin yet</b>Prices show up once the desk has seen it trade.</div>`; return; }
    const first = !cached; cache['coin' + mint] = d;
    const sym = d.symbol || d.name || mint.slice(0, 6), nm = d.name || sym;
    const pos = d.position, open = pos && ['open', 'exiting'].includes(pos.status);
    const age = d.age_h == null ? '' : d.age_h < 1 ? Math.max(1, Math.round(d.age_h * 60)) + 'm old' : d.age_h < 48 ? Math.round(d.age_h) + 'h old' : Math.round(d.age_h / 24) + 'd old';
    const big = d.market_cap != null ? kfmt(d.market_cap) : price(d.price);
    let sinceHtml = '';
    if (pos) {
      const ref = open ? d.price : (pos.exit_price || d.price), pct = ref && pos.entry_price ? 100 * (ref / pos.entry_price - 1) : d.since_entry_pct;
      if (pct != null) sinceHtml = `<div class="since ${pct >= 0 ? 'up' : 'down'}">${pct >= 0 ? '▲' : '▼'} ${Math.abs(pct).toFixed(1)}% <span>${open ? 'since Grok Bot bought' : 'when Grok Bot sold'}</span></div>`;
    } else sinceHtml = `<div class="since"><span>price ${price(d.price)}</span></div>`;
    const myActs = ((cache.activity || {rows: []}).rows || []).filter(r => r.mint === mint);
    const buyAct = myActs.find(r => r.kind === 'bought'), exitAct = myActs.find(r => r.kind === 'sold' || r.kind === 'stopped');
    const entry = pos ? {ts: pos.opened_at, price: pos.entry_price, name: sym, verb: 'bought', amount: usd(pos.size_usd)} : null;
    let exit = null;
    if (pos && !open && pos.exit_price) {
      const pnl = pos.pnl_usd != null ? pos.pnl_usd : (exitAct ? parseFloat(actView(exitAct).right.replace(/[$,]/g, '')) : 0);
      exit = {ts: pos.closed_at || pos.exit_pushed_at || (exitAct && exitAct.ts), price: pos.exit_price, name: sym, verb: pos.exit_reason === 'stop' || pos.exit_reason === 'pulled' ? 'stop' : 'sold', amount: (pnl >= 0 ? '+' : '-') + usd(Math.abs(pnl)), loss: pnl < 0};
    }
    const mult = pos && pos.entry_price ? ((open ? d.price : pos.exit_price) || 0) / pos.entry_price : null;
    const value = pos && pos.entry_price && d.price ? pos.size_usd * (open ? d.price : pos.exit_price || d.price) / pos.entry_price : null;
    const pnl = pos ? (open ? (value != null ? value - pos.size_usd : null) : pos.pnl_usd) : null;
    const ex = d.exit;
    const tl = ex ? `${Math.floor(ex.timeout_left_s / 3600)}h ${Math.floor(ex.timeout_left_s % 3600 / 60)}m left` : '';
    const reasonTxt = {trail: 'Took profit', stop: 'Stopped', timeout: 'Timed out', pulled: 'Liquidity pulled'};
    v.innerHTML = `<div class="${first ? 'slide-in' : ''}"><div class="nav">${backBtn()}${d.mode === 'PAPER' ? '<span class="pillsm">PAPER</span>' : ''}</div>
      <div class="th">${coinIcon(sym, mint, 48)}<div style="min-width:0"><div class="t">${esc(nm)}</div><div class="s">${esc(sym)} · Solana${age ? ' · ' + age : ''}</div></div></div>
      <div class="cbig">${esc(big)}</div>${sinceHtml}
      <div class="badges">${pos ? `<span class="bdg"><span class="mav">${LOGO}</span><b>Grok Bot</b> on fomo</span>` : ''}${d.shield ? `<a class="bdg ${d.shield === '8/8' ? 'g' : 'r'}" href="#/audit/${esc(mint)}">⛨ audit ${esc(d.shield)}</a>` : ''}${d.holders ? `<span class="bdg" style="padding:0 10px">${fmtInt(d.holders)} holders</span>` : ''}</div>
      <div class="cchart"><canvas id="cdl"></canvas><div class="wait" id="cwait" hidden>Collecting price data…</div></div>
      <div class="kv"><div><div class="k">Market cap</div><div class="val">${kfmt(d.market_cap)}</div></div><div><div class="k">Liquidity</div><div class="val">${kfmt(d.liquidity)}</div></div>
        <div><div class="k">Volume 24h</div><div class="val">${kfmt(d.volume_h24)}</div></div><div><div class="k">Price</div><div class="val">${price(d.price)}</div></div></div>
      ${pos ? `<div class="scard">${tile('executor', 'sm')}<div class="mid"><div class="t">Position</div><div class="s">${usd(pos.size_usd)} in · Executor · ${esc(pos.mode)}${open ? '' : ' · closed'}</div></div>
        <div class="v"><b>${value != null ? usd(value) : 'n/a'}</b>${pnl != null ? `<span class="${pnl >= 0 ? 'up' : 'down'}">${pnl >= 0 ? '+' : '-'}${usd(Math.abs(pnl))}</span>` : ''}</div></div>` : ''}
      ${open && ex ? `<div class="scard">${tile('risk', 'sm')}<div class="mid"><div class="t">Risk · ${ex.trail_active ? 'trailing' : 'watching'}</div><div class="s">trail ${ex.trail_pct}% from top · stop -${ex.stop_pct}% · ${tl}</div></div>
        <div class="v"><span class="down" style="display:block">${price(ex.stop_price)}</span><span class="muted" style="font-weight:500">stop line</span></div></div>` : ''}
      ${pos && !open ? `<div class="scard">${tile('action', 'sm')}<div class="mid"><div class="t">${esc(reasonTxt[pos.exit_reason] || 'Closed')} · x${(mult || 0).toFixed(2)}</div><div class="s">Risk · ${t12(pos.closed_at || pos.exit_pushed_at)}</div></div></div>` : ''}
      ${!pos ? `<div class="scard">${tile('analyst', 'sm')}<div class="mid"><div class="t">Not bought by Grok Bot</div><div class="s">${d.shield ? 'Audited ' + esc(d.shield) + ' · tap the audit badge to see why' : 'Seen by Scanner'}</div></div></div>` : ''}
      <a class="buy" href="${esc(d.coin_url)}" target="_blank" rel="noopener">Open on FOMO</a>
      ${open && pos.status === 'open' && PLAN === 'A' ? `<button class="sellnow" id="sellnow">Sell now</button>` : ''}
      <div class="fine">${d.mode === 'PAPER' ? 'PAPER: sells fill at the last price.' : 'LIVE: the desk clicks Sell only when auto-click is armed; otherwise sell it on FOMO.'}</div></div>`;
    const sn = $('#sellnow'); if (sn) sn.onclick = () => sellSheet(mint, sym);
    const hasC = Charts.candles($('#cdl'), d.candles, {entry, exit, lastLabel: d.market_cap != null ? kfmt(d.market_cap) : price(d.price)});
    $('#cwait').hidden = hasC;
  }

  function sellSheet(mint, sym) {
    const sh = document.createElement('div'); sh.className = 'sheet';
    sh.innerHTML = `<div class="sheetin"><div class="t">Sell ${esc(sym)}</div><div class="seg2" id="spct">${[25, 50, 100].map(p => `<button data-p="${p}" class="${p === 100 ? 'on' : ''}">${p}%</button>`).join('')}</div>
      <button class="buy" id="sconf">Confirm sell</button><button class="morebtn" id="scancel">Cancel</button></div>`;
    document.body.appendChild(sh); let pct = 100;
    $('#spct', sh).onclick = e => { const b = e.target.closest('button'); if (!b) return; pct = +b.dataset.p; sh.querySelectorAll('#spct button').forEach(x => x.classList.toggle('on', x === b)); };
    $('#scancel', sh).onclick = () => sh.remove();
    $('#sconf', sh).onclick = async () => { try { await api('/sell/' + mint, {method: 'POST', body: {pct, confirm: true}}); toast(`Sell ${pct}% sent`); } catch (e) { toast(e.message); } sh.remove(); };
  }

  // ---- COPY PICKS (Account tab): newest list on top, 1 card per trader, then the last 7 lists
  async function picks() {
    const v = $('#view');
    v.innerHTML = `<div class="slide-in"><div class="nav">${backBtn('Account')}<span class="muted" style="font-weight:600">Copy picks</span></div><div id="pk"><div class="skel" style="height:300px"></div></div></div>`;
    let j; try { j = await api('/picks'); } catch (e) { return; }
    if (S.screen !== 'picks') return;
    const runs = j.runs || [], last = runs[0];
    const k = x => x == null ? 'n/a' : Math.abs(x) >= 1e6 ? (x / 1e6).toFixed(1) + 'M' : Math.abs(x) >= 1e3 ? (x / 1e3).toFixed(0) + 'K' : x.toFixed(0);
    const card = t => `<div class="pcard"><div class="ph"><b>#${esc(t.rank || '')} ${esc(t.handle)}</b><span class="up">7d +$${k(t.pnl_7d)}</span><span class="up">30d +$${k(t.pnl_30d)}</span></div>
      <div class="muted fs">${fmtInt(t.trades)} trades · last trade ${t.last_ts ? t12(t.last_ts) : 'n/a'} · ${esc(t.why || '')}</div>
      ${t.last_buy ? `<a class="li" href="${esc(t.last_buy.url)}" target="_blank" rel="noopener"><div class="mid"><div class="t">Last buy: ${esc(t.last_buy.symbol || (t.last_buy.mint || '').slice(0, 6))}</div><div class="s">at $${k(t.last_buy.mcap)}</div></div><span class="chev">›</span></a>` : ''}
      <div class="prow"><a class="smallbtn" href="${esc(t.profile_url)}" target="_blank" rel="noopener">Profile</a><span class="muted fs" style="margin-left:auto">Copy on desk</span><button class="switch ${j.switches[t.id] ? 'on' : ''}" data-copy="${esc(t.id)}" data-h="${esc(t.handle)}"></button></div></div>`;
    const head = `<div class="muted fs" style="margin:6px 0 12px">Every ${esc(j.every)} at ${esc(j.time)} · read only · Copy on desk is ${j.copy_enabled ? 'on' : 'off'}</div>`;
    const body = !last ? '<div class="emptycard"><b>No list yet</b>The first list comes with the copy-picks routine.</div>'
      : last.status !== 'ok' ? `<div class="emptycard"><b>Last run ${esc(last.status)} · ${t12(last.ts)}</b>${esc(last.error || '')}</div>`
      : `<div class="ttl2">Grok Bot · ${last.picks.length} traders worth copying today</div>${last.picks.map((t, i) => card({...t, rank: i + 1})).join('')}${(last.dropped || []).filter(x => /1 coin/.test(x.why)).map(x => `<div class="muted fs">Dropped ${esc(x.handle)}: ${esc(x.why)}</div>`).join('')}`;
    const hist = runs.length ? `<div class="sec"><h2>Last 7 lists</h2></div><div class="feed2">${runs.map(r => `<div class="frow"><span class="ft">${new Date(r.ts * 1000).toLocaleDateString('es-EC', {day: '2-digit', month: 'short', timeZone: TZ})}</span><span class="fa">${esc(r.status)}</span><span class="fn">${r.status === 'ok' ? esc((r.picks || []).map(t => t.handle).join(', ')) : esc((r.error || '').slice(0, 60))}</span><span class="fv"></span></div>`).join('')}</div>` : '';
    $('#pk').innerHTML = head + body + hist + `<a class="buy" href="${esc(j.signup_url)}" target="_blank" rel="noopener">New to FOMO? Sign up</a>`;
    v.querySelectorAll('[data-copy]').forEach(b => b.onclick = async () => { const on = !b.classList.contains('on');
      try { await api('/copy/' + encodeURIComponent(b.dataset.copy), {method: 'POST', body: {on, handle: b.dataset.h}}); b.classList.toggle('on', on); } catch (e) { toast(e.message); } });
  }

  // ---- ACCOUNT TAB
  async function account() {
    const v = $('#view');
    v.innerHTML = `<div class="fade-in"><div class="ttl"><h1>Account</h1></div><div id="acc"><div class="skel" style="height:86px;border-radius:18px"></div><div class="skel" style="height:300px;margin-top:14px;border-radius:16px"></div></div></div>`;
    let a, s; try { [a, s] = await Promise.all([api('/account'), api('/settings')]); } catch (e) { return; }
    if (S.screen !== 'account') return;
    const ro = PLAN === 'B';
    const groups = {}; s.settings.forEach(x => (groups[x.group] = groups[x.group] || []).push(x));
    const titles = {scanner: 'Scanner', auditor: 'Auditor', analyst: 'Analyst', social: 'Social (X)', brain: 'Brain', executor: 'Executor', risk: 'Risk', desk: 'Desk'};
    const standalone = matchMedia('(display-mode: standalone)').matches || navigator.standalone;
    const ctl = x => {
      if (x.type === 'bool') return `<button class="switch ${x.value ? 'on' : ''}" data-k="${x.key}" data-bool="1" ${ro ? 'disabled' : ''}></button>`;
      if (x.choices) return `<select data-k="${x.key}" ${ro ? 'disabled' : ''}>${x.choices.map(c => `<option ${c === x.value ? 'selected' : ''}>${c}</option>`).join('')}</select>`;
      if (x.type === 'str') return `<input type="text" data-k="${x.key}" value="${esc(x.value)}" ${ro ? 'disabled' : ''} style="width:170px">`;
      return `<input type="number" step="any" min="${x.min}" max="${x.max}" data-k="${x.key}" value="${x.value}" ${ro ? 'disabled' : ''}>`;
    };
    const chev = '<span class="chev">›</span>';
    v.querySelector('#acc').innerHTML = `
      <div class="prof"><div class="av">${LOGO}</div><div style="min-width:0"><div class="t">Grok Bot</div><div class="s">${a.fomo_handle ? '@' + esc(a.fomo_handle) + ' on FOMO · ' : ''}${esc(a.mode)}</div></div></div>
      <div class="grp"><h3>Trading mode</h3><div class="list"><div class="setrow"><div class="modeseg" id="mode-seg"><button data-m="PAPER" class="${a.mode === 'PAPER' ? 'on' : ''}">PAPER</button><button data-m="LIVE" class="${a.mode === 'LIVE' ? 'on' : ''}">LIVE</button></div>
        <div class="muted" style="font-size:13px;margin-top:8px;line-height:1.4">${a.mode === 'PAPER' ? 'Simulated money. ' : ''}${a.full_paper_nights < 1 ? 'LIVE unlocks after 1 full PAPER night.' : 'Money only moves when you tap Buy on FOMO.'}</div></div>
        <div class="setrow"><div class="lab"><span>Stack (LIVE)</span><input class="field" id="stack" type="number" step="any" value="${a.stack}" ${ro ? 'disabled' : ''}></div></div></div></div>
      <div class="grp"><h3>FOMO</h3><div class="list">${a.profile_url ? `<a class="li" href="${esc(a.profile_url)}" target="_blank" rel="noopener"><div class="mid"><div class="t">Ver mi perfil en FOMO</div><div class="s">@${esc(a.fomo_handle)}</div></div>${chev}</a>` : ''}
        <a class="li" href="#/picks"><div class="mid"><div class="t">Copy picks</div><div class="s">5 traders worth copying · every ${esc(String((s.settings.find(x => x.key === 'copy_picks.every') || {}).value || '24h'))} at ${esc(String((s.settings.find(x => x.key === 'copy_picks.time') || {}).value || '21:30'))}</div></div>${chev}</a>
        <button class="li" id="invite"><div class="mid"><div class="t">Invite a friend</div><div class="s">10% off fees for life</div></div>${chev}</button></div></div>
      <div class="grp"><h3>Notifications</h3><div class="list"><div class="li"><div class="mid"><div class="t">Telegram</div><div class="s">${esc(a.telegram)}</div></div>${ro ? '' : '<button class="smallbtn" id="testpush">Test push</button>'}</div>
        <div class="li"><div class="mid"><div class="t">Web push</div><div class="s">${a.webpush ? (standalone ? 'Alerts on this phone' : 'Add the app to your home screen first') : 'Telegram only on this hosting'}</div></div>${a.webpush && standalone ? '<button class="smallbtn" id="enpush">Enable</button>' : ''}</div></div></div>
      ${ro ? '<div class="emptycard" style="margin-top:16px">Read-only here. Change settings in Telegram, e.g. "set stop to -8%".</div>' : ''}
      ${Object.entries(groups).map(([g, xs]) => `<div class="grp" id="set-${g}"><h3>${titles[g] || g}</h3><div class="list">${xs.map(x => `<div class="setrow"><div class="lab"><span>${esc(x.label)}</span>${ctl(x)}</div>
        ${x.type !== 'bool' && !x.choices && x.type !== 'str' && x.min != null ? sliderHtml(x, ro) : ''}</div>`).join('')}</div></div>`).join('')}
      <div style="height:24px"></div>`;
    if (S.scrollTo) { const el = $('#set-' + S.scrollTo); if (el) el.scrollIntoView(); S.scrollTo = null; }
    $('#invite').onclick = async () => { const url = a.signup_url; if (navigator.share) { try { await navigator.share({url}); } catch (e) {} } else { try { await navigator.clipboard.writeText(url); } catch (e) {} toast('Link copied'); } };
    if (ro) return;
    const save = async (k, val) => { try { const r = await api('/settings', {method: 'POST', body: {[k]: val}}); if (r.errors && r.errors[k]) toast(r.errors[k]); else toast('Saved'); if (r.ticket_warning) toast(r.ticket_warning); } catch (e) { toast((e.body && e.body.errors && e.body.errors[k]) || e.message); account(); } };
    v.querySelectorAll('input[data-k],select[data-k]').forEach(i => i.onchange = () => { save(i.dataset.k, i.value); const r = v.querySelector(`[data-r="${i.dataset.k}"]`); if (r) r.value = Slider.toPos(r, +i.value); });
    v.querySelectorAll('input[data-r]').forEach(r => { const val = () => Slider.toValue(r); r.oninput = () => { v.querySelector(`[data-k="${r.dataset.r}"]`).value = val(); }; r.onchange = () => save(r.dataset.r, val()); });
    v.querySelectorAll('[data-bool]').forEach(b => b.onclick = () => { const on = !b.classList.contains('on'); b.classList.toggle('on', on); save(b.dataset.k, on); });
    $('#stack').onchange = e => save('desk.stack', e.target.value);
    $('#mode-seg').onclick = async e => {
      const m = e.target.dataset.m; if (!m || m === a.mode) return;
      let body = {mode: m};
      if (m === 'LIVE') { const t = await confirmLive(); if (t !== 'LIVE') return; body.confirm = 'LIVE'; }
      try { const r = await api('/mode', {method: 'POST', body}); if (r.ticket_warning) toast(r.ticket_warning); account(); } catch (err) { toast(err.message); }
    };
    const tp = $('#testpush'); if (tp) tp.onclick = async () => { try { const r = await api('/test_push', {method: 'POST'}); toast(r.ok ? 'Test push sent' : 'Push failed'); } catch (e) { toast(e.message); } };
    const en = $('#enpush'); if (en) en.onclick = enablePush.bind(null, a.vapid_public);
  }
  // Settings slider. Wide ranges (e.g. min liquidity $1K..$10M) use a log scale with nice round values:
  // the old linear step was (max-min)/200 = $49,995, so one touch jumped liquidity to $50,995 / $150,985 / $200,980.
  const Slider = window.DeskSlider;
  function sliderHtml(x, ro) {
    const log = Slider.isLog(x.min, x.max, x.type);
    return `<input type="range" min="0" max="${Slider.STEPS}" step="1" value="${Slider.posFor(x.min, x.max, x.type, x.value)}" data-r="${x.key}" data-min="${x.min}" data-max="${x.max}" data-t="${x.type}" ${log ? 'data-log="1"' : ''} ${ro ? 'disabled' : ''}>`;
  }
  // LIVE confirm: same rule as before (you must type LIVE), in a bottom sheet instead of a browser prompt.
  function confirmLive() {
    return new Promise(res => {
      const bg = document.createElement('div'); bg.className = 'sheetbg';
      bg.innerHTML = `<div class="sheet"><h3>Switch to LIVE?</h3><p>LIVE uses real money. Grok Bot still never buys on its own: you confirm every trade in FOMO. Type <b style="color:#fff">LIVE</b> to confirm.</p>
        <input id="live-in" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="LIVE"><div class="acts"><button id="live-no">Cancel</button><button class="go" id="live-go" disabled>Go LIVE</button></div></div>`;
      document.body.appendChild(bg);
      const inp = $('#live-in', bg), go = $('#live-go', bg);
      const done = v => { bg.remove(); res(v); };
      inp.oninput = () => { go.disabled = inp.value.trim() !== 'LIVE'; };
      go.onclick = () => done(inp.value.trim()); $('#live-no', bg).onclick = () => done(null);
      bg.onclick = e => { if (e.target === bg) done(null); };
      setTimeout(() => inp.focus(), 50);
    });
  }
  async function enablePush(vapid) {
    try {
      const reg = await navigator.serviceWorker.register('sw.js'); const perm = await Notification.requestPermission(); if (perm !== 'granted') return toast('Notifications not allowed');
      const key = Uint8Array.from(atob(vapid.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - vapid.length % 4) % 4)), c => c.charCodeAt(0));
      const sub = await reg.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: key});
      await api('/push', {method: 'POST', body: sub.toJSON()}); toast('Notifications on');
    } catch (e) { toast('Could not enable: ' + e.message); }
  }

  // ---- live updates: SSE (best-effort; tunnels often buffer it) + 2.5s ETag poll that works through cloudflared
  async function sse() {
    if (PLAN !== 'A' || !TOKEN) return;
    while (true) {
      try {
        const r = await fetch('api/stream', {headers: {'Authorization': 'Bearer ' + TOKEN, 'Accept': 'text/event-stream'}, cache: 'no-store'});
        if (r.status === 401) return showAuth();
        ok(); const rd = r.body.getReader(), dec = new TextDecoder(); let buf = '';
        while (true) {
          const {value, done} = await rd.read(); if (done) break; buf += dec.decode(value, {stream: true});
          let i; while ((i = buf.indexOf('\n\n')) >= 0) {
            const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
            const ev = (chunk.match(/^event: (.*)$/m) || [])[1], data = (chunk.match(/^data: (.*)$/m) || [])[1];
            if (ev) onEvent(ev, data);
          }
        }
      } catch (e) { fail(); }
      await new Promise(r => setTimeout(r, 3000));
    }
  }
  let pend = null;
  function onEvent(ev, data) {
    if (ev === 'activity' && data) { try { const row = JSON.parse(data); if (!seenAct.has(row.id)) { seenAct.add(row.id); if (isTrade(row)) banner(row); } } catch (e) {} }
    if (ev === 'fomo_account' && data) { try { const j = JSON.parse(data); api('/fomo_account').then(setFomo).catch(() => {}); } catch (e) {} return; }
    if (S.screen === 'audit' && ev === 'audit_layer') return;
    clearTimeout(pend); pend = setTimeout(refresh, 400);
  }
  function refresh() { if (S.screen === 'home') home(); else if (S.screen === 'coin') coin(S.arg); else if (S.screen === 'activity') activity(); }
  let pollEtag = null, polling = false;
  async function pollLive() {
    if (polling || failing) return;
    if (PLAN === 'B') {
      refresh();
      if (S.screen !== 'home' && S.screen !== 'activity' && DP) api('/activity').then(j => { cache.activity = j; noteActivity(j.rows, true); }).catch(() => {});
      return;
    }
    if (!TOKEN) return;
    polling = true;
    try {
      const h = {'Authorization': 'Bearer ' + TOKEN};
      if (pollEtag) h['If-None-Match'] = pollEtag;
      const r = await fetch('api/rev', {headers: h, cache: 'no-store'});
      if (r.status === 401) { showAuth(); return; }
      if (r.status === 304) { ok(); return; }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      pollEtag = r.headers.get('ETag') || pollEtag;
      ok();
      refresh();
      if (S.screen !== 'home' && S.screen !== 'activity') api('/activity').then(j => { cache.activity = j; noteActivity(j.rows, true); }).catch(() => {});
    } catch (e) { fail(); }
    finally { polling = false; }
  }
  setInterval(pollLive, 2500);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) pollLive(); });
  setInterval(() => { const c = $('#clock'); if (c) c.textContent = new Date().toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit'}); }, 20000);
  let rz; window.addEventListener('resize', () => { clearTimeout(rz); rz = setTimeout(() => { if (S.screen === 'home') renderHome(); }, 150); });
  if ('serviceWorker' in navigator) navigator.serviceWorker.getRegistration().then(r => r && r.update()).catch(() => {});
  window.__desk = {banner, confetti};  // used by the screenshot script to show a banner
  route(); sse();
})();
