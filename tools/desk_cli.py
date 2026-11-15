"""Helper for the two routines. Usage:
  desk_cli.py health [--fix]        heartbeats, process, websocket reconnects; --fix restarts + Telegram "Restarted {agent}, down {n} min"
  desk_cli.py report-file           path of the newest morning report (writes one for the current night if none yet today)
  desk_cli.py set-report-url URL    store the Page link (Telegram 'report' replies with it) and Telegram it to the owner
  desk_cli.py fomo-set --cash 37.89 [--positions JSON] [--trades JSON] [--note TXT]
                                    read-only snapshot of the real FOMO account (what was read on the FOMO screen)
  desk_cli.py copy-picks [--no-telegram]   copy-picks routine: run picks.py, store it, Telegram the message, print it
  desk_cli.py weekly-data [--days 7] [--json]   weekly-review routine: medians green vs red vs skipped-that-ran-2x
                                    (writes reports/weekly-YYYY-MM-DD.{md,json}, prints the markdown or JSON)
  desk_cli.py clear-skips           clear db.skips
  desk_cli.py send "text"           Telegram the owner (plain text)
  desk_cli.py lane-check            connect to the desk Chrome (127.0.0.1:9222), report logged in / not, 1 screenshot (no clicks)
  desk_cli.py dry-run MINT [USD]    S1+S2 on a coin page: open, Buy tab, type the amount, read the quote, screenshot, NO button
  desk_cli.py test-trade MINT --i-approve-real-money
                                    REAL MONEY. Only after Christian approves it: buy $2.00, verify, sell 100%, verify.
                                    Both verified on screen + API + chain -> unlocks desk.autoclick=on. Never Withdraw."""
import sys, os, time, subprocess, json, datetime as dt
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from common import SECRETS
from db import DB

AGENTS = ["main", "scanner", "auditor", "analyst", "brain", "executor", "risk", "telegram"]


def send(text, buttons=None):
    """Telegram the owner. buttons is an optional list of (label, https_url)
    pairs sent as a single row of inline URL buttons (needed so the phone
    keeps the #t= fragment on the private app link)."""
    db = DB(); chat = db.kv_get("owner_chat_id")
    if not chat:
        print("no owner_chat_id"); return False
    payload = {"chat_id": int(chat), "text": text, "disable_web_page_preview": True}
    if buttons:
        row = []
        for label, url in buttons:
            if not str(url).startswith("https://"):
                print("refusing non-https button url")
                return False
            row.append({"text": label, "url": url})
        payload["reply_markup"] = {"inline_keyboard": [row]}
    r = httpx.post(f"https://api.telegram.org/bot{SECRETS['TG_TOKEN']}/sendMessage", json=payload, timeout=20)
    ok = r.json().get("ok"); print("telegram sent:", ok); return ok


def alive():
    try:
        pid = int((ROOT / "desk.pid").read_text()); os.kill(pid, 0); return pid
    except Exception:
        return None


def health(fix=False):
    db = DB(); now = time.time()
    hb = {r["agent"]: r["ts"] for r in db.all("SELECT * FROM heartbeats")}
    pid = alive()
    stale = {a: (now - hb[a]) / 60 if a in hb else None for a in AGENTS}
    bad = {a: m for a, m in stale.items() if m is None or m > 2}
    rc = db.one("SELECT COUNT(*) c FROM events WHERE kind='ws_reconnect' AND ts>=?", (now - 3600,))["c"]
    print(f"process pid={pid or 'DOWN'}")
    for a, m in stale.items():
        print(f"  {a:9} heartbeat {'never' if m is None else f'{m:.1f} min ago'}{'  STALE' if a in bad else ''}")
    print(f"websocket reconnects last hour: {rc}")
    import urllib.request
    for label, url, script in (("trade-journal :3010", "http://127.0.0.1:3010/api/accounts", "start_journal.sh"),
                               ("timesfm :8795", "http://127.0.0.1:8795/health", "start_timesfm.sh")):
        try:
            urllib.request.urlopen(url, timeout=3); st = "up"
        except Exception:
            st = "DOWN"
            if fix:
                subprocess.run([str(ROOT / "tools" / script)], check=False); st = "DOWN -> started"
        print(f"  sidecar {label}: {st}")
    if fix and (not pid or bad):
        down = max([m for m in bad.values() if m is not None] or [0])
        subprocess.run([str(ROOT / "run.sh")], check=False)
        time.sleep(8)
        who = "desk process" if not pid else ", ".join(a for a in bad)
        send(f"Restarted {who}, down {down:.0f} min")
    if rc > 10:
        print("ALERT: more than 10 websocket reconnects in the last hour")
        if fix:
            send(f"Scanner websocket reconnected {rc} times in the last hour")
    return 0 if pid and not bad else 1


