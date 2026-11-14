"""AGENT 4 · EXECUTOR. Arithmetic + 1 button. Never places an order, never touches funds."""
import asyncio, datetime as dt
import fields as F
import links
from common import now, iso, get_logger


def size_ticket(stack, free, liquidity_usd, s):
    """Returns (size or None, raw, cap_hit, skip_reason)."""
    raw = stack * s("executor.stack_pct") / 100
    size, cap = raw, "stack_pct"
    pool_cap = (liquidity_usd or 0) * s("executor.max_pool_pct") / 100
    if size > pool_cap:
        size, cap = pool_cap, "max_pool_pct"
    mt = s("executor.min_ticket_usd")
    if size < mt:
        if s("executor.below_min") == "bump":
            size, cap = mt, "bumped"
        else:
            return None, raw, cap, f"under ${mt:.2f}"
    if size > free:
        return None, raw, cap, "no free stack"
    return round(size, 2), raw, cap, None


class Executor:
    name = "executor"

    def __init__(self, desk):
        self.d = desk
        self.log = get_logger("executor")
        self.pushed: set[str] = set()
        for r in self.d.db.all("SELECT mint FROM signals WHERE ts>=?", (self.d.night_start_ts(),)):
            self.pushed.add(r["mint"])

    async def handle(self, item):
        scan, verdict = item["scan"], item["verdict"]
        mint = scan["mint"]
        name = self.d.coin_name(mint)
        if mint in self.pushed:
            return None          # 1 push per coin per night
        if self.d.db.one("SELECT 1 FROM skips WHERE mint=?", (mint,)):
            return None
        if any(p["mint"] == mint for p in self.d.open_positions()):
            return None          # never a 2nd buy on an open position
        mode = self.d.mode()
        link = links.coin_url(mint, "solana")
        try:
            pair = (await self.d.dex.tokens([mint])).get(mint)
        except Exception:
            pair = None
        price = F.num("dexscreener", pair, "price_usd") if pair else None
        liq = F.num("dexscreener", pair, "liquidity_usd") if pair else None
        stack, free = self.d.stack(), self.d.free_stack()
        size, raw, cap, reason = size_ticket(stack, free, liq, self.d.s)
        if price is None:
            reason = "no price"
        elif reason is None and scan.get("liquidityUsd") and liq < scan["liquidityUsd"] * (1 - self.d.s("executor.recheck_liq_drop_pct") / 100):
            reason = "liquidity dropping"
        elif reason is None and verdict.get("price") and price > verdict["price"] * (1 + self.d.s("executor.recheck_price_up_pct") / 100):
            reason = "ran before the push"
        pct = round(100 * (size or 0) / stack, 1) if stack else 0
        out = {"agent": "executor", "mint": mint, "signalPrice": price, "sizeUsd": size, "stackPct": pct, "link": link,
               "mode": mode, "status": "skipped" if reason else "sent", "reason": reason}
        self.log.info("%s stack=%.2f raw=%.2f cap=%s final=%s mode=%s status=%s reason=%s link=%s",
                      mint, stack, raw, cap, size, mode, out["status"], reason, link)
        if reason:
            self.pushed.add(mint)
            self.d.db.exec("INSERT INTO signals(mint,ts,price,size_usd,stack_pct,link,mode,status,reason) VALUES(?,?,?,?,?,?,?,?,?)",
                           (mint, now(), price, size, pct, link, mode, "skipped", reason))
            self.d.decision("executor", mint, "skip", reason, line=f"{name.upper()} skipped: {reason}.")
            self.d.bus.emit("signal", out)
            return out
        self.pushed.add(mint)
        sid = self.d.db.exec("INSERT INTO signals(mint,ts,price,size_usd,stack_pct,link,mode,status) VALUES(?,?,?,?,?,?,?,?)",
                             (mint, now(), price, size, pct, link, mode, "sent"))
        self.d.cards["executor"] = {"mint": mint, "size": size, "pct": pct, "state": "executing", "ts": now()}
        self.d.bus.emit("signal", {**out, "signal_id": sid})
        stop, trail = self.d.s("risk.stop_pct"), self.d.s("risk.trail_pct")
        score = verdict.get("score")
        text = (f"{'PAPER · ' if mode == 'PAPER' else ''}Buy {name} · ${size:.2f} · {pct:g}% of stack\n"
                f"Auditor 8/8 · Analyst {score} · stop -{stop:g}% · trail {trail:g}%")
        ok = False
        if self.d.notifier:
            ok = await self.d.notifier.push(text, mint, kind="buy", buttons=[("Buy on FOMO", link), ("Bought", f"bought:{sid}"), ("Skip", f"skip:{sid}")])
        if not ok:
            self.log.info("%s push failed", mint)
            if mode == "LIVE":
                self.d.db.exec("UPDATE signals SET status='missed', reason='push failed' WHERE id=?", (sid,))
                return {**out, "status": "missed", "reason": "push failed"}
        if mode == "PAPER":
            await asyncio.sleep(1.2)   # the PAPER bar runs 1.2s in the app
            self.fill(sid)
            out["status"] = "bought"
        else:
            asyncio.create_task(self.expire(sid))
        return out

    def fill(self, sid):
        sig = self.d.db.one("SELECT * FROM signals WHERE id=?", (sid,))
        if not sig or sig["status"] not in ("sent",):
            return None
        mint = sig["mint"]
        stop_pct = self.d.s("risk.stop_pct")
        pid = self.d.db.exec("INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,trail_active,mode,stop_pct,status,signal_id,last_price) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                             (mint, now(), sig["price"], sig["size_usd"], sig["price"], sig["price"] * (1 - stop_pct / 100), 0, sig["mode"], stop_pct, "open", sid, sig["price"]))
        self.d.db.exec("UPDATE signals SET status='bought' WHERE id=?", (sid,))
        if sig["mode"] == "PAPER":
            cash = float(self.d.db.kv_get("paper_cash")) - sig["size_usd"]
            self.d.db.kv_set("paper_cash", round(cash, 4))
        name = self.d.coin_name(mint)
        t = dt.datetime.now().strftime("%H:%M")
        self.d.activity("bought", mint, "executor", f"Bought {name}", f"Executor · {t}", f"${sig['size_usd']:.2f} · {sig['stack_pct']:g}% of stack")
        self.d.decision("executor", mint, "bought", f"${sig['size_usd']:.2f}",
                        line=f"Bought {name.upper()} · ${sig['size_usd']:.2f} · {sig['stack_pct']:g}% of stack. Handed to Risk.")
        self.d.cards["executor"] = {"mint": mint, "size": sig["size_usd"], "pct": sig["stack_pct"], "state": "filled", "ts": now()}
        self.d.bus.emit("fill", {"mint": mint, "position_id": pid, "size": sig["size_usd"], "price": sig["price"], "mode": sig["mode"]})
        self.d.bus.risk.put_nowait(pid)
        return pid

    async def expire(self, sid):
        await asyncio.sleep(60 * self.d.s("executor.confirm_window_min"))
        sig = self.d.db.one("SELECT * FROM signals WHERE id=?", (sid,))
        if sig and sig["status"] == "sent":
            self.d.db.exec("UPDATE signals SET status='missed' WHERE id=?", (sid,))
            self.d.decision("executor", sig["mint"], "missed", "no tap")

    def skip(self, sid):
        sig = self.d.db.one("SELECT * FROM signals WHERE id=?", (sid,))
        if not sig:
            return
        self.d.db.exec("INSERT OR REPLACE INTO skips(mint,until) VALUES(?,?)", (sig["mint"], now() + 86400))
        if sig["status"] == "sent":
            self.d.db.exec("UPDATE signals SET status='skipped', reason='skip tapped' WHERE id=?", (sid,))

    async def run(self):
        while True:
            self.d.heartbeat("executor")
            try:
                item = await asyncio.wait_for(self.d.bus.executor.get(), timeout=30)
            except asyncio.TimeoutError:
                continue
            while self.d.paused("executor"):
                self.d.heartbeat("executor"); await asyncio.sleep(5)
            try:
                await self.handle(item)
            except Exception as e:
                self.log.exception("executor crash: %s", e)
