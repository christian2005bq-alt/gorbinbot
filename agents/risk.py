"""AGENT 5 · RISK. Exits by rule, sends the Sell button. Never moves a stop down."""
import asyncio
import fields as F
import fees
import links
import sources as S
from common import now, iso, get_logger


def effective_stop_pct(pos_stop_pct, setting_stop_pct):
    """A new stop setting applies to an open position only if it is tighter."""
    return min(pos_stop_pct, setting_stop_pct)


def evaluate(pos: dict, price: float, t: float, s) -> tuple[dict, str | None]:
    """Apply RULES in order. Returns (updated fields, exit reason or None)."""
    entry = pos["entry_price"]
    stop_pct = effective_stop_pct(pos["stop_pct"], s("risk.stop_pct"))
    peak = max(pos["peak_price"] or entry, price)
    trail_active = bool(pos["trail_active"])
    upd = {"peak_price": peak, "stop_pct": stop_pct, "stop_price": entry * (1 - stop_pct / 100), "last_price": price}
    if price <= entry * (1 - stop_pct / 100):
        return upd, "stop"
    if price >= entry * (1 + s("risk.trail_start_pct") / 100):
        trail_active = True
    upd["trail_active"] = int(trail_active)
    if trail_active and price <= peak * (1 - s("risk.trail_pct") / 100):
        return upd, "trail"
    if t - pos["opened_at"] >= s("risk.timeout_h") * 3600 and price < entry * (1 + s("risk.timeout_min_gain_pct") / 100):
        return upd, "timeout"
    return upd, None


def exit_line(pos, s):
    """Current exit line drawn on the Coin screen: the higher of the stop and the active trail line."""
    entry = pos["entry_price"]
    stop_pct = effective_stop_pct(pos["stop_pct"], s("risk.stop_pct"))
    line = entry * (1 - stop_pct / 100)
    if pos["trail_active"]:
        line = max(line, (pos["peak_price"] or entry) * (1 - s("risk.trail_pct") / 100))
    return line


