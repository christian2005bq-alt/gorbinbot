"""Helper for the two routines. Usage:
  desk_cli.py health [--fix]        heartbeats, process, websocket reconnects; --fix restarts + Telegram "Restarted {agent}, down {n} min"
  desk_cli.py report-file           path of the newest morning report (writes one for the current night if none yet today)
  desk_cli.py set-report-url URL    store the Page link (Telegram 'report' replies with it) and Telegram it to the owner
  desk_cli.py clear-skips           clear db.skips
  desk_cli.py send "text"           Telegram the owner (plain text)"""
import sys, os, time, subprocess, json, datetime as dt
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from common import SECRETS
from db import DB

AGENTS = ["main", "scanner", "auditor", "analyst", "executor", "risk", "telegram"]


def send(text):
    db = DB(); chat = db.kv_get("owner_chat_id")
    if not chat:
        print("no owner_chat_id"); return False
    r = httpx.post(f"https://api.telegram.org/bot{SECRETS['TG_TOKEN']}/sendMessage", json={"chat_id": int(chat), "text": text, "disable_web_page_preview": True}, timeout=20)
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


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "health":
        sys.exit(health("--fix" in sys.argv))
    elif cmd == "report-file":
        report_file()
    elif cmd == "set-report-url":
        DB().kv_set("last_report_url", sys.argv[2])
        send("Morning Page: " + sys.argv[2])
    elif cmd == "clear-skips":
        DB().exec("DELETE FROM skips"); print("skips cleared")
    elif cmd == "send":
        send(sys.argv[2])
    else:
        print(__doc__)
