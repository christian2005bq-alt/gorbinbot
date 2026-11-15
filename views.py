"""JSON shapes for the app (STEP 7). Used by api.py (plan A) and the plan B JSON writer."""
import datetime as dt
import links
from common import now, iso, mask_secret
from config import DEFAULTS, CHOICES
from agents.risk import exit_line, effective_stop_pct

RANGES = {"LIVE": 30 * 60, "1H": 3600, "4H": 4 * 3600, "1D": 86400, "1W": 7 * 86400, "ALL": None}


def _use_ref(d):
    links.set_ref_code(d.s("desk.ref_code") or "gorbindx")


def _url(m):
    return links.coin_url(m, "solana") if m else None


def revision(d):
    """Cheap fingerprint of user-visible desk state, for /api/rev ETag polling."""
    db = d.db

    def mid(table):
        r = db.one(f"SELECT MAX(id) AS i FROM {table}")
        return int(r["i"] or 0) if r else 0

    def mts(table, col="ts"):
        r = db.one(f"SELECT MAX({col}) AS t FROM {table}")
        return float(r["t"] or 0) if r else 0

    paused = "".join("1" if d.paused(a) else "0" for a in ("scanner", "auditor", "analyst", "brain", "executor", "risk"))
    unread = db.one("SELECT COUNT(*) c FROM pushes WHERE read=0")["c"]
    parts = [
        mid("activity"), mid("decisions"), mid("audits"), mid("verdicts"),
        mid("signals"), mid("positions"), mid("pushes"), mid("scans"), mid("orders"),
        int((d.lane.last_frame_ts if d.lane else 0) // 5),
        mts("settings", "updated_at"), mts("balance"), mts("prices"), mts("change_log"),
        d.mode(), f"{d.balance():.2f}", unread, paused, _fomo_fp(d),
    ]
    return "|".join(map(str, parts))


def _fomo_fp(d):
    try:
        import fomo_account
        s = fomo_account.get(d) or {}
        return hash(repr((s.get("cash"), s.get("positions"), s.get("trades"), s.get("source"))))
    except Exception:
        return 0


TZ = "America/Guayaquil"


def local_hm(ts):
    from zoneinfo import ZoneInfo
    return dt.datetime.fromtimestamp(ts, ZoneInfo(TZ)).strftime("%H:%M:%S") if ts else None


VERDICT_ES = {"kill": "descartada", "pass": "pasa", "waiting": "en sala de espera", "reject": "rechazada",
              "skip": "saltada", "size": "tamaño", "bought": "comprada", "failed": "falló", "missed": "perdida"}


def feed_row(d, r):
    """One live-feed line: every agent decision, coin name or short mint, reason, Guayaquil time."""
    m = r.get("mint")
    c = d.db.coin(m) if m else None
    sym = (c and (c.get("symbol") or c.get("name"))) or None
    short = f"{m[:4]}…{m[-4:]}" if m and len(m) > 10 else m
    return {"id": r["id"], "ts": r["ts"], "time": local_hm(r["ts"]), "agent": r["agent"], "mint": m, "short": short,
            "name": sym or short, "verdict": r["verdict"], "verdict_es": VERDICT_ES.get(r["verdict"], r["verdict"]),
            "reason": r.get("reason"), "coin_url": _url(m)}


def night_window(d, t=None):
    t = t if t is not None else now()
    ws = d.window_start_ts(t)
    a, b = d.s("desk.night_start"), d.s("desk.lock_time")
    hh, mm = map(int, b.split(":"))
    x = dt.datetime.fromtimestamp(ws)
    end = x.replace(hour=hh, minute=mm)
    if end <= x:
        end += dt.timedelta(days=1)
    open_ = d.in_night(t)
    nxt = ws + 86400
    return {"open": open_, "start": a, "end": b, "tz": TZ, "window_start_ts": ws,
            "closes_in_s": round(end.timestamp() - t) if open_ else None,
            "opens_in_s": None if open_ else round(nxt - t), "locked": d.db.kv_get("night.locked") == "1"}


def live(d, before=None, limit=60):
    """Status strip + live decision feed for the app."""
    _use_ref(d)
    db = d.db
    win = night_window(d)
    since = win["window_start_ts"]
    q = "SELECT * FROM decisions" + (" WHERE ts<?" if before else "") + " ORDER BY ts DESC, id DESC LIMIT ?"
    rows = db.all(q, ((float(before), limit) if before else (limit,)))
    feed = [feed_row(d, r) for r in rows]
    hb = {r["agent"]: r["ts"] for r in db.all("SELECT * FROM heartbeats")}
    t = now()
    agents = [{"name": a, "heartbeat": hb.get(a), "age_s": round(t - hb[a]) if hb.get(a) else None,
               "ok": bool(hb.get(a) and t - hb[a] < 150), "paused": d.paused(a)}
              for a in ("scanner", "auditor", "analyst", "brain", "executor", "risk")]
    cnt = lambda sql, a: db.one(sql, a)["c"]
    sc = d.agents.get("scanner")
    counts = {
        "seen": cnt("SELECT COUNT(*) c FROM coins WHERE first_seen>=?", (since,)),
        "scanned": cnt("SELECT COUNT(*) c FROM scans WHERE ts>=?", (since,)),
        "killed": cnt("SELECT COUNT(*) c FROM scans WHERE verdict='kill' AND ts>=?", (since,)),
        "passed": cnt("SELECT COUNT(*) c FROM scans WHERE verdict='pass' AND ts>=?", (since,)),
        "waiting": len(sc.room) if sc else cnt("SELECT COUNT(*) c FROM coins c WHERE first_seen>=? AND NOT EXISTS (SELECT 1 FROM scans s WHERE s.mint=c.mint)", (since,)),
        "audited": cnt("SELECT COUNT(DISTINCT mint) c FROM audits WHERE ts>=?", (since,)),
        "scored": cnt("SELECT COUNT(*) c FROM verdicts WHERE ts>=?", (since,)),
        "trades": d.trades_tonight(),
    }
    top = db.all("SELECT reason, COUNT(*) n FROM scans WHERE verdict='kill' AND ts>=? GROUP BY CASE WHEN reason LIKE 'liq %' THEN 'liq' ELSE reason END ORDER BY n DESC LIMIT 3", (since,))
    rules = {"min_liquidity_usd": d.s("scanner.min_liquidity_usd"), "max_top10_pct": d.s("scanner.max_top10_pct"),
             "max_h1_change_pct": d.s("scanner.max_h1_change_pct"), "min_pool_age_min": d.s("scanner.min_pool_age_min")}
    sl = db.all("SELECT ts, detail FROM events WHERE kind='box_sleep' AND ts>=? ORDER BY ts DESC", (since,))
    box = {"sleeps": len(sl), "slept_min": round(sum(float(r["detail"]) for r in sl) / 60),
           "last_wake_ts": sl[0]["ts"] if sl else None, "last_sleep_min": round(float(sl[0]["detail"]) / 60) if sl else None}
    return {"mode": d.mode(), "window": win, "box": box, "agents": agents, "counts": counts, "rules": rules,
            "top_kills": [{"reason": ("liquidez baja" if (r["reason"] or "").startswith("liq ") else r["reason"]), "n": r["n"]} for r in top],
            "feed": feed, "next": feed[-1]["ts"] if len(feed) == limit else None, "now": t, "now_local": local_hm(t), "tz": TZ}


def state(d):
    _use_ref(d)
    night = d.night()
    start_bal = night["start_balance"] if night else d.balance()
    bal = d.balance()
    db, ns = d.db, d.night_start_ts()
    cnt = lambda sql, a=(): db.one(sql, a)["c"]
    feed = db.all("SELECT s.mint, s.verdict, s.reason, s.liquidity_usd, s.ts, c.name, c.symbol FROM scans s LEFT JOIN coins c ON c.mint=s.mint ORDER BY s.ts DESC LIMIT 6")
    for f in feed:
        f["coin_url"] = _url(f["mint"])
    sc = d.agents.get("scanner")
    last_audit = db.one("SELECT run_id, mint FROM audits ORDER BY id DESC LIMIT 1")
    strips, aud_mint = [None] * 8, None
    if last_audit:
        aud_mint = last_audit["mint"]
        for r in db.all("SELECT layer, pass FROM audits WHERE run_id=?", (last_audit["run_id"],)):
            strips[r["layer"] - 1] = None if r["pass"] is None else bool(r["pass"])
    ac = d.cards.get("auditor", {})
    lv = db.one("SELECT * FROM verdicts ORDER BY ts DESC LIMIT 1")
    ec = d.cards.get("executor", {})
    lastsig = db.one("SELECT * FROM signals WHERE status IN ('bought','sent') ORDER BY ts DESC LIMIT 1")
    lastexit = db.one("SELECT exit_reason FROM positions WHERE exit_reason IS NOT NULL ORDER BY closed_at DESC LIMIT 1")
    hb = {r["agent"]: r["ts"] for r in db.all("SELECT * FROM heartbeats")}
    bc = d.cards.get("brain", {})
    br = d.agents.get("brain")
    agents = [
        {"name": "scanner", "title": "Scanner", "color": "#64d2ff", "paused": d.paused("scanner"), "heartbeat": hb.get("scanner"),
         "pools": cnt("SELECT COUNT(*) c FROM coins WHERE first_seen>=?", (ns,)), "waiting": len(sc.room) if sc else 0, "feed": feed},
        {"name": "auditor", "title": "Auditor", "color": "#ffffff", "paused": d.paused("auditor"), "heartbeat": hb.get("auditor"),
         "taken_apart": cnt("SELECT COUNT(DISTINCT mint) c FROM audits WHERE ts>=?", (ns,)),
         "rejected": cnt("SELECT COUNT(*) c FROM decisions WHERE agent='auditor' AND verdict='reject' AND ts>=?", (ns,)),
         "running": bool(ac.get("running")), "strips": strips, "mint": aud_mint, "name_coin": d.coin_name(aud_mint) if aud_mint else None,
         "result": ("8/8 → Executor" if ac.get("passed") else ac.get("reason")) if "passed" in ac else None},
        {"name": "analyst", "title": "Analyst", "color": "#ffd60a", "paused": d.paused("analyst"), "heartbeat": hb.get("analyst"),
         "score": lv["score"] if lv else None, "passed": bool(lv["pass"]) if lv else None, "mint": lv["mint"] if lv else None,
         "min_score": d.s("analyst.min_score"), "mode": d.s("analyst.mode"),
         "scored": cnt("SELECT COUNT(*) c FROM verdicts WHERE ts>=?", (ns,))},
        {"name": "brain", "title": "Brain", "color": "#bf5af2", "paused": d.paused("brain"), "heartbeat": hb.get("brain"),
         "size": bc.get("size"), "pct": bc.get("pct"), "cap": bc.get("cap"), "free_cash": round(d.free_cash(), 2),
         "full_score": d.s("brain.full_size_score"), "trades": d.trades_tonight(), "max_trades": d.s("brain.max_trades_night"),
         "block": br.night_block() if br else None},
        {"name": "executor", "title": "Executor", "color": "#00d35a", "paused": d.paused("executor"), "heartbeat": hb.get("executor"),
         "trades": cnt("SELECT COUNT(*) c FROM signals WHERE status IN ('bought','sent') AND ts>=?", (ns,)),
         "size": lastsig["size_usd"] if lastsig else None, "stack_pct": lastsig["stack_pct"] if lastsig else None,
         "last_pct": lastsig["stack_pct"] if lastsig else None, "state": ec.get("state"), "state_ts": ec.get("ts"),
         "waiting": cnt("SELECT COUNT(*) c FROM signals WHERE status='waiting'"), "dip_pct": d.s("executor.dip_pct"),
         "autoclick": d.s("desk.autoclick")},
        {"name": "risk", "title": "Risk", "color": "#ff6b9a", "paused": d.paused("risk"), "heartbeat": hb.get("risk"),
         "open": len(d.open_positions()), "stop_pct": d.s("risk.stop_pct"), "trail_pct": d.s("executor.trail_pct"),
         "last_exit": {"trail": "Trailed out", "stop": "Stopped", "pulled": "Stopped", "dead money": "Timed out", "take profit": "Took profit"}.get(lastexit["exit_reason"]) if lastexit else None},
    ]
    unread = db.one("SELECT COUNT(*) c FROM pushes WHERE read=0 AND ts>=?", (ns,))["c"]
    tc = d.settings.ticket_check()
    lo = db.one("SELECT o.*, c.symbol FROM orders o LEFT JOIN coins c ON c.mint=o.mint ORDER BY o.id DESC LIMIT 1")
    last_order = None
    if lo:
        last_order = {k: lo[k] for k in ("side", "usd", "status", "screen_ok", "api_ok", "chain_ok", "mint")}
        last_order["name"] = lo["symbol"]
    return {"lane": d.lane.card() if d.lane else {"mode": "off"}, "last_order": last_order, "balance": bal, "start_balance": start_bal, "today_pct": round(100 * (bal / start_bal - 1), 2) if start_bal else 0,
            "multiplier": round(bal / start_bal, 2) if start_bal else 1, "mode": d.mode(), "agents": agents,
            "unread": unread, "ticket_warning": tc[1] if tc else None, "ts": iso(), "night_started": iso(ns)}


def chart(d, rng="LIVE"):
    _use_ref(d)
    span = RANGES.get(rng.upper(), RANGES["LIVE"])
    since = now() - span if span else 0
    pts = d.db.all("SELECT ts, value FROM balance WHERE ts>=? ORDER BY ts", (since,))
    if len(pts) > 600:
        step = len(pts) // 600 + 1
        pts = pts[::step] + [pts[-1]]
    night = d.night()
    marks = []
    for a in d.db.all("SELECT * FROM activity WHERE ts>=? AND kind IN ('bought','sold','stopped') ORDER BY ts", (since,)):
        name = a["title"].split(" ", 1)[1] if " " in a["title"] else a["title"]
        if a["kind"] == "bought":
            marks.append({"ts": a["ts"], "kind": "bought", "text": f"Bought {name}", "color": "#0a84ff"})
        elif a["kind"] == "sold":
            marks.append({"ts": a["ts"], "kind": "sold", "text": a["value"].split(" · ")[0], "color": "#00d35a" if a["value"].startswith("+") else "#ff453a"})
        else:
            pct = a["subtitle"].split("· ")[-1].replace(" stop", "")
            marks.append({"ts": a["ts"], "kind": "stopped", "text": f"{pct} · {a['value']}", "color": "#ff453a"})
    return {"range": rng.upper(), "points": [[p["ts"], p["value"]] for p in pts], "marks": marks,
            "start_value": night["start_balance"] if night else (pts[0]["value"] if pts else d.balance())}


def activity(d, before=None, limit=30):
    _use_ref(d)
    if before:
        rows = d.db.all("SELECT * FROM activity WHERE id<? ORDER BY id DESC LIMIT ?", (int(before), limit))
    else:
        rows = d.db.all("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,))
    for r in rows:
        r["coin_url"] = _url(r["mint"])
    return {"rows": rows, "next": rows[-1]["id"] if len(rows) == limit else None}


def candles(d, mint, minutes=240):
    rows = d.db.all("SELECT ts, price, volume_m5 FROM prices WHERE mint=? AND ts>=? ORDER BY ts", (mint, now() - minutes * 60))
    out, prev_vol = [], None
    for r in rows:
        b = int(r["ts"] // 60) * 60
        dv = 0.0
        if r["volume_m5"] is not None and prev_vol is not None:
            dv = max(0.0, r["volume_m5"] - prev_vol)
        if r["volume_m5"] is not None:
            prev_vol = r["volume_m5"]
        if out and out[-1]["t"] == b:
            c = out[-1]; c["h"] = max(c["h"], r["price"]); c["l"] = min(c["l"], r["price"]); c["c"] = r["price"]; c["v"] += dv
        else:
            o = out[-1]["c"] if out else r["price"]
            out.append({"t": b, "o": o, "h": max(o, r["price"]), "l": min(o, r["price"]), "c": r["price"], "v": dv})
    return out


def audit(d, mint):
    _use_ref(d)
    last = d.db.one("SELECT run_id FROM audits WHERE mint=? ORDER BY id DESC LIMIT 1", (mint,))
    coin = d.db.coin(mint) or {}
    name = coin.get("symbol") or coin.get("name") or mint[:6]
    if not last:
        return {"mint": mint, "name": name, "layers": [], "status": "none", "coin_url": _url(mint), "enabled": d.s("auditor.enabled")}
    layers = d.db.all("SELECT layer n, name, value_text value, pass, source, ts FROM audits WHERE run_id=? ORDER BY layer", (last["run_id"],))
    for l in layers:
        l["pass"] = None if l["pass"] is None else bool(l["pass"])
    red = next((l for l in layers if l["pass"] is False), None)
    done = len(layers) == 8
    sig = d.db.one("SELECT size_usd FROM signals WHERE mint=? ORDER BY ts DESC LIMIT 1", (mint,))
    return {"mint": mint, "name": name, "layers": layers, "run": last["run_id"],
            "status": "rejected" if red else ("cleared" if done and all(l["pass"] for l in layers) else "running"),
            "reason": red["value"] if red else None, "sent_size": sig["size_usd"] if sig else None,
            "holders": coin.get("holders"), "coin_url": _url(mint), "enabled": d.s("auditor.enabled")}


def coin(d, mint):
    _use_ref(d)
    c = d.db.coin(mint) or {"mint": mint}
    lp = d.db.one("SELECT * FROM prices WHERE mint=? ORDER BY ts DESC LIMIT 1", (mint,))
    pos = d.db.one("SELECT * FROM positions WHERE mint=? ORDER BY opened_at DESC LIMIT 1", (mint,))
    pos = dict(pos) if pos else None
    au = audit(d, mint)
    shield = None
    if au["layers"]:
        shield = f"{sum(1 for l in au['layers'] if l['pass'])}/8"
    exit_card = None
    if pos and pos["status"] in ("open", "exiting"):
        line = exit_line(pos, d.s)
        stop_pct = effective_stop_pct(pos["stop_pct"], d.s("risk.stop_pct"))
        trail_line = (pos["peak_price"] * (1 - d.s("executor.trail_pct") / 100)) if pos["trail_active"] else None
        left = max(0, pos["opened_at"] + d.s("risk.timeout_h") * 3600 - now())
        exit_card = {"exit_line": line, "stop_price": pos["entry_price"] * (1 - stop_pct / 100), "stop_pct": stop_pct,
                     "trail_line": trail_line, "trail_pct": d.s("executor.trail_pct"), "trail_active": bool(pos["trail_active"]),
                     "trail_start_price": pos["entry_price"] * d.s("executor.tp_x"), "tp_done": bool(pos.get("tp_done")), "timeout_left_s": left}
    age_h = (now() - c["migrated_at"]) / 3600 if c.get("migrated_at") else None
    return {"mint": mint, "name": c.get("name"), "symbol": c.get("symbol"), "age_h": age_h, "shield": shield,
            "price": lp["price"] if lp else None, "market_cap": lp["market_cap"] if lp else None,
            "liquidity": lp["liquidity_usd"] if lp else None, "volume_h24": lp["volume_h24"] if lp else None,
            "holders": c.get("holders"), "candles": candles(d, mint), "position": pos, "exit": exit_card,
            "since_entry_pct": round(100 * (lp["price"] / pos["entry_price"] - 1), 2) if (lp and pos) else None,
            "coin_url": _url(mint), "mode": d.mode(), "price_ts": lp["ts"] if lp else None}


def decisions(d, name):
    _use_ref(d)
    rows = d.db.all("SELECT d.*, c.name, c.symbol FROM decisions d LEFT JOIN coins c ON c.mint=d.mint WHERE agent=? ORDER BY d.ts DESC LIMIT 20", (name,))
    for r in rows:
        r["coin_url"] = _url(r["mint"])
    today = d.db.one("SELECT COUNT(*) c FROM decisions WHERE agent=? AND ts>=?", (name, d.night_start_ts()))["c"]
    return {"agent": name, "paused": d.paused(name), "today": today, "rows": rows,
            "locked": name == "risk" and bool(d.open_positions())}


def account(d, plan="B"):
    _use_ref(d)
    h = d.s("desk.fomo_handle")
    tg = bool(d.db.kv_get("owner_chat_id"))
    return {"mode": d.mode(), "stack": d.s("desk.stack"), "paper_start_stack": d.s("desk.paper_start_stack"),
            "fomo_handle": h, "profile_url": links.profile_url(h) if h else None, "signup_url": links.SIGNUP_URL,
            "telegram": "connected" if tg else "not connected", "plan": plan, "webpush": plan == "A",
            "vapid_public": __import__("webpush").public_key() if plan == "A" else None,
            "full_paper_nights": d.full_paper_nights(), "analyst_mode": d.s("analyst.mode")}


def settings(d):
    _use_ref(d)
    out = []
    for k, (dflt, lo, hi, typ, label) in DEFAULTS.items():
        val = d.s(k)
        if k == "desk.rpc_url" and isinstance(val, str):
            val = mask_secret(val)
        out.append({"key": k, "group": k.split(".")[0], "label": label, "value": val, "default": dflt, "min": lo, "max": hi,
                    "type": typ.__name__, "choices": CHOICES.get(k)})
    return {"settings": out}
