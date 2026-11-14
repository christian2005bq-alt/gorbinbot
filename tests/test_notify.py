"""STEP 13.1b test_notify: send 1 PAPER push through every channel set up (Telegram; web push only if subscribed),
through the RUNNING desk. Each must carry the exact links.py URL with r=savipww. Run as a script (sends a real message)."""
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from common import SECRETS
from db import DB
import links

if __name__ == "__main__":
    db = DB()
    if not db.kv_get("owner_chat_id"):
        print("SKIP: no owner_chat_id yet (send /start to the bot)"); sys.exit(2)
    t0 = time.time()
    r = httpx.post("http://127.0.0.1:8787/api/test_push", headers={"Authorization": "Bearer " + SECRETS["APP_TOKEN"]}, timeout=60)
    print("POST /api/test_push ->", r.status_code, r.json())
    rows = db.all("SELECT * FROM pushes WHERE ts>=? ORDER BY ts", (t0 - 1,))
    ok = True
    for p in rows:
        exact = p["link"] == links.coin_url(p["mint"], "solana")
        print(f"channel={p['channel']} delivered={bool(p['ok'])} text={p['text']!r}\n  button url={p['link']}\n  exact links.coin_url: {exact} · r=savipww: {'r=savipww' in (p['link'] or '')}")
        ok = ok and bool(p["ok"]) and exact and p["text"].startswith("PAPER · ")
    print("test_notify:", "PASS" if ok and rows else "FAIL")
    sys.exit(0 if ok and rows else 1)