class Risk:
    name = "risk"

    def __init__(self, desk):
        self.d = desk
        self.log = get_logger("risk")
        self.last_exit = None

    async def poll_once(self):
        pos = self.d.open_positions()
        if not pos:
            return
        mints = sorted({p["mint"] for p in pos})
        pairs = await self.d.dex.tokens(mints)    # all open mints in 1 call
        for p in pos:
            pair = pairs.get(p["mint"])
            price = None
            if pair:
                price = self.d.write_price(p["mint"], pair, "risk")
            await self.step(p, price, F.num("dexscreener", pair, "liquidity_usd") if pair else None)

    async def step(self, p, price, liq):
        name = self.d.coin_name(p["mint"])
        link = links.coin_url(p["mint"], "solana")
        if p["status"] == "exiting":
            if p["exit_pushed_at"] and now() - p["exit_pushed_at"] >= 60 * self.d.s("risk.confirm_window_min") and not self.d.db.kv_get(f"reminded.{p['id']}"):
                self.d.db.kv_set(f"reminded.{p['id']}", "1")
                await self.push(f"{name} still open", p["mint"], [("Sell on FOMO", link), ("Sold", f"sold:{p['id']}")])
            return
        if price is None:
            n = (p["no_price_polls"] or 0) + 1
            self.d.db.exec("UPDATE positions SET no_price_polls=? WHERE id=?", (n, p["id"]))
            self.log.info("pos %s %s no price (%d)", p["id"], p["mint"], n)
            if n == self.d.s("risk.no_price_polls"):
                await self.push(f"{name}: no price for 1 min", p["mint"], [("Sell on FOMO", link)])
            return
        if liq is not None and liq <= 0:
            return await self.exit(p, {"last_price": p["last_price"]}, "pulled", p["last_price"] or price)
        upd, reason = evaluate(p, price, now(), self.d.s)
        upd["no_price_polls"] = 0
        sets = ", ".join(f"{k}=?" for k in upd)
        self.d.db.exec(f"UPDATE positions SET {sets} WHERE id=?", (*upd.values(), p["id"]))
        trail_line = (upd["peak_price"] * (1 - self.d.s("risk.trail_pct") / 100)) if upd.get("trail_active") else None
        self.log.info("pos %s %s price=%.10g peak=%.10g stop=%.10g trail=%s action=%s", p["id"], p["mint"], price, upd["peak_price"],
                      upd["stop_price"], f"{trail_line:.10g}" if trail_line else "off", reason or "hold")
        self.d.cards["risk"] = {"state": "guarding"}
        if reason:
            p = {**p, **upd}
            await self.exit(p, upd, reason, price)

    async def exit(self, p, upd, reason, price):
        mode = p["mode"]
        name = self.d.coin_name(p["mint"])
        link = links.coin_url(p["mint"], "solana")
        entry, size = p["entry_price"], p["size_usd"]
        exit_value = size * price / entry
        fee = fees.round_trip(size, exit_value, self.d.s("desk.fees_ref_discount"))
        pnl = round(exit_value - size - fee, 2)
        pct = round(100 * (price / entry - 1), 2)
        stop_pct = p["stop_pct"]
        status = "closed" if mode == "PAPER" else "exiting"
        self.d.db.exec("UPDATE positions SET status=?, exit_price=?, exit_reason=?, pnl_usd=?, fees_usd=?, closed_at=?, exit_pushed_at=? WHERE id=?",
                       (status, price, reason, pnl, fee, now() if status == "closed" else None, now(), p["id"]))
        if mode == "PAPER":
            cash = float(self.d.db.kv_get("paper_cash")) + exit_value - fee
            self.d.db.kv_set("paper_cash", round(cash, 4))
        pre = "PAPER · " if mode == "PAPER" else ""
        if reason == "trail":
            text = f"{pre}Sold {name} · {'+' if pnl >= 0 else '-'}${abs(pnl):.2f} ({pct:+.1f}%)"
            act = ("sold", f"Sold {name}", "Risk · trailing stop", f"{'+' if pnl >= 0 else '-'}${abs(pnl):.2f} · {pct:+.1f}%")
        elif reason == "stop":
            text = f"{pre}{name} hit the -{stop_pct:g}% stop · -${abs(pnl):.2f}"
            act = ("stopped", f"Stopped {name}", f"Risk · -{stop_pct:g}% stop", f"-${abs(pnl):.2f}")
        elif reason == "timeout":
            text = f"{pre}Sell {name}, dead money · {pct:+.1f}% in {self.d.s('risk.timeout_h'):g}h"
            act = ("sold", f"Sold {name}", "Risk · timeout", f"{'+' if pnl >= 0 else '-'}${abs(pnl):.2f} · {pct:+.1f}%")
        else:
            text = f"{pre}{name} liquidity pulled · sell now · {pct:+.1f}%"
            act = ("stopped", f"Stopped {name}", "Risk · liquidity pulled", f"-${abs(pnl):.2f}")
        self.d.activity(act[0], p["mint"], "risk", act[1], act[2], act[3])
        self.d.decision("risk", p["mint"], reason, text.replace(pre, ""), line=text.replace(pre, "") + ".")
        self.last_exit = "Trailed out" if reason == "trail" else "Stopped" if reason in ("stop", "pulled") else "Timed out"
        self.d.cards["risk"] = {"state": "idle", "last": self.last_exit}
        out = {"agent": "risk", "mint": p["mint"], "name": name, "ts": iso(), "reason": reason, "entryPrice": entry,
               "exitPrice": price, "peakPrice": p.get("peak_price"), "pnlUsd": pnl, "pct": pct, "feesUsd": fee,
               "stopPct": stop_pct, "mode": mode, "status": status, "link": link}
        self.d.bus.emit("exit", out)
        btns = [("Sell on FOMO", link), ("Sold", f"sold:{p['id']}")]
        await self.push(text, p["mint"], btns, kind="exit")
        return out

    def sold(self, pid):
        p = self.d.db.one("SELECT * FROM positions WHERE id=?", (pid,))
        if p and p["status"] == "exiting":
            self.d.db.exec("UPDATE positions SET status='closed', closed_at=? WHERE id=?", (now(), pid))

    async def push(self, text, mint, buttons, kind="risk"):
        if self.d.notifier:
            return await self.d.notifier.push(text, mint, kind=kind, buttons=buttons)
        return False

    async def run(self):
        while True:
            self.d.heartbeat("risk")
            try:
                if not self.d.paused("risk"):
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
