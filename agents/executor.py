"""AGENT 4 · EXECUTOR (v2). Waits for the dip, re-checks, then buys; takes profit (2x -> sell 50%, then a 40%
trail). Clicks only through browser.py (desk.autoclick). Never picks a coin, never changes Brain's size.

PAPER: fills at the DexScreener price (with desk.autoclick=dryrun|on the lane also opens the coin, types the
amount, reads the quote, screenshots, and does NOT press the button).
LIVE + autoclick on (armed after a verified $2 test): browser.py clicks Buy/Sell and verify.py checks it.
LIVE + autoclick off/dryrun: the v1 flow, a "Buy on FOMO" push Christian taps himself."""
import asyncio, datetime as dt
import fields as F
import fees
import links
import smart_money as SM
import journal as JR
from common import now, iso, get_logger


def dip_decision(prices, price, buys5, sells5, s):
    """v2 DIP ENTRY. prices = prices of the last dip_window_min (any order, the current one may be included).
    Returns (action, depth_pct, high10): action = wait | buy | crash."""
    pts = [p for p in prices if p] + [price]
    high = max(pts)
    depth = 100 * (1 - price / high) if high else 0.0
    if depth > s("executor.crash_pct"):
        return "crash", round(depth, 1), high
    if depth >= s("executor.dip_pct"):
        if (sells5 or 0) <= s("executor.dip_sell_ratio") * (buys5 or 0):
            return "buy", round(depth, 1), high
        return "wait", round(depth, 1), high       # falling with sellers still running
    return "wait", round(depth, 1), high


def _spawn(coro):
    try:
        return asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        coro.close()
        return None


