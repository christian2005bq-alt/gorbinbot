"""AGENT 5 · RISK (v2). Polls every open (and dip-waiting) mint in 1 DexScreener call every [5]s and cuts losers.
Rules each poll, in order: stop -25% · dead money (3h under +5%) · pulled liquidity (-> 0 or -80% in 1 poll) ·
take profit 2x sells 50% (Executor's rule, same poll) · then a 40% trail off the peak sells the rest.
Every [60]s: dev dumping (creator balance -50% since the buy). 12 polls without a price -> sell.
The stop is set at the buy and only ever tightens. Sells jump the click lane."""
import asyncio
import fields as F
import fees
import links
import journal as JR
import sources as S
from common import now, iso, get_logger


def effective_stop_pct(pos_stop_pct, setting_stop_pct):
    """A new stop setting applies to an open position only if it is tighter."""
    return min(pos_stop_pct, setting_stop_pct)


def evaluate(pos: dict, price: float, t: float, s, liq=None) -> tuple[dict, tuple | None]:
    """Apply the v2 rules in order. Returns (updated fields, (sell_pct, reason) or None)."""
    entry = pos["entry_price"]
    stop_pct = effective_stop_pct(pos["stop_pct"], s("risk.stop_pct"))
    peak = max(pos.get("peak_price") or entry, price)
    tp_done = bool(pos.get("tp_done"))
    upd = {"peak_price": peak, "stop_pct": stop_pct, "stop_price": entry * (1 - stop_pct / 100), "last_price": price}
    if liq is not None:
        upd["last_liq"] = liq
    if price <= entry * (1 - stop_pct / 100):
        return upd, (100, "stop")
    if t - pos["opened_at"] >= s("risk.timeout_h") * 3600 and price < entry * (1 + s("risk.timeout_min_gain_pct") / 100):
        return upd, (100, "dead money")
    last_liq = pos.get("last_liq")
    if liq is not None and (liq <= 0 or (last_liq and liq < last_liq * (1 - s("risk.pulled_drop_pct") / 100))):
        return upd, (100, "pulled")
    if not tp_done and price >= entry * s("executor.tp_x"):
        upd["tp_done"] = 1
        upd["trail_active"] = 1
        upd["peak_price"] = price
        return upd, (s("executor.tp_sell_pct"), "take profit")
    if tp_done:
        upd["trail_active"] = 1
        if price <= peak * (1 - s("executor.trail_pct") / 100):
            return upd, (100, "trail")
    return upd, None


def exit_line(pos, s):
    """Current exit line drawn on the Coin screen: the stop, or the 40% trail once take profit is done."""
    entry = pos["entry_price"]
    stop_pct = effective_stop_pct(pos["stop_pct"], s("risk.stop_pct"))
    line = entry * (1 - stop_pct / 100)
    if pos.get("tp_done") or pos.get("trail_active"):
        line = max(line, (pos.get("peak_price") or entry) * (1 - s("executor.trail_pct") / 100))
    return line


