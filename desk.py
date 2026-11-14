"""Shared context: db, settings, bus, sources, notifier, activity/decision helpers, balance."""
import json, time
import httpx
from common import now, iso, get_logger
from db import DB
from config import Settings
from bus import Bus
import sources as S
import links

AGENTS = ["scanner", "auditor", "analyst", "executor", "risk"]


class Desk:
    def __init__(self, db: DB | None = None, client: httpx.AsyncClient | None = None):
        self.db = db or DB()
        self.settings = Settings(self.db)
        self.bus = Bus()
        self.client = client or httpx.AsyncClient(headers={"User-Agent": "grokbot-desk/1.0"})
        self.dex = S.Dex(self.client, self.settings.get("scanner.max_dex_rpm"))
        self.rug = S.RugCheck(self.client)
        self.rpc = S.RPC(self.client, lambda: self.settings.get("desk.rpc_url"))
        self.notifier = None      # set in main (notifier.Notifier)
        self.agents = {}
        self.cards = {a: {} for a in AGENTS}
        self.log = get_logger("desk")
        if self.db.kv_get("paper_cash") is None:
            self.db.kv_set("paper_cash", self.settings.get("desk.paper_start_stack"))

    # ---- helpers
    def s(self, key):
        return self.settings.get(key)

    def mode(self):
        return self.s("desk.mode")

    def heartbeat(self, agent):
        self.db.exec("INSERT INTO heartbeats(agent,ts) VALUES(?,?) ON CONFLICT(agent) DO UPDATE SET ts=excluded.ts", (agent, now()))

    def paused(self, agent):
        return self.db.kv_get(f"paused.{agent}") == "1"

    def set_paused(self, agent, on: bool):
        if agent == "risk" and on and self.open_positions():
            raise ValueError("Risk can't be paused while a position is open")
        self.db.kv_set(f"paused.{agent}", "1" if on else "0")
        self.bus.emit("agent", {"agent": agent, "paused": on})

    def decision(self, agent, mint, verdict, reason, line=None):
        self.db.exec("INSERT INTO decisions(ts,agent,mint,verdict,reason) VALUES(?,?,?,?,?)", (now(), agent, mint, verdict, reason))
        self.status(agent, line or self.status_line(agent, mint, verdict, reason))

    NEXT = {"scanner": "Auditor", "auditor": "Analyst", "analyst": "Executor", "executor": "Risk"}

    def status_line(self, agent, mint, verdict, reason):
        sym = (self.coin_name(mint) or "?").upper() if mint else ""
        if verdict == "pass":
            if agent == "auditor":
                return f"{sym} 8/8 clean. Sent to Analyst."
            return f"{sym} {reason or 'passed'}. Sent to {self.NEXT.get(agent, 'next')}." if agent != "scanner" else f"{sym} passed. Sent to Auditor."
        return f"{sym} {verdict}: {reason}."

    def status(self, agent, line):
        """One-line status per agent for the Grok Bot status chats: status/{agent}.txt (latest) + .log (append)."""
        try:
            from common import ROOT
            import datetime as _dt, os as _os
            from pathlib import Path as _P
            d = _P(_os.environ.get("DESK_STATUS", ROOT / "status")); d.mkdir(exist_ok=True)
            t = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
            mode = self.mode()
            txt = f"{'PAPER · ' if mode == 'PAPER' else ''}{line}"
            (d / f"{agent}.txt").write_text(f"{t} {txt}\n")
            with open(d / f"{agent}.log", "a") as f:
                f.write(f"{t} {txt}\n")
        except Exception:
            pass

    def activity(self, kind, mint, agent, title, subtitle, value):
        aid = self.db.exec("INSERT INTO activity(ts,kind,mint,agent,title,subtitle,value) VALUES(?,?,?,?,?,?,?)",
                           (now(), kind, mint, agent, title, subtitle, value))
        row = {"id": aid, "ts": now(), "kind": kind, "mint": mint, "agent": agent, "title": title, "subtitle": subtitle,
               "value": value, "coin_url": links.coin_url(mint, "solana") if mint else None}
        self.bus.emit("activity", row)
        return row

    def coin_name(self, mint):
        c = self.db.coin(mint)
        return (c and (c.get("symbol") or c.get("name"))) or (mint[:6] if mint else "?")

    def write_price(self, mint, pair, writer):
        import fields as F
        p = F.num("dexscreener", pair, "price_usd")
        if p is None:
            return None
        self.db.exec("INSERT INTO prices(mint,ts,price,volume_m5,liquidity_usd,market_cap,volume_h24) VALUES(?,?,?,?,?,?,?)",
                     (mint, now(), p, F.num("dexscreener", pair, "volume_m5"), F.num("dexscreener", pair, "liquidity_usd"),
                      F.num("dexscreener", pair, "market_cap"), F.num("dexscreener", pair, "volume_h24")))
        return p

    def open_positions(self):
        return self.db.all("SELECT * FROM positions WHERE status IN ('open','exiting') ORDER BY opened_at")

    def last_price(self, mint):
        r = self.db.one("SELECT price FROM prices WHERE mint=? ORDER BY ts DESC LIMIT 1", (mint,))
        return r["price"] if r else None

    def balance(self):
        """PAPER: simulated cash + open positions marked at last polled price. LIVE: the stack I set."""
        if self.mode() == "PAPER":
            cash = float(self.db.kv_get("paper_cash", self.s("desk.paper_start_stack")))
            val = 0.0
            for p in self.db.all("SELECT * FROM positions WHERE status IN ('open','exiting') AND mode='PAPER'"):
                lp = p["last_price"] or p["entry_price"]
                val += p["size_usd"] * lp / p["entry_price"]
            return round(cash + val, 2)
        return float(self.s("desk.stack"))

    def free_stack(self):
        if self.mode() == "PAPER":
            return float(self.db.kv_get("paper_cash", self.s("desk.paper_start_stack")))
        used = sum(p["size_usd"] for p in self.open_positions() if p["mode"] == "LIVE")
        return float(self.s("desk.stack")) - used

    def stack(self):
        return self.balance() if self.mode() == "PAPER" else float(self.s("desk.stack"))

    def night(self):
        r = self.db.one("SELECT * FROM nights WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1")
        return dict(r) if r else None

    def start_night(self):
        nid = self.db.exec("INSERT INTO nights(started_at,mode,start_balance) VALUES(?,?,?)", (now(), self.mode(), self.balance()))
        return nid

    def end_night(self):
        n = self.night()
        if n:
            self.db.exec("UPDATE nights SET ended_at=?, end_balance=? WHERE id=?", (now(), self.balance(), n["id"]))
        return n

    def night_start_ts(self):
        n = self.night()
        return n["started_at"] if n else now() - 86400

    def full_paper_nights(self):
        r = self.db.one("SELECT COUNT(*) c FROM nights WHERE mode='PAPER' AND ended_at IS NOT NULL AND ended_at-started_at >= 6*3600")
        return r["c"]

    def event(self, kind, detail=""):
        self.db.exec("INSERT INTO events(ts,kind,detail) VALUES(?,?,?)", (now(), kind, detail))
