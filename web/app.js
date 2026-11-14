// Grok Bot desk app. Plain JS, no framework, no build step.
(function () {
  'use strict';
  const $ = (s, el = document) => el.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const reduced = () => window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const usd = (v, d = 2) => v == null ? 'n/a' : (v < 0 ? '-' : '') + '$' + Math.abs(v).toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d});
  const kfmt = v => v == null ? 'n/a' : v >= 1e6 ? '$' + (v / 1e6).toFixed(1) + 'M' : v >= 1e3 ? '$' + (v / 1e3).toFixed(1) + 'K' : '$' + v.toFixed(0);
  const price = v => v == null ? 'n/a' : v >= 1 ? '$' + v.toFixed(4) : '$' + Number(v.toPrecision(4)).toString();
  const hhmm = ts => ts ? new Date(ts * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', hour12: false}) : '';

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
    e.textContent = `Desk offline · retrying in ${n}s · last update ${lastOk ? new Date(lastOk).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) : 'never'}`;
  }
  setInterval(renderErr, 1000);
  function showAuth() {
    $('#view').innerHTML = `<div class="nav"><div class="title">Grok Bot</div></div><div class="empty">Open the app once with the private link Grok Bot gave you (it ends in #t=… or #d=…).</div>`;
  }
  function toast(t) { const d = document.createElement('div'); d.className = 'toast'; d.textContent = t; document.body.appendChild(d); setTimeout(() => d.remove(), 2200); }

  // ---- odometer: each changed digit rolls 600ms ease-out, 30ms stagger right to left
  function odometer(el, text) {
    const prev = el._txt || ''; el._txt = text;
    if (reduced() || prev.length !== text.length) { el.innerHTML = [...text].map(ch => /\d/.test(ch) ? `<span class="odo"><span style="transform:translateY(-${+ch * 1.05}em)">${[...'0123456789'].map(d => `<b>${d}</b>`).join('')}</span></span>` : `<span>${esc(ch)}</span>`).join(''); return; }
    const spans = [...el.children]; let k = 0;
    for (let i = text.length - 1; i >= 0; i--) {
      const ch = text[i], sp = spans[i]; if (!sp) continue;
      if (/\d/.test(ch) && sp.firstElementChild && ch !== prev[i]) { const inner = sp.firstElementChild; inner.style.transitionDelay = (k++ * 30) + 'ms'; inner.style.transform = `translateY(-${+ch * 1.05}em)`; }
      else if (!/\d/.test(ch)) sp.textContent = ch;
    }
  }

  // ---- router
  let S = {state: null, range: 'LIVE', screen: null};
  const routes = {home, agents, activity, account, coin, audit};
  async function route() {
    if (!TOKEN && !DP) return showAuth();
    const [, name = 'home', arg] = (location.hash.match(/^#\/(\w+)(?:\/(.+))?/) || []);
    S.screen = name; S.arg = arg;
    document.querySelectorAll('.tabs a').forEach(a => a.classList.toggle('on', a.dataset.tab === name));
    $('#tabs').hidden = false;
    window.scrollTo(0, 0);
    await (routes[name] || home)(arg);
  }
  window.addEventListener('hashchange', route);

  // ---- HOME
  function homeSkeleton() {
    return `<div class="nav"><div class="skel" style="width:32px;height:32px;border-radius:16px"></div><div class="title"></div></div>
      <div class="skel" style="height:70px;width:70%;margin-top:8px"></div><div class="skel" style="height:220px;margin:14px 0"></div>
      <div class="skel" style="height:44px"></div><div class="skel agent-card" style="margin-top:20px;border-radius:42px"></div>`;
  }
  async function home() {
    const v = $('#view');
    if (!cache.state) v.innerHTML = homeSkeleton();
    try { cache.state = await api('/state'); } catch (e) { if (!cache.state) { v.innerHTML = homeSkeleton(); return; } }
    try { cache['chart' + S.range] = await api('/chart?range=' + S.range); } catch (e) {}
    try { cache.activity = await api('/activity'); } catch (e) {}
    if (S.screen !== 'home') return;
    renderHome();
  }
  function renderHome() {
    const st = cache.state, v = $('#view'); if (!st) return;
    if (!$('#home-root')) {
      v.innerHTML = `<div id="home-root">
      <div class="nav"><a class="icon-btn" href="#/account"><div class="avatar">G</div></a><a class="title" href="#/agents">Grok Bot ›</a>
        <button class="icon-btn" id="btn-search" aria-label="Search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg></button>
        <button class="icon-btn" id="btn-bell" aria-label="Pushes"><svg viewBox="0 0 24 24"><path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 21h4"/></svg><i class="dot" id="bell-dot" hidden></i></button></div>
      <div id="search-box" hidden><input class="search" id="search" placeholder="Name, symbol or mint"><div id="search-res"></div></div>
      <div class="balance-row"><div class="balance num" id="bal"></div><span class="pill paper" id="paper">PAPER</span></div>
      <div class="sub"><span id="today"></span><span class="pill mult" id="mult"></span></div>
      <div class="chart-wrap"><canvas id="line"></canvas><div class="empty-chart" id="chart-empty" hidden>Waiting for the first trade</div></div>
      <div class="ranges" id="ranges">${['LIVE', '1H', '4H', '1D', '1W', 'ALL'].map(r => `<button data-r="${r}">${r}</button>`).join('')}</div>
      <div class="section"><h2 id="agents-h">Agents · 5 running</h2></div>
      <div class="carousel" id="cards"></div>
      <div class="section"><h2>Activity</h2><a href="#/activity">See all</a></div>
      <div id="act5"></div></div>`;
      $('#ranges').onclick = e => { const r = e.target.dataset.r; if (!r) return; S.range = r; api('/chart?range=' + r).then(j => { cache['chart' + r] = j; renderHome(); }).catch(() => {}); };
      $('#btn-search').onclick = () => { const b = $('#search-box'); b.hidden = !b.hidden; if (!b.hidden) $('#search').focus(); };
      $('#search').oninput = searchCoins;
      $('#btn-bell').onclick = () => { if (PLAN === 'A') api('/pushes/read', {method: 'POST'}).catch(() => {}); $('#bell-dot').hidden = true; location.hash = '#/activity'; };
    }
    odometer($('#bal'), usd(st.balance));
    $('#paper').hidden = st.mode !== 'PAPER';
    const up = st.today_pct >= 0; $('#today').className = up ? 'up' : 'down'; $('#today').textContent = (up ? '+' : '') + st.today_pct.toFixed(2) + '% today';
    $('#mult').textContent = st.multiplier.toFixed(2) + '×';
    $('#bell-dot').hidden = !st.unread;
    const running = st.agents.filter(a => !a.paused).length; $('#agents-h').textContent = `Agents · ${running} running`;
    document.querySelectorAll('#ranges button').forEach(b => b.classList.toggle('on', b.dataset.r === S.range));
    const ch = cache['chart' + S.range] || {points: [], marks: []};
    const hasTrade = (ch.marks || []).length > 0 || (cache.activity && cache.activity.rows.some(r => r.kind !== 'rejected'));
    $('#chart-empty').hidden = hasTrade;
    Charts.line($('#line'), hasTrade ? ch : {points: [], marks: [], start_value: ch.start_value});
    $('#cards').innerHTML = st.agents.map(agentCard).join('');
    st.agents.forEach(a => { if (a.name === 'analyst') { const cv = $('#ring'); if (cv) Charts.ring(cv, a.score, a.min_score); } });
    animateExecutor(st.agents.find(a => a.name === 'executor'));
    $('#act5').innerHTML = actRows((cache.activity || {rows: []}).rows.slice(0, 5));
  }
  function radius() { const w = Math.min(window.innerWidth - 32, 504); return 42 * w / 504; }
  function agentCard(a) {
    const r = radius(), dot = `<span class="sdot ${a.paused ? 'off' : ''}"></span>`;
    const box = (inner) => `<a class="card agent-card" href="#/agents" style="border-radius:${r}px">${inner}</a>`;
    if (a.name === 'scanner') {
      const feed = a.feed.length ? a.feed.map(f => f.verdict === 'kill'
        ? `<div class="r kill"><span class="n">${esc(f.symbol || f.name || f.mint.slice(0, 6))}</span><span class="why">${esc(f.reason)}</span></div>`
        : `<div class="r"><span class="n">${esc(f.name || f.symbol)} · liq ${kfmt(f.liquidity_usd)}</span><span style="color:var(--cyan)">→ auditor</span></div>`).join('')
        : `<div class="muted">Listening for graduations</div>`;
      return box(`<div class="head" style="color:#64d2ff">${dot}Scanner</div><div class="big num">${a.pools} pools</div><div class="muted">${a.waiting} in the waiting room</div><div class="feed">${feed}</div>`);
    }
    if (a.name === 'auditor') {
      const strips = a.strips.map(s => `<i class="${s === true ? 'ok' : s === false ? 'no' : ''}"></i>`).join('');
      const line = a.running ? 'taking apart...' : (a.result || 'No coin taken apart yet');
      return box(`<div class="head">${dot}Auditor</div><div class="big num">${a.taken_apart} taken apart</div><div class="strips">${strips}</div>
        <div style="margin-top:14px;font-weight:600">${esc(a.name_coin ? a.name_coin + ' · ' : '')}${esc(line)}</div><div class="muted" style="margin-top:auto">${a.rejected} rejected</div>`);
    }
    if (a.name === 'analyst') return box(`<div class="head" style="color:#ffd60a">${dot}Analyst${a.mode === 'rules' ? ' (rules)' : ''}</div><div class="big">Scoring</div><canvas class="ring" id="ring"></canvas><div class="muted" style="margin-top:auto">${a.scored} scored · green from ${a.min_score}</div>`);
    if (a.name === 'executor') {
      const fresh = a.state_ts && (Date.now() / 1000 - a.state_ts) < 30;
      return box(`<div class="head" style="color:#00d35a">${dot}Executor</div><div class="big num">${a.trades} trades</div>
        <div class="muted">${a.size != null ? usd(a.size) + ' · ' + a.stack_pct + '% of stack' : a.stack_pct + '% of stack'}</div>
        <div class="bar"><i id="exbar" style="width:${a.state === 'filled' ? 100 : 0}%"></i></div><div id="exlabel" style="margin-top:8px;font-weight:600">${a.state === 'filled' && fresh ? '✓ Filled' : a.state === 'executing' ? 'Executing... 0%' : (a.trades ? '✓ Filled' : 'Waiting for a cleared coin')}</div>`);
    }
    return box(`<div class="head" style="color:#ff6b9a">${dot}Risk</div><div class="big">${a.open ? 'Guarding' : (a.last_exit || 'Guarding')}</div><div class="muted">${a.open} open</div>
      <div style="display:flex;gap:8px;margin-top:auto"><span class="pill mono red">stop -${a.stop_pct}%</span><span class="pill mono green">trail ${a.trail_pct}%</span></div>`);
  }
  function animateExecutor(a) {
    if (!a || a.state !== 'executing') return; const bar = $('#exbar'), lab = $('#exlabel'); if (!bar) return;
    const t0 = performance.now();
    const step = now => { const k = Math.min(1, (now - t0) / 1200); if (lab) lab.textContent = k < 1 ? `Executing... ${Math.round(k * 100)}%` : '✓ Filled'; bar.style.width = (k * 100) + '%'; if (k < 1) requestAnimationFrame(step); };
    if (reduced()) { bar.style.width = '100%'; lab.textContent = '✓ Filled'; } else requestAnimationFrame(step);
  }
  async function searchCoins() {
    const q = $('#search').value.trim().toLowerCase(); const out = $('#search-res'); if (!q) { out.innerHTML = ''; return; }
    const seen = new Map();
    ((cache.state || {}).agents || []).find(a => a.name === 'scanner')?.feed.forEach(f => seen.set(f.mint, f));
    ((cache.activity || {}).rows || []).forEach(r => r.mint && !seen.has(r.mint) && seen.set(r.mint, {mint: r.mint, name: r.title.split(' ').slice(1).join(' ')}));
    const hits = [...seen.values()].filter(c => [c.name, c.symbol, c.mint].some(x => x && x.toLowerCase().includes(q)));
    if (q.length >= 32 && !hits.length) hits.push({mint: $('#search').value.trim(), name: 'Open mint'});
    out.innerHTML = `<div class="rows">${hits.slice(0, 6).map(c => `<a class="row" href="#/coin/${esc(c.mint)}"><div class="mid"><div class="t">${esc(c.symbol || c.name)}</div><div class="s">${esc(c.mint)}</div></div></a>`).join('') || '<div class="empty">No match</div>'}</div>`;
  }

  // ---- ACTIVITY
  function actRows(rows) {
    if (!rows.length) return `<div class="rows"><div class="empty">Nothing yet tonight</div></div>`;
    return `<div class="rows">${rows.map(r => {
      const href = r.kind === 'rejected' ? `#/audit/${r.mint}` : `#/coin/${r.mint}`;
      const col = r.kind === 'bought' ? 'var(--blue)' : r.kind === 'sold' ? (String(r.value).startsWith('+') ? 'var(--green)' : 'var(--red)') : r.kind === 'stopped' ? 'var(--red)' : 'var(--sec)';
      const ic = {bought: '↓', sold: '↑', stopped: '!', rejected: '×'}[r.kind] || '·';
      return `<a class="row" href="${href}"><div class="ic" style="color:${col}">${ic}</div><div class="mid"><div class="t">${esc(r.title)}</div><div class="s">${esc(r.subtitle)}</div></div><div class="v" style="color:${col}">${esc(r.value)}</div></a>`;
    }).join('')}</div>`;
  }
  async function activity() {
    const v = $('#view');
    v.innerHTML = `<div class="nav"><div class="title" style="font-size:28px;font-weight:700">Activity</div></div><div id="acts">${cache.activity ? actRows(cache.activity.rows) : '<div class="skel" style="height:360px"></div>'}</div><div id="more"></div>`;
    try { cache.activity = await api('/activity'); } catch (e) { return; }
    if (S.screen !== 'activity') return;
    $('#acts').innerHTML = actRows(cache.activity.rows);
    let next = cache.activity.next;
    const more = () => { if (!next) { $('#more').innerHTML = ''; return; } $('#more').innerHTML = `<button class="btn sec" id="load-more">Load more</button>`;
      $('#load-more').onclick = async () => { const j = await api('/activity?before=' + next); next = j.next; $('#acts').insertAdjacentHTML('beforeend', actRows(j.rows)); more(); }; };
    more();
  }

  // ---- AGENTS TAB
  async function agents() {
    const v = $('#view');
    v.innerHTML = `<div class="nav"><div class="title" style="font-size:28px;font-weight:700">Agents</div></div><div id="ag">${'<div class="skel" style="height:180px;margin-bottom:12px"></div>'.repeat(5)}</div>`;
    const names = ['scanner', 'auditor', 'analyst', 'executor', 'risk'], colors = {scanner: '#64d2ff', auditor: '#fff', analyst: '#ffd60a', executor: '#00d35a', risk: '#ff6b9a'};
    let data;
    try { data = await Promise.all(names.map(n => api(`/agents/${n}/decisions`))); } catch (e) { return; }
    if (S.screen !== 'agents') return;
    $('#ag').innerHTML = data.map(d => `<div class="agent-full" id="ag-${d.agent}"><div class="top"><span class="sdot ${d.paused ? 'off' : ''}"></span>
      <span class="nm" style="color:${colors[d.agent]}">${d.agent[0].toUpperCase() + d.agent.slice(1)}</span><span class="muted" style="color:var(--sec)">${d.today} today</span>
      <button class="switch ${d.paused ? '' : 'on'} ${d.locked ? 'locked' : ''}" data-agent="${d.agent}" aria-label="pause or resume" style="margin-left:10px"></button></div>
      <div class="muted" style="color:var(--sec);font-size:13px;margin:2px 0 8px">${d.paused ? 'paused' : 'running'}${d.locked ? ' · locked while a position is open' : ''}</div>
      ${d.rows.length ? d.rows.map(r => `<div class="dec"><span class="tm">${hhmm(r.ts)}</span><a class="cn" href="${esc(r.coin_url)}" target="_blank" rel="noopener">${esc(r.symbol || r.name || (r.mint || '').slice(0, 6))}</a><span class="vd">${esc(r.verdict)}</span><span class="rs">${esc(r.reason)}</span></div>`).join('') : `<div class="empty" style="padding:12px">${d.agent === 'scanner' ? 'Listening for graduations' : d.agent === 'auditor' ? 'No coin taken apart yet' : 'Nothing yet tonight'}</div>`}
      <a href="#/account" data-sec="${d.agent}" class="section" style="margin:6px 0 0;color:var(--blue);font-size:15px">Settings ›</a></div>`).join('');
    v.querySelectorAll('.switch').forEach(b => b.onclick = async () => {
      if (PLAN === 'B') return toast('Plan B: pause/resume with Telegram, e.g. "pause ' + b.dataset.agent + '"');
      if (b.classList.contains('locked')) return toast('Risk is locked while a position is open');
      const on = b.classList.contains('on');
      try { await api(`/agents/${b.dataset.agent}/${on ? 'pause' : 'resume'}`, {method: 'POST'}); agents(); } catch (e) { toast(e.message); }
    });
    v.querySelectorAll('[data-sec]').forEach(a => a.onclick = () => { S.scrollTo = a.dataset.sec; });
  }

  // ---- AUDITOR SCREEN
  async function audit(mint) {
    const v = $('#view');
    v.innerHTML = `<div class="nav"><a class="icon-btn" href="javascript:history.back()"><svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg></a><div class="title">Auditor</div></div><div id="au"><div class="skel" style="height:300px"></div><div class="skel" style="height:300px;margin-top:12px"></div></div>`;
    let d; try { d = await api('/audit/' + mint); } catch (e) { return; }
    if (S.screen !== 'audit') return;
    if (!d || !d.layers || !d.layers.length) {
      $('#au').innerHTML = `<div class="empty">No coin taken apart yet</div>${d ? `<a class="btn" href="${esc(d.coin_url)}" target="_blank" rel="noopener">Open on FOMO</a>` : ''}`; return;
    }
    $('#au').innerHTML = `<div style="font-size:28px;font-weight:700">${esc(d.name)}</div>
      <div class="discs" id="discs">${d.layers.map((l, i) => `<div class="disc" style="top:${i * 34}px;z-index:${10 - i}" id="disc${l.n}">${l.n} · ${esc(l.name)}</div>`).join('')}<div class="beam" id="beam"></div></div>
      <div id="verdict"></div><div id="lrows" style="margin-top:12px"></div>
      <div class="setrow" style="padding:14px 0;border-top:.5px solid var(--sep);display:flex;justify-content:space-between;align-items:center"><span>Take apart before buying</span><button class="switch ${d.enabled ? 'on' : ''}" id="au-toggle"></button></div>
      <a class="btn" href="${esc(d.coin_url)}" target="_blank" rel="noopener">Open on FOMO</a>`;
    // beam: 350ms per layer top to bottom, then 150ms to green or red. Only results the server sent.
    const beam = $('#beam'), rows = $('#lrows');
    const show = l => {
      const disc = $('#disc' + l.n); disc.classList.add(l.pass === true ? 'ok' : l.pass === false ? 'no' : 'nc');
      rows.insertAdjacentHTML('beforeend', `<div class="lrow"><span class="k">${l.n} ${esc(l.name)}</span><span class="val ${l.pass === true ? 'ok' : l.pass === false ? 'no' : 'nc'}">${l.pass === true ? '✓ ' : l.pass === false ? '✗ ' : ''}${esc(l.value)}</span></div>`);
    };
    const finish = () => {
      $('#verdict').innerHTML = d.status === 'rejected' ? `<div class="verdict no">Rejected · ${esc(d.reason)}</div><div class="muted" style="color:var(--sec)">Grok Bot won't buy ${esc(d.name)}</div>`
        : d.status === 'cleared' ? `<div class="verdict ok">Cleared · 8/8 parts</div><div class="muted" style="color:var(--sec)">Sent to Executor${d.sent_size ? ' · ' + usd(d.sent_size) : ''}</div>` : `<div class="verdict">taking apart...</div>`;
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
      if (PLAN === 'B') return toast('Plan B: change it with Telegram, e.g. "set enabled to false"');
      if (on && !(confirm('Turn off "Take apart before buying"? Coins would reach Analyst unchecked.') && confirm('Sure? Every coin skips all 8 layers.'))) return;
      try { await api('/settings', {method: 'POST', body: {'auditor.enabled': !on}}); b.classList.toggle('on'); } catch (err) { toast(err.message); }
    };
  }

  // ---- COIN SCREEN
  async function coin(mint) {
    const v = $('#view');
    const cached = cache['coin' + mint];
    if (!cached) v.innerHTML = `<div class="nav"><a class="icon-btn" href="javascript:history.back()"><svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg></a><div class="title"></div></div><div class="skel" style="height:90px"></div><div class="skel" style="height:240px;margin-top:12px"></div><div class="skel" style="height:140px;margin-top:12px"></div>`;
    let d; try { d = await api('/coin/' + mint); } catch (e) { d = cached; if (!d) return; }
    if (!d) { v.innerHTML = `<div class="nav"><a class="icon-btn" href="javascript:history.back()"><svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg></a><div class="title">Coin</div></div><div class="empty">No data for this coin yet</div>`; return; }
    cache['coin' + mint] = d;
    if (S.screen !== 'coin') return;
    const pos = d.position && ['open', 'exiting'].includes(d.position.status) ? d.position : null;
    const age = d.age_h == null ? '' : d.age_h < 1 ? Math.round(d.age_h * 60) + 'm old' : Math.round(d.age_h) + 'h old';
    const sinc = d.since_entry_pct; const up = (sinc || 0) >= 0;
    const ex = d.exit;
    v.innerHTML = `<div class="nav"><a class="icon-btn" href="javascript:history.back()"><svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg></a>
      <div class="title">${esc(d.name || d.symbol || mint.slice(0, 6))}</div>${d.mode === 'PAPER' ? '<span class="pill paper">PAPER</span>' : ''}</div>
      <div class="sub" style="margin-top:0">${esc(d.symbol || '')} · Solana${age ? ' · ' + age : ''} ${d.shield ? `<a class="chip" href="#/audit/${esc(mint)}">⛨ ${d.shield}</a>` : ''}</div>
      <div class="balance num" style="font-size:44px;margin-top:8px">${price(d.price)}</div>
      ${pos && sinc != null ? `<div class="sub ${up ? 'up' : 'down'}">${up ? '▲' : '▼'} ${Math.abs(sinc).toFixed(2)}% since entry</div>` : ''}
      <div class="chart-wrap" style="height:260px"><canvas id="cdl"></canvas></div>
      <div class="stats"><div class="stat"><div class="k">Market cap</div><div class="val">${kfmt(d.market_cap)}</div></div><div class="stat"><div class="k">Liquidity</div><div class="val">${kfmt(d.liquidity)}</div></div>
      <div class="stat"><div class="k">24h volume</div><div class="val">${kfmt(d.volume_h24)}</div></div><div class="stat"><div class="k">Holders</div><div class="val">${d.holders == null ? 'n/a' : d.holders.toLocaleString()}</div></div></div>
      ${pos ? `<div class="section"><h2>Your position</h2></div><div class="rows"><div class="row"><div class="mid"><div class="t">${usd(pos.size_usd)} in · Executor</div><div class="s">entry ${price(pos.entry_price)} · ${pos.mode}</div></div></div></div>
      <div class="section"><h2>Exit</h2></div><div class="rows">
      <div class="row"><div class="mid"><div class="t">Stop line</div><div class="s">-${ex.stop_pct}%</div></div><div class="v down">${price(ex.stop_price)}</div></div>
      <div class="row"><div class="mid"><div class="t">Trail line</div><div class="s">${ex.trail_active ? ex.trail_pct + '% off the top' : 'starts at ' + price(ex.trail_start_price)}</div></div><div class="v up">${ex.trail_line ? price(ex.trail_line) : 'off'}</div></div>
      <div class="row"><div class="mid"><div class="t">Time left to timeout</div></div><div class="v">${Math.floor(ex.timeout_left_s / 3600)}h ${Math.floor(ex.timeout_left_s % 3600 / 60)}m</div></div></div>` : ''}
      <a class="btn" href="${esc(d.coin_url)}" target="_blank" rel="noopener">${pos ? 'Sell on FOMO' : 'Buy on FOMO'}</a>`;
    Charts.candles($('#cdl'), d.candles, ex ? ex.exit_line : null);
  }

  // ---- ACCOUNT TAB
  async function account() {
    const v = $('#view');
    v.innerHTML = `<div class="nav"><div class="title" style="font-size:28px;font-weight:700">Account</div></div><div id="acc"><div class="skel" style="height:120px"></div><div class="skel" style="height:300px;margin-top:12px"></div></div>`;
    let a, s; try { [a, s] = await Promise.all([api('/account'), api('/settings')]); } catch (e) { return; }
    if (S.screen !== 'account') return;
    const ro = PLAN === 'B';
    const groups = {}; s.settings.forEach(x => (groups[x.group] = groups[x.group] || []).push(x));
    const titles = {scanner: 'Scanner', auditor: 'Auditor', analyst: 'Analyst', executor: 'Executor', risk: 'Risk', desk: 'Desk'};
    const standalone = matchMedia('(display-mode: standalone)').matches || navigator.standalone;
    const ctl = x => {
      if (x.type === 'bool') return `<button class="switch ${x.value ? 'on' : ''}" data-k="${x.key}" data-bool="1" ${ro ? 'disabled' : ''}></button>`;
      if (x.choices) return `<select data-k="${x.key}" ${ro ? 'disabled' : ''}>${x.choices.map(c => `<option ${c === x.value ? 'selected' : ''}>${c}</option>`).join('')}</select>`;
      if (x.type === 'str') return `<input type="text" data-k="${x.key}" value="${esc(x.value)}" ${ro ? 'disabled' : ''} style="width:170px">`;
      return `<input type="number" step="any" min="${x.min}" max="${x.max}" data-k="${x.key}" value="${x.value}" ${ro ? 'disabled' : ''}>`;
    };
    v.querySelector('#acc').innerHTML = `
      <div class="rows"><div class="row" style="display:block"><div class="seg" id="mode-seg"><button data-m="PAPER" class="${a.mode === 'PAPER' ? 'on' : ''}">PAPER</button><button data-m="LIVE" class="${a.mode === 'LIVE' ? 'on' : ''}">LIVE</button></div>
        <div class="s" style="margin-top:8px">${a.full_paper_nights < 1 ? 'LIVE unlocks after 1 full PAPER night.' : 'Money only moves when you tap Buy on FOMO.'}</div></div>
        <div class="row"><div class="mid"><div class="t">Stack (LIVE)</div></div><input class="field" id="stack" type="number" step="any" value="${a.stack}" ${ro ? 'disabled' : ''}></div></div>
      <div class="section"><h2>FOMO</h2></div>
      <div class="rows">${a.profile_url ? `<a class="row" href="${esc(a.profile_url)}" target="_blank" rel="noopener"><div class="mid"><div class="t">Your FOMO profile</div><div class="s">@${esc(a.fomo_handle)}</div></div><div class="v" style="color:var(--ter)">›</div></a>` : ''}
        <button class="row" id="invite" style="width:100%;text-align:left"><div class="mid"><div class="t">Invite a friend</div><div class="s">10% off fees for life</div></div><div class="v" style="color:var(--ter)">›</div></button></div>
      <div class="section"><h2>Notifications</h2></div>
      <div class="rows"><div class="row"><div class="mid"><div class="t">Telegram</div><div class="s">${esc(a.telegram)}</div></div>${ro ? '' : '<button class="pill green" id="testpush" style="height:36px">Send test push</button>'}</div>
        <div class="row"><div class="mid"><div class="t">Web push</div><div class="s">${a.webpush ? (standalone ? '' : 'Add the app to your home screen first') : 'Not available on this hosting (plan B): Telegram only'}</div></div>${a.webpush && standalone ? '<button class="pill green" id="enpush" style="height:36px">Enable notifications</button>' : ''}</div></div>
      ${ro ? '<div class="empty" style="padding:16px 0 0">Plan B: settings are read-only here. Change them in Telegram, e.g. "set stop to -8%".</div>' : ''}
      ${Object.entries(groups).map(([g, xs]) => `<div class="setgroup" id="set-${g}"><h3>${titles[g] || g}</h3><div class="rows">${xs.map(x => `<div class="setrow"><div class="lab"><span>${esc(x.label)}</span>${ctl(x)}</div>
        ${x.type !== 'bool' && !x.choices && x.type !== 'str' && x.min != null ? `<input type="range" min="${x.min}" max="${x.max}" step="${x.type === 'int' ? 1 : (x.max - x.min) / 200}" value="${x.value}" data-r="${x.key}" ${ro ? 'disabled' : ''}>` : ''}</div>`).join('')}</div></div>`).join('')}
      <div style="height:20px"></div>`;
    if (S.scrollTo) { const el = $('#set-' + S.scrollTo); if (el) el.scrollIntoView(); S.scrollTo = null; }
    $('#invite').onclick = async () => { const url = a.signup_url; if (navigator.share) { try { await navigator.share({url}); } catch (e) {} } else { try { await navigator.clipboard.writeText(url); } catch (e) {} toast('Link copied'); } };
    if (ro) return;
    const save = async (k, val) => { try { const r = await api('/settings', {method: 'POST', body: {[k]: val}}); if (r.errors && r.errors[k]) toast(r.errors[k]); else toast('Saved'); if (r.ticket_warning) toast(r.ticket_warning); } catch (e) { toast((e.body && e.body.errors && e.body.errors[k]) || e.message); account(); } };
    v.querySelectorAll('input[data-k],select[data-k]').forEach(i => i.onchange = () => { save(i.dataset.k, i.value); const r = v.querySelector(`[data-r="${i.dataset.k}"]`); if (r) r.value = i.value; });
    v.querySelectorAll('input[data-r]').forEach(r => { r.oninput = () => { v.querySelector(`[data-k="${r.dataset.r}"]`).value = +(+r.value).toPrecision(6); }; r.onchange = () => save(r.dataset.r, r.value); });
    v.querySelectorAll('[data-bool]').forEach(b => b.onclick = () => { const on = !b.classList.contains('on'); b.classList.toggle('on', on); save(b.dataset.k, on); });
    $('#stack').onchange = e => save('desk.stack', e.target.value);
    $('#mode-seg').onclick = async e => {
      const m = e.target.dataset.m; if (!m || m === a.mode) return;
      let body = {mode: m}; if (m === 'LIVE') { const t = prompt('Type LIVE to confirm'); if (t !== 'LIVE') return; body.confirm = 'LIVE'; }
      try { const r = await api('/mode', {method: 'POST', body}); if (r.ticket_warning) toast(r.ticket_warning); account(); } catch (err) { toast(err.message); }
    };
    const tp = $('#testpush'); if (tp) tp.onclick = async () => { try { const r = await api('/test_push', {method: 'POST'}); toast(r.ok ? 'Test push sent' : 'Push failed'); } catch (e) { toast(e.message); } };
    const en = $('#enpush'); if (en) en.onclick = enablePush.bind(null, a.vapid_public);
  }
  async function enablePush(vapid) {
    try {
      const reg = await navigator.serviceWorker.register('sw.js'); const perm = await Notification.requestPermission(); if (perm !== 'granted') return toast('Notifications not allowed');
      const key = Uint8Array.from(atob(vapid.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - vapid.length % 4) % 4)), c => c.charCodeAt(0));
      const sub = await reg.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: key});
      await api('/push', {method: 'POST', body: sub.toJSON()}); toast('Notifications on');
    } catch (e) { toast('Could not enable: ' + e.message); }
  }

  // ---- live updates: SSE over fetch (token in a header, never in a URL) in plan A, 15s polling in plan B
  async function sse() {
    if (PLAN !== 'A' || !TOKEN) return;
    while (true) {
      try {
        const r = await fetch('api/stream', {headers: {'Authorization': 'Bearer ' + TOKEN}, cache: 'no-store'});
        if (r.status === 401) return showAuth();
        ok(); const rd = r.body.getReader(), dec = new TextDecoder(); let buf = '';
        while (true) {
          const {value, done} = await rd.read(); if (done) break; buf += dec.decode(value, {stream: true});
          let i; while ((i = buf.indexOf('\n\n')) >= 0) { const chunk = buf.slice(0, i); buf = buf.slice(i + 2); const ev = (chunk.match(/^event: (.*)$/m) || [])[1]; if (ev) onEvent(ev); }
        }
      } catch (e) { fail(); }
      await new Promise(r => setTimeout(r, 3000));
    }
  }
  let pend = null;
  function onEvent(ev) {
    if (S.screen === 'audit' && ev === 'audit_layer') return; // the beam screen reloads on 'audit'
    clearTimeout(pend); pend = setTimeout(refresh, 400);
  }
  function refresh() { if (S.screen === 'home') home(); else if (S.screen === 'coin') coin(S.arg); else if (S.screen === 'activity') activity(); }
  setInterval(() => { if (PLAN === 'B' || failing) refresh(); else if (S.screen === 'coin' || S.screen === 'home') refresh(); }, 15000);
  window.addEventListener('resize', () => { if (S.screen === 'home') renderHome(); });
  route(); sse();
})();