class Risk:
    name = "risk"

    def __init__(self, desk):
        self.d = desk
        self.log = get_logger("risk")
        self.last_exit = None
        self.fail_count: dict[int, int] = {}

    async def poll_once(self):
        pos = self.d.open_positions()
        ex = self.d.agents.get("executor")
        waiting = ex.waiting_mints() if ex and hasattr(ex, "waiting_mints") else []
        mints = sorted({p["mint"] for p in pos} | set(waiting))
        if not mints:
            return
        pairs = await self.d.dex.tokens(mints)    # open + waiting mints in 1 call
        for m, pair in pairs.items():
            self.d.last_pairs[m] = pair
            if m in waiting and m not in {p["mint"] for p in pos}:
                self.d.write_price(m, pair, "risk")
        for p in pos:
            pair = pairs.get(p["mint"])
            price = self.d.write_price(p["mint"], pair, "risk") if pair else None
            await self.step(p, price, F.num("dexscreener", pair, "liquidity_usd") if pair else None)
        if ex and waiting:
            await ex.on_poll(pairs)

    async def step(self, p, price, liq):
        name = self.d.coin_name(p["mint"])
        link = links.coin_url(p["mint"], "solana")
        if p["status"] == "exiting":
            if p["exit_pushed_at"] and now() - p["exit_pushed_at"] >= 60 * self.d.s("risk.confirm_window_min") and not self.d.db.kv_get(f"reminded.{p['id']}"):
                self.d.db.kv_set(f"reminded.{p['id']}", "1")
                await self.push(f"{name} still open · sell it by hand now", p["mint"], [("Sell on FOMO", link), ("Sold", f"sold:{p['id']}")])
            return
        if price is None:
            n = (p["no_price_polls"] or 0) + 1
            self.d.db.exec("UPDATE positions SET no_price_polls=? WHERE id=?", (n, p["id"]))
            self.log.info("pos %s %s no price (%d)", p["id"], p["mint"], n)
            if n >= self.d.s("risk.no_price_polls"):
                return await self.sell(p, 100, "no price", p["last_price"] or p["entry_price"])
            return
        upd, action = evaluate(p, price, now(), self.d.s, liq)
        upd["no_price_polls"] = 0
        sets = ", ".join(f"{k}=?" for k in upd)
        self.d.db.exec(f"UPDATE positions SET {sets} WHERE id=?", (*upd.values(), p["id"]))
        self.log.info("pos %s %s price=%.10g peak=%.10g stop=%.10g tp_done=%s action=%s", p["id"], p["mint"], price,
                      upd["peak_price"], upd["stop_price"], upd.get("tp_done", p.get("tp_done")), action or "hold")
        self.d.cards["risk"] = {"state": "guarding"}
        p = {**p, **upd}
        if action:
            return await self.sell(p, action[0], action[1], price)
        if now() - (p.get("last_dev_check") or 0) >= 60:
            await self.dev_check(p, price)

    async def dev_check(self, p, price):
        self.d.db.exec("UPDATE positions SET last_dev_check=? WHERE id=?", (now(), p["id"]))
        b0 = p.get("creator_bal_at_buy")
        creator = (self.d.db.coin(p["mint"]) or {}).get("creator")
        if not b0 or not creator:
            return
        try:
            b = await self.d.rpc.owner_balance(creator, p["mint"])
        except Exception:
            return
        if b < b0 * (1 - self.d.s("risk.dev_dump_pct") / 100):
            await self.sell(p, 100, "dev dumping", price)

    async def sell_all(self, reason="lock time"):
        for p in self.d.open_positions():
            if p["status"] == "open":
                await self.sell(p, 100, reason, p["last_price"] or p["entry_price"])

    async def sell(self, p, pct, reason, price):
        """Sell pct of a position. PAPER: fill at the DexScreener price that fired it minus fees.py.
        LIVE + armed lane: browser.py clicks it (jumps the lane), verify.py checks it. LIVE manual: push."""
        mode = p["mode"]
        name = self.d.coin_name(p["mint"])
        link = links.coin_url(p["mint"], "solana")
        lane = self.d.lane
        ac = self.d.s("desk.autoclick")
        bot = "executor" if reason in ("take profit", "trail") else "risk"
        if mode == "PAPER":
            if lane and ac in ("dryrun", "on"):
                asyncio.create_task(lane.order("sell", p["mint"], None, pct=pct, bot=bot, reason=reason, dry=True, priority=True))
            return await self.pushed(self.realize(p, pct, price, reason))
        if lane and ac == "on" and lane.armed():
            res = await lane.order("sell", p["mint"], None, pct=pct, bot=bot, reason=reason, dry=False, priority=True)
            if res.get("status") == "done" or res.get("screen_ok"):
                out = await self.pushed(self.realize(p, pct, price, reason, fill_usd=res.get("fill_usd")))
                if res.get("status") != "done":
                    await self.push(f"Unverified: {name}, check FOMO", p["mint"], [("Open on FOMO", link)], kind="alert")
                return out
            n = self.fail_count.get(p["id"], 0) + 1
            self.fail_count[p["id"]] = n
            if n == 2:
                await self.push(f"Sell {name} by hand now", p["mint"], [("Sell on FOMO", link)], kind="alert")
            return None                                 # retried on the next poll
        # LIVE manual: Christian sells on FOMO himself
        if pct < 100:
            self.d.db.exec("UPDATE positions SET tp_done=1, trail_active=1 WHERE id=?", (p["id"],))
            await self.push(f"Take profit {name}: sell {pct:g}% now ({price / p['entry_price']:.1f}x)", p["mint"], [("Sell on FOMO", link)], kind="exit")
            return None
        self.d.db.exec("UPDATE positions SET status='exiting', exit_price=?, exit_reason=?, exit_pushed_at=? WHERE id=?",
                       (price, reason, now(), p["id"]))
        await self.push(f"Sell {name} 100% now · {reason} · {100 * (price / p['entry_price'] - 1):+.1f}%", p["mint"],
                        [("Sell on FOMO", link), ("Sold", f"sold:{p['id']}")], kind="exit")
        return None

    def realize(self, p, pct, price, reason, fill_usd=None):
        mode = p["mode"]
        name = self.d.coin_name(p["mint"])
        link = links.coin_url(p["mint"], "solana")
        entry = p["entry_price"]
        tokens = p.get("tokens") or (p["size_usd"] / entry)
        size_open = p.get("size_open") or p["size_usd"]
        frac = min(1.0, pct / 100)
        sold_tokens = tokens * frac
        gross = float(fill_usd) if fill_usd else sold_tokens * price
        fee = fees.side_fee(gross, self.d.s("desk.fees_ref_discount"), self.d.s("desk.fee_pct"))
        net = gross - fee
        cost = size_open * frac
        realized = (p.get("realized_usd") or 0) + net
        fees_total = (p.get("fees_usd") or 0) + fee
        leg_pnl = round(net - cost, 2)
        pct_move = round(100 * (price / entry - 1), 2)
        closed = frac >= 0.999 or (tokens - sold_tokens) * price < 0.01
        JR.record(self.d, mode, p["mint"], "Sell", sold_tokens, (gross / sold_tokens) if sold_tokens else price, fee)
        if mode == "PAPER":
            cash = float(self.d.db.kv_get("paper_cash")) + net
            self.d.db.kv_set("paper_cash", round(cash, 4))
        if closed:
            # total pnl = everything received - what went in - the entry fee
            entry_fee = fees.side_fee(p["size_usd"], self.d.s("desk.fees_ref_discount"), self.d.s("desk.fee_pct"))
            pnl = round(realized - p["size_usd"] - entry_fee, 2)
            self.d.db.exec("UPDATE positions SET status='closed', exit_price=?, exit_reason=?, pnl_usd=?, fees_usd=?, closed_at=?, tokens=0, size_open=0, realized_usd=?, exit_pushed_at=? WHERE id=?",
                           (price, reason, pnl, fees_total, now(), realized, now(), p["id"]))
        else:
            pnl = leg_pnl
            self.d.db.exec("UPDATE positions SET tokens=?, size_open=?, realized_usd=?, fees_usd=? WHERE id=?",
                           (tokens - sold_tokens, size_open - cost, realized, fees_total, p["id"]))
        pre = "PAPER · " if mode == "PAPER" else ""
        sign = "+" if pnl >= 0 else "-"
        stop_pct = p["stop_pct"]
        if reason == "stop":
            text = f"{pre}Stopped {name} · -{stop_pct:g}% · -${abs(pnl):.2f}"
            act = ("stopped", f"Stopped {name}", f"Risk · -{stop_pct:g}% stop", f"-${abs(pnl):.2f}")
        elif reason == "take profit":
            text = f"{pre}Sold {name} · {sign}${abs(pnl):.2f} ({pct_move:+.0f}%) · take profit {pct:g}%"
            act = ("sold", f"Sold {name}", f"Executor · take profit {pct:g}%", f"{sign}${abs(pnl):.2f} · {pct_move:+.0f}%")
        elif reason == "trail":
            text = f"{pre}Sold {name} · {sign}${abs(pnl):.2f} ({pct_move:+.0f}%) · trail"
            act = ("sold", f"Sold {name}", "Executor · trail", f"{sign}${abs(pnl):.2f} · {pct_move:+.0f}%")
        else:
            kind = "stopped" if reason in ("pulled", "dev dumping", "no price", "FOMO warns") else "sold"
            text = f"{pre}{'Stopped' if kind == 'stopped' else 'Sold'} {name} · {reason} · {sign}${abs(pnl):.2f} ({pct_move:+.1f}%)"
            act = (kind, f"{'Stopped' if kind == 'stopped' else 'Sold'} {name}", f"Risk · {reason}", f"{sign}${abs(pnl):.2f} · {pct_move:+.1f}%")
        agent = "executor" if reason in ("take profit", "trail") else "risk"
        self.d.activity(act[0], p["mint"], agent, act[1], act[2], act[3])
        self.d.decision(agent, p["mint"], reason, text.replace(pre, ""), line=text.replace(pre, "") + ".")
        if closed:
            self.last_exit = {"stop": "Stopped", "trail": "Trailed out", "dead money": "Timed out"}.get(reason, "Sold")
            self.d.cards["risk"] = {"state": "idle", "last": self.last_exit}
        out = {"bot": "risk", "agent": agent, "mint": p["mint"], "name": name, "ts": iso(), "reason": reason, "entryPrice": entry,
               "exitPrice": price, "pnlUsd": pnl, "pct": pct_move, "soldPct": pct, "feesUsd": round(fee, 4), "stopPct": stop_pct,
               "mode": mode, "status": "closed" if closed else "open", "link": link}
        self.d.bus.emit("exit", out)
        out["_push"] = text
        return out

    async def pushed(self, out):
        if out and out.get("_push"):
            await self.push(out.pop("_push"), out["mint"], [("Open on FOMO", out["link"])], kind="exit")
        return out

    def sold(self, pid):
        """Manual LIVE: Christian tapped Sold."""
        p = self.d.db.one("SELECT * FROM positions WHERE id=?", (pid,))
        if p and p["status"] == "exiting":
            p = dict(p)
            p["status"] = "open"
            out = self.realize(p, 100, p["exit_price"] or p["last_price"] or p["entry_price"], p["exit_reason"] or "sold")
            out.pop("_push", None)

    async def push(self, text, mint, buttons, kind="risk"):
        if self.d.notifier:
            return await self.d.notifier.push(text, mint, kind=kind, buttons=buttons)
        return False

    async def run(self):
        while True:
            self.d.heartbeat("risk")
            try:
                if not self.d.paused("risk") or self.d.open_positions():
                    await self.poll_once()
            except S.RateLimited:
                self.log.info("dexscreener 429, back off 30s (missed polls logged)")
                await asyncio.sleep(30)
            except Exception as e:
                self.log.info("poll error %s", e)
            try:
                await asyncio.wait_for(self.d.bus.risk.get(), timeout=self.d.s("risk.poll_s"))
            except asyncio.TimeoutError:
                pass