async def lane_cmd(cmd, args):
    from desk import Desk
    from browser import Lane
    d = Desk()
    lane = Lane(d)
    if d.s("desk.autoclick") == "off":
        print("desk.autoclick is off: set it to dryrun first (app Account tab or Telegram 'set autoclick to dryrun')"); return 2
    if not await lane.connect():
        print(f"no Chrome: {lane.status}. Start it with tools/start_chrome.sh"); return 2
    if cmd == "lane-check":
        await lane.page.wait_for_timeout(500)
        bad = await lane.check_session()
        p = ROOT / "logs" / "orders" / "lane_check.jpg"; p.parent.mkdir(parents=True, exist_ok=True)
        if not lane.private:
            await lane.page.screenshot(path=str(p), type="jpeg", quality=60)
        print(json.dumps({"url_ok": not lane.private, "logged_in": bad is None, "problem": bad, "token_seen": lane.api.has_token() if lane.api else False}))
        return 0
    mint = args[0]
    if cmd == "dry-run":
        usd = float(args[1]) if len(args) > 1 else 2.0
        res = await lane.order("buy", mint, usd, bot="executor", reason="dry-run check", dry=True)
        print(json.dumps({k: res.get(k) for k in ("order_id", "status", "quote_text", "fee_text", "error")}))
        return 0 if res.get("status") == "dry-run" else 1
    if "--i-approve-real-money" not in args:
        print("refused: test-trade spends real money; it needs --i-approve-real-money, and only after Christian approves it"); return 2
    if not d.s("desk.fomo_sol_address"):
        print("set desk.fomo_sol_address first (chain witness)"); return 2
    b = await lane.order("buy", mint, 2.0, bot="executor", reason="approved $2 test", dry=False, approved_test=True)
    print("BUY", json.dumps({k: b.get(k) for k in ("order_id", "status", "quote_text", "fee_text", "screen_ok", "api_ok", "chain_ok", "error")}))
    if not b.get("screen_ok"):
        return 1
    await asyncio.sleep(20)
    sres = await lane.order("sell", mint, None, pct=100, bot="risk", reason="approved $2 test", dry=False, priority=True, approved_test=True)
    print("SELL", json.dumps({k: sres.get(k) for k in ("order_id", "status", "quote_text", "fee_text", "screen_ok", "api_ok", "chain_ok", "error")}))
    if b.get("status") == "done" and sres.get("status") == "done":
        d.db.kv_set("autoclick.test_ok", "1")
        print("test trade verified on all checks: desk.autoclick=on is now allowed (Christian sets it)")
        return 0
    print("not unlocked: both orders must be 'done' (screen + API + chain). Raw API samples are in logs/raw/ for mapping.")
    return 1


def report_file():
    rep = sorted((ROOT / "reports").glob("night-*.md"))
    today = dt.date.today().isoformat()
    if not rep or today not in rep[-1].name:
        from desk import Desk
        import report
        d = Desk(); n = d.db.one("SELECT * FROM nights WHERE ended_at IS NOT NULL ORDER BY id DESC LIMIT 1")
        p = report.build(d, dict(n) if n else None)
        print(p); return
    print(rep[-1])


def fomo_set(argv):
    """Write a read-only snapshot of Christian's real FOMO account for the app's 'Cuenta FOMO' card."""
    import argparse, fomo_account
    ap = argparse.ArgumentParser(prog="desk_cli.py fomo-set")
    ap.add_argument("--cash", type=float, required=True)
    ap.add_argument("--positions", default="[]")
    ap.add_argument("--trades", default="[]")
    ap.add_argument("--note", default="")
    ap.add_argument("--at", type=float, default=None, help="unix time it was read (default now)")
    a = ap.parse_args(argv)
    from desk import Desk
    d = Desk(DB())
    snap = {"cash": round(a.cash, 2), "positions": json.loads(a.positions), "trades": json.loads(a.trades),
            "source": "screen", "note": a.note or None, "synced_at": a.at or time.time()}
    fomo_account.put(d, snap)
    print("fomo account snapshot saved: cash", snap["cash"], "positions", len(snap["positions"]), "trades", len(snap["trades"]))


def copy_picks(argv):
    import picks
    from desk import Desk
    d = Desk(DB())
    every = d.s("copy_picks.every")
    if every == "off" and "--force" not in argv:
        print("copy_picks.every is off (use --force to run anyway)"); return 0
    row = picks.run(d)
    if row["status"] == "ok":
        text, buttons = picks.message(row["picks"])
        print(text)
        if row.get("unmapped"):
            print("unmapped keys (check the raw sample):", ", ".join(row["unmapped"]))
        if "--no-telegram" not in argv:
            send(text, buttons[:3] or None)
        return 0
    print(f"copy picks {row['status']}: {row['error']}")
    print(f"stored as run #{row['id']}; no Telegram for a blocked run")
    return 2


def weekly_data(argv):
    import weekly, datetime as _dt
    from desk import Desk
    days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 7
    d = Desk(DB())
    w = weekly.build(d, days)
    md = weekly.markdown(w)
    out = ROOT / "reports"; out.mkdir(exist_ok=True)
    stem = out / f"weekly-{_dt.date.today().isoformat()}"
    stem.with_suffix(".json").write_text(json.dumps(w, indent=1))
    stem.with_suffix(".md").write_text(md)
    print(json.dumps(w, indent=1) if "--json" in argv else md)
    print(f"\n(saved {stem}.md and .json)")
    return 0



if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "health":
        sys.exit(health("--fix" in sys.argv))
    elif cmd == "report-file":
        report_file()
    elif cmd == "set-report-url":
        DB().kv_set("last_report_url", sys.argv[2])
        send("Morning Page: " + sys.argv[2])
    elif cmd == "copy-picks":
        sys.exit(copy_picks(sys.argv[2:]))
    elif cmd == "weekly-data":
        sys.exit(weekly_data(sys.argv[2:]))
    elif cmd == "fomo-set":
        fomo_set(sys.argv[2:])
    elif cmd == "clear-skips":
        DB().exec("DELETE FROM skips"); print("skips cleared")
    elif cmd == "send":
        send(sys.argv[2])
    elif cmd in ("lane-check", "dry-run", "test-trade"):
        import asyncio
        sys.exit(asyncio.run(lane_cmd(cmd, sys.argv[2:])))
    else:
        print(__doc__)

