"""WEEKLY REVIEW data (v2 STEP 14). Per metric the desk logs, the median on green trades vs red trades vs coins
skipped that later ran 2x, plus counts. The routine turns this into a Page with at most 3 suggested setting changes;
nothing here changes a setting."""
import re, statistics, json
from common import now

METRICS = ["score", "alive", "organic", "flush", "chase", "social_pts", "fresh_pct", "curve_min", "insiders_pct",
           "holders_growth", "liq_mcap", "accel", "dip_depth_pct"]


def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 4) if xs else None


def coin_metrics(db, mint):
    m = {k: None for k in METRICS}
    v = db.one("SELECT * FROM verdicts WHERE mint=? ORDER BY ts DESC LIMIT 1", (mint,))
    if v:
        m.update({"score": v["score"], "alive": v["alive_6h"], "organic": v["organic"], "flush": v["flush"], "chase": v["chase"],
                  "social_pts": v["social_pts"], "fresh_pct": v["fresh_pct"], "curve_min": v["curve_min"]})
    if m["curve_min"] is None:
        c = db.one("SELECT curve_min FROM coins WHERE mint=?", (mint,))
        m["curve_min"] = c["curve_min"] if c else None
    a = db.one("SELECT value_text FROM audits WHERE mint=? AND layer=7 ORDER BY id DESC LIMIT 1", (mint,))
    if a and a["value_text"]:
        x = re.search(r"insiders (\d+(?:\.\d+)?)%", a["value_text"])
        m["insiders_pct"] = float(x.group(1)) if x else (0.0 if "0 insider" in a["value_text"] else None)
    s = db.one("SELECT holders_growth, liq_mcap, accel FROM scans WHERE mint=? ORDER BY ts DESC LIMIT 1", (mint,))
    if s:
        m.update({"holders_growth": s["holders_growth"], "liq_mcap": s["liq_mcap"], "accel": s["accel"]})
    g = db.one("SELECT dip_depth_pct FROM signals WHERE mint=? AND dip_depth_pct IS NOT NULL ORDER BY ts DESC LIMIT 1", (mint,))
    if g:
        m["dip_depth_pct"] = g["dip_depth_pct"]
    return m


def ran_2x(db, mint, since_ts):
    p0 = db.one("SELECT price FROM prices WHERE mint=? AND ts>=? ORDER BY ts LIMIT 1", (mint, since_ts))
    if not p0 or not p0["price"]:
        return False, None
    hi = db.one("SELECT MAX(price) h FROM prices WHERE mint=? AND ts>=?", (mint, since_ts))["h"]
    return (hi or 0) >= 2 * p0["price"], round((hi or 0) / p0["price"], 2)


def build(d, days=7):
    db, since = d.db, now() - days * 86400
    closed = db.all("SELECT mint, pnl_usd FROM positions WHERE closed_at>=? AND pnl_usd IS NOT NULL", (since,))
    bought = {r["mint"] for r in db.all("SELECT DISTINCT mint FROM positions WHERE opened_at>=?", (since,))}
    green = [r["mint"] for r in closed if r["pnl_usd"] > 0]
    red = [r["mint"] for r in closed if r["pnl_usd"] <= 0]
    skipped, runners = {}, []
    for r in db.all("SELECT mint, MIN(ts) ts FROM decisions WHERE ts>=? AND verdict IN ('kill','reject','skip','missed') GROUP BY mint", (since,)):
        if r["mint"] and r["mint"] not in bought:
            skipped[r["mint"]] = r["ts"]
    for m, t in skipped.items():
        ok, x = ran_2x(db, m, t)
        if ok:
            runners.append((m, x))
    groups = {"green": green, "red": red, "skipped_2x": [m for m, _ in runners]}
    per = {g: [coin_metrics(db, m) for m in ms] for g, ms in groups.items()}
    med = {k: {g: _med([x[k] for x in per[g]]) for g in groups} for k in METRICS}
    kills = db.all("SELECT CASE WHEN reason LIKE 'liq %' THEN 'liq under min' ELSE reason END r, COUNT(*) n FROM scans WHERE verdict='kill' AND ts>=? GROUP BY r ORDER BY n DESC LIMIT 10", (since,))
    return {"days": days, "generated_at": now(),
            "counts": {"green": len(green), "red": len(red), "skipped": len(skipped), "skipped_2x": len(runners),
                       "scanned": db.one("SELECT COUNT(*) c FROM scans WHERE ts>=?", (since,))["c"],
                       "pnl_usd": round(sum(r["pnl_usd"] for r in closed), 2)},
            "medians": med, "runners": [{"mint": m, "max_x": x} for m, x in runners][:20],
            "scanner_kills": [dict(r) for r in kills],
            "settings_now": {k: d.s(k) for k in ("scanner.min_liquidity_usd", "analyst.min_score", "executor.dip_pct", "risk.stop_pct",
                                                 "executor.trail_pct", "brain.risk_per_trade_pct", "analyst.max_fresh_pct")},
            "rule": "suggest at most 3 setting changes with the numbers behind each; apply none (Christian approves in the app)"}


def markdown(w):
    c = w["counts"]
    out = [f"# Weekly review data · last {w['days']} days", "",
           f"Trades: {c['green']} green · {c['red']} red · PnL ${c['pnl_usd']:+.2f} · scanned {c['scanned']} · skipped {c['skipped']} (ran 2x after: {c['skipped_2x']})", "",
           "| metric | green | red | skipped that ran 2x |", "|---|---|---|---|"]
    f = lambda v: "n/a" if v is None else f"{v:g}"
    for k, g in w["medians"].items():
        out.append(f"| {k} | {f(g['green'])} | {f(g['red'])} | {f(g['skipped_2x'])} |")
    out += ["", "Scanner kills: " + (", ".join(f"{r['r']} {r['n']}" for r in w["scanner_kills"]) or "none"),
            "", "Settings now: " + ", ".join(f"{k}={v}" for k, v in w["settings_now"].items()), "", w["rule"]]
    return "\n".join(out)