# kept for old callers/tests: v1 ticket sizing (unused by the v2 pipeline, Brain sizes)
def size_ticket(stack, free, liquidity_usd, s):
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
        self.waiting: dict[int, dict] = {}     # signal id -> item, orders waiting for their dip
        for r in self.d.db.all("SELECT mint FROM signals WHERE ts>=?", (self.d.night_start_ts(),)):
            self.pushed.add(r["mint"])
        # a restart drops waiting orders (their dip context is gone): free the cash, say so
        for r in self.d.db.all("SELECT id, mint FROM signals WHERE status='waiting'"):
            self.d.db.exec("UPDATE signals SET status='skipped', reason='restart while waiting' WHERE id=?", (r["id"],))

    # ---------- from Brain
    async def handle(self, item):
        scan, verdict, brain = item["scan"], item["verdict"], item.get("brain") or {}
        mint = scan["mint"]
        name = self.d.coin_name(mint)
        if mint in self.pushed:
            return None
        if self.d.db.one("SELECT 1 FROM skips WHERE mint=?", (mint,)):
            return None
        if any(p["mint"] == mint for p in self.d.open_positions()):
            return None                           # never a 2nd buy on an open position
        size = brain.get("sizeUsd")
        if not size:
            return None
        self.pushed.add(mint)
        mode = self.d.mode()
        link = links.coin_url(mint, "solana")
        sid = self.d.db.exec("INSERT INTO signals(mint,ts,price,size_usd,stack_pct,link,mode,status,score,cap_hit,waiting_since) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                             (mint, now(), verdict.get("price"), size, brain.get("pctOfCash"), link, mode, "waiting",
                              verdict.get("score"), brain.get("capHit"), now()))
        self.waiting[sid] = {**item, "sid": sid, "since": now()}
        self.d.cards["executor"] = {"mint": mint, "size": size, "pct": brain.get("pctOfCash"), "state": "waiting", "ts": now()}
        self.d.decision("executor", mint, "waiting", f"dip -{self.d.s('executor.dip_pct'):g}%",
                        line=f"{name.upper()} ${size:.2f} waiting for a dip -{self.d.s('executor.dip_pct'):g}% under its 10m high (max {self.d.s('executor.dip_wait_min'):g} min).")
        self.d.bus.emit("signal", {"mint": mint, "signal_id": sid, "status": "waiting", "sizeUsd": size, "link": link})
        self.d.bus.risk.put_nowait(None)          # wake Risk so the mint joins its 5s poll
        if SM.enabled():
            asyncio.create_task(self.smart_money(mint, sid))
        return {"status": "waiting", "signal_id": sid}

    async def smart_money(self, mint, sid):
        """Optional Nansen smart-money holders (nansen-cli, read only). Log + gate only if executor.nansen_min_sm>0."""
        sm = await SM.holders(self.d.client, mint)
        self.waiting.get(sid, {})["smart_money"] = sm
        if sm is None:
            return
        self.log.info("%s nansen smart money holders=%s usd=%s", mint, sm["count"], sm["usd"])
        mn = self.d.s("executor.nansen_min_sm")
        if mn > 0 and sm["count"] < mn and sid in self.waiting:
            self.drop(sid, f"Nansen smart-money holders {sm['count']} < {mn}")

    def waiting_mints(self):
        return sorted({w["scan"]["mint"] for w in self.waiting.values()})

    # ---------- every Risk poll
    async def on_poll(self, pairs: dict):
        for sid, w in list(self.waiting.items()):
            mint = w["scan"]["mint"]
            pair = pairs.get(mint)
            if now() - w["since"] >= 60 * self.d.s("executor.dip_wait_min"):
                self.drop(sid, "no dip"); continue
            if self.d.db.kv_get("night.locked") == "1" or not self.d.in_night():
                self.drop(sid, "night over"); continue
            if not pair:
                continue
            price = F.num("dexscreener", pair, "price_usd")
            if not price:
                continue
            since = now() - 60 * self.d.s("executor.dip_window_min")
            hist = [r["price"] for r in self.d.db.all("SELECT price FROM prices WHERE mint=? AND ts>=?", (mint, since))]
            act, depth, high = dip_decision(hist, price, F.num("dexscreener", pair, "buys_m5"), F.num("dexscreener", pair, "sells_m5"), self.d.s)
            self.d.db.exec("UPDATE signals SET dip_high=?, dip_depth_pct=? WHERE id=?", (high, depth, sid))
            if act == "crash":
                self.drop(sid, f"crash -{depth:.0f}%")
            elif act == "buy":
                self.waiting.pop(sid, None)
                await self.buy(sid, w, pair, price, depth)

    def drop(self, sid, reason):
        w = self.waiting.pop(sid, None)
        if not w:
            return
        mint = w["scan"]["mint"]
        name = self.d.coin_name(mint)
        self.d.db.exec("UPDATE signals SET status='skipped', reason=? WHERE id=?", (reason, sid))
        self.d.decision("executor", mint, "skip", reason, line=f"{name.upper()} skipped: {reason}.")
        self.d.activity("rejected", mint, "executor", f"Skipped {name}", f"Executor · {reason}", "Skipped")
        self.log.info("signal %s %s skipped: %s", sid, mint, reason)

    async def recheck(self, w, pair, price):
        scan, verdict, brain = w["scan"], w["verdict"], w.get("brain") or {}
        s = self.d.s
        liq = F.num("dexscreener", pair, "liquidity_usd")
        if scan.get("liquidityUsd") and liq is not None and liq < scan["liquidityUsd"] * (1 - s("executor.recheck_liq_drop_pct") / 100):
            return "liquidity dropping"
        if verdict.get("price") and price > verdict["price"] * (1 + s("executor.recheck_price_up_pct") / 100):
            return "ran before the click"
        cash = self.d.free_cash() + (brain.get("sizeUsd") or 0)   # its own reserve is being released now
        if cash < (brain.get("sizeUsd") or 0):
            return "no free cash"
        dev = ((w.get("audit") or {}).get("_ctx") or {}).get("dev_bal")
        creator = (self.d.db.coin(scan["mint"]) or {}).get("creator")
        if dev is not None and creator:
            try:
                now_bal = await self.d.rpc.owner_balance(creator, scan["mint"])
                if now_bal < dev:
                    return "dev sold while we waited"
            except Exception:
                pass
        return None

    async def buy(self, sid, w, pair, price, depth):
        scan, brain = w["scan"], w.get("brain") or {}
        mint = scan["mint"]
        name = self.d.coin_name(mint)
        size = brain["sizeUsd"]
        reason = await self.recheck(w, pair, price)
        if reason:
            self.waiting[sid] = w
            return self.drop(sid, reason)
        mode = self.d.mode()
        link = links.coin_url(mint, "solana")
        self.d.db.exec("UPDATE signals SET status='sent', price=? WHERE id=?", (price, sid))
        self.d.cards["executor"] = {"mint": mint, "size": size, "pct": brain.get("pctOfCash"), "state": "executing", "ts": now()}
        self.log.info("signal %s %s dip -%.1f%% -> BUY $%.2f mode=%s autoclick=%s", sid, mint, depth, size, mode, self.d.s("desk.autoclick"))
        lane = self.d.lane
        ac = self.d.s("desk.autoclick")
        if mode == "PAPER":
            if lane and ac in ("dryrun", "on"):
                res = await lane.order("buy", mint, size, bot="executor", reason="dip entry", dry=True, symbol=scan.get("symbol"))
                self.log.info("signal %s paper lane: %s", sid, {k: res.get(k) for k in ("status", "quote_text", "fee_text", "error")})
            return await self.fill_and_push(sid)
        # LIVE
        if lane and ac == "on" and lane.armed():
            res = await lane.order("buy", mint, size, bot="executor", reason="dip entry", dry=False, symbol=scan.get("symbol"))
            self.d.db.exec("UPDATE signals SET order_id=? WHERE id=?", (res.get("order_id"), sid))
            if res.get("status") == "done":
                return await self.fill_and_push(sid, fill_usd=res.get("fill_usd"))
            if res.get("screen_ok"):
                pid = self.fill(sid, fill_usd=res.get("fill_usd"))   # screen says Bought: Risk must guard it anyway
                await self.push(f"Unverified: {name}, check FOMO", mint, [("Open on FOMO", link)], kind="alert")
                return pid
            self.d.db.exec("UPDATE signals SET status='failed', reason=? WHERE id=?", (res.get("error") or "click failed", sid))
            self.d.decision("executor", mint, "failed", res.get("error") or "click failed")
            return None
        # LIVE manual (v1): Christian taps Buy on FOMO himself
        score = w["verdict"].get("score")
        text = (f"Buy {name} · ${size:.2f} · {brain.get('pctOfCash') or 0:g}% of cash · dip -{depth:.0f}%\n"
                f"8/8 · score {score} · stop -{self.d.s('risk.stop_pct'):g}% · TP {self.d.s('executor.tp_x'):g}x · trail {self.d.s('executor.trail_pct'):g}%")
        ok = await self.push(text, mint, [("Buy on FOMO", link), ("Bought", f"bought:{sid}"), ("Skip", f"skip:{sid}")], kind="buy")
        if not ok:
            self.d.db.exec("UPDATE signals SET status='missed', reason='push failed' WHERE id=?", (sid,))
            return None
        asyncio.create_task(self.expire(sid))
        return None

    def fill(self, sid, fill_usd=None):
        sig = self.d.db.one("SELECT * FROM signals WHERE id=?", (sid,))
        if not sig or sig["status"] not in ("sent",):
            return None
        mint = sig["mint"]
        stop_pct = self.d.s("risk.stop_pct")
        size = float(fill_usd or sig["size_usd"])
        price = sig["price"]
        fee = fees.side_fee(size, self.d.s("desk.fees_ref_discount"), self.d.s("desk.fee_pct"))
        tokens = size / price
        creator = (self.d.db.coin(mint) or {}).get("creator")
        pid = self.d.db.exec("INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,trail_active,mode,stop_pct,status,signal_id,last_price,tokens,size_open,fees_usd,realized_usd,tp_done) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (mint, now(), price, size, price, price * (1 - stop_pct / 100), 0, sig["mode"], stop_pct, "open", sid, price, tokens, size, fee, 0, 0))
        JR.record(self.d, sig["mode"], mint, "Buy", tokens, price, fee)
        self.d.db.exec("UPDATE signals SET status='bought' WHERE id=?", (sid,))
        if sig["mode"] == "PAPER":
            cash = float(self.d.db.kv_get("paper_cash")) - size - fee
            self.d.db.kv_set("paper_cash", round(cash, 4))
        if creator:
            _spawn(self._dev_bal(pid, creator, mint))
        name = self.d.coin_name(mint)
        t = dt.datetime.now().strftime("%H:%M")
        pct = sig["stack_pct"] or 0
        self.d.activity("bought", mint, "executor", f"Bought {name}", f"Executor · {t}", f"${size:.2f} · {pct:g}% of cash")
        self.d.decision("executor", mint, "bought", f"${size:.2f}",
                        line=f"Bought {name.upper()} · ${size:.2f} · {pct:g}% of cash. Handed to Risk (stop -{stop_pct:g}%).")
        self.d.cards["executor"] = {"mint": mint, "size": size, "pct": pct, "state": "filled", "ts": now()}
        self.d.bus.emit("fill", {"mint": mint, "position_id": pid, "size": size, "price": price, "mode": sig["mode"]})
        self.d.bus.risk.put_nowait(pid)
        return pid

    async def fill_and_push(self, sid, fill_usd=None):
        pid = self.fill(sid, fill_usd=fill_usd)
        if pid:
            sig = self.d.db.one("SELECT * FROM signals WHERE id=?", (sid,))
            pos = self.d.db.one("SELECT size_usd FROM positions WHERE id=?", (pid,))
            pre = "PAPER · " if sig["mode"] == "PAPER" else ""
            await self.push(f"{pre}Bought {self.d.coin_name(sig['mint'])} · ${pos['size_usd']:.2f} · Executor", sig["mint"],
                            [("Open on FOMO", links.coin_url(sig["mint"], "solana"))], kind="bought")
        return pid

    async def _dev_bal(self, pid, creator, mint):
        try:
            b = await self.d.rpc.owner_balance(creator, mint)
            self.d.db.exec("UPDATE positions SET creator_bal_at_buy=? WHERE id=?", (b, pid))
        except Exception:
            pass

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
        if sig["status"] in ("sent", "waiting"):
            self.waiting.pop(sid, None)
            self.d.db.exec("UPDATE signals SET status='skipped', reason='skip tapped' WHERE id=?", (sid,))

    async def push(self, text, mint, buttons, kind="info"):
        if self.d.notifier:
            return await self.d.notifier.push(text, mint, kind=kind, buttons=buttons)
        return False

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
