"""Morning Page (STEP 12). Writes reports/night-YYYY-MM-DD.md (+ .html). The night-report routine publishes it as a Page."""
import datetime as dt, html, sys
from collections import Counter
import links
from common import ROOT, now

OUT = ROOT / "reports"


def _t(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "?"


def build(d, night=None):
    OUT.mkdir(exist_ok=True)
    night = night or d.night() or {"started_at": now() - 86400, "start_balance": d.balance(), "mode": d.mode()}
    a, b = night["started_at"], night.get("ended_at") or now()
    db = d.db
    name = lambda m: d.coin_name(m)
    link = lambda m: f"[{name(m)}]({links.coin_url(m, 'solana')})"
    L = []
    day = dt.datetime.fromtimestamp(b).strftime("%Y-%m-%d")
    L.append(f"# Night report · {day} · {night.get('mode', d.mode())}")
    l8 = db.one("SELECT COUNT(DISTINCT mint) c FROM audits WHERE layer=8 AND pass=0 AND value_text='no data: delegations' AND ts BETWEEN ? AND ?", (a, b))["c"]
    if l8:
        L.append(f"\n**Layer 8 down: {l8} coins killed with \"no data: delegations\".**")
    bal = d.balance()
    L.append(f"\n{_t(a)} → {_t(b)} · balance ${night.get('start_balance') or 0:,.2f} → ${bal:,.2f}")
    pos = db.all("SELECT * FROM positions WHERE closed_at BETWEEN ? AND ? OR (status IN ('open','exiting') AND opened_at<=?) ORDER BY opened_at", (a, b, b))
    red = [p for p in pos if p["pnl_usd"] is not None and p["pnl_usd"] < 0]
    green = [p for p in pos if p["pnl_usd"] is not None and p["pnl_usd"] >= 0]
    opn = [p for p in pos if p["pnl_usd"] is None]
    def row(p):
        pct = 100 * ((p["exit_price"] or 0) / p["entry_price"] - 1) if p["exit_price"] else 0
        rule = {"stop": f"-{p['stop_pct']:g}% stop", "trail": "trailing stop", "timeout": "timeout", "pulled": "liquidity pulled"}.get(p["exit_reason"], p["exit_reason"])
        return f"| {link(p['mint'])} | {p['entry_price']:.8g} | {p['exit_price'] or 0:.8g} | {'+' if p['pnl_usd'] >= 0 else '-'}${abs(p['pnl_usd']):.2f} | {pct:+.1f}% | {rule} |"
    hdr = "| Coin | Entry | Exit | $ | % | Rule |\n|---|---|---|---|---|---|"
    L.append(f"\n## Red trades ({len(red)})\n" + (hdr + "\n" + "\n".join(row(p) for p in red) if red else "None."))
    L.append(f"\n## Green trades ({len(green)})\n" + (hdr + "\n" + "\n".join(row(p) for p in green) if green else "None."))
    if opn:
        L.append("\n## Still open\n" + "\n".join(f"- {link(p['mint'])} · ${p['size_usd']:.2f} in since {_t(p['opened_at'])}" for p in opn))
    seen = db.all("SELECT mint FROM coins WHERE first_seen BETWEEN ? AND ?", (a, b))
    L.append(f"\n## Coins seen: {len(seen)}")
    kills = Counter()
    for r in db.all("SELECT reason FROM scans WHERE verdict='kill' AND ts BETWEEN ? AND ?", (a, b)):
        rs = r["reason"] or "?"
        key = rs.split(" ")[0] if rs.startswith(("liq", "copycat")) else ("top 10" if rs.startswith("top 10") else ("1h change" if rs.endswith("in 1h") else rs))
        kills[key] += 1
    L.append("\n## Scanner kills by reason\n" + ("\n".join(f"- {k}: {v}" for k, v in kills.most_common()) or "None."))
    refs = db.all("SELECT mint, layer, name, value_text, ts FROM audits WHERE pass=0 AND ts BETWEEN ? AND ? ORDER BY layer, ts", (a, b))
    L.append("\n## Auditor refusals by layer\n" + ("\n".join(f"- L{r['layer']} {r['name']} · {link(r['mint'])} · {r['value_text']} · {_t(r['ts'])}" for r in refs) or "None."))
    rej = db.all("SELECT mint, reason, model, ts FROM verdicts WHERE pass=0 AND ts BETWEEN ? AND ?", (a, b))
    L.append("\n## Analyst rejects\n" + ("\n".join(f"- {link(r['mint'])} · {'Analyst (rules)' if r['model'] == 'rules' else 'Analyst'} · {r['reason']} · {_t(r['ts'])}" for r in rej) or "None."))
    jt = db.one("SELECT COUNT(*) n, COALESCE(SUM(input_tokens),0) i, COALESCE(SUM(output_tokens),0) o FROM jev_calls WHERE ts BETWEEN ? AND ?", (a, b))
    L.append(f"\n## Jev\n{jt['n']} calls · {jt['i']:,} input tokens · {jt['o']:,} output tokens · cost: n/a (no per-token price on file)")
    fees = db.one("SELECT COALESCE(SUM(fees_usd),0) f FROM positions WHERE closed_at BETWEEN ? AND ?", (a, b))["f"]
    L.append(f"\n## Fees paid\n${fees:.2f} (FOMO fee model, 10% ref discount, gas $0)")
    L.append(f"\n---\nNew to FOMO? {links.SIGNUP_URL}")
    md = "\n".join(L) + "\n"
    p = OUT / f"night-{day}.md"
    p.write_text(md)
    return p


if __name__ == "__main__":
    from desk import Desk
    d = Desk()
    print(build(d))
