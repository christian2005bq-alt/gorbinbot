"""AGENT · BRAIN (v2 bot 3). Sizes. Never picks a coin and never clicks.
risk size = free cash x risk_per_trade_pct / stop_pct (12% of cash at 3% / 25%), so a stop never costs more
than 3% of cash. Score >= full_size_score -> full; under -> below_full_pct of it; shill ring -> half again.
Caps: max_pool_pct of pool liquidity, max_ticket_usd. Under min_ticket_usd ($2, FOMO's minimum) -> skip.
Night limits: max_trades_night, night loss >= night_loss_stop_pct, outside the night window -> no buys."""
import asyncio
from common import now, get_logger
import forecast as FC


def size_order(cash, score, liquidity_usd, s, shill=0.0):
    """Returns dict(size or None, raw, pct, cap_hit, reason)."""
    raw = cash * s("brain.risk_per_trade_pct") / s("risk.stop_pct")
    full = raw
    if score is None or score < s("brain.full_size_score"):
        raw = raw * s("brain.below_full_pct") / 100
    if shill and shill >= s("social.shill_cut"):
        raw = raw / 2
    size, cap = raw, "none"
    pool_cap = (liquidity_usd or 0) * s("brain.max_pool_pct") / 100
    if size > pool_cap:
        size, cap = pool_cap, "pool"
    if size > s("brain.max_ticket_usd"):
        size, cap = s("brain.max_ticket_usd"), "ticket"
    size = round(size + 1e-9, 2)
    pct = round(100 * size / cash, 1) if cash else 0
    if size < s("brain.min_ticket_usd"):
        return {"size": None, "raw": round(raw, 4), "full": round(full, 4), "pct": pct, "cap": cap,
                "reason": f"under ${s('brain.min_ticket_usd'):.0f}"}
    return {"size": size, "raw": round(raw, 4), "full": round(full, 4), "pct": pct, "cap": cap, "reason": None}


class Brain:
    name = "brain"

    def __init__(self, desk):
        self.d = desk
        self.log = get_logger("brain")

    def night_block(self):
        """Reason no new buy may start tonight, or None."""
        if not self.d.in_night():
            return "outside the night window"
        if self.d.db.kv_get("night.locked") == "1":
            return "night locked"
        n = self.d.trades_tonight()
        if n >= self.d.s("brain.max_trades_night"):
            return f"max {n} trades tonight"
        loss = self.d.night_loss_pct()
        if loss is not None and loss >= self.d.s("risk.night_loss_stop_pct"):
            return f"night brake -{loss:.0f}%"
        return None

    async def handle(self, item):
        scan, verdict = item["scan"], item["verdict"]
        mint = scan["mint"]
        name = self.d.coin_name(mint)
        score = verdict.get("score")
        shill = ((verdict.get("parts") or {}).get("shill")) or 0.0
        cash = self.d.free_cash()
        liq = scan.get("liquidityUsd")
        block = self.night_block()
        if any(p["mint"] == mint for p in self.d.open_positions()):
            block = "already held"
        r = size_order(cash, score, liq, self.d.s, shill)
        reason = block or r["reason"]
        fc = None
        if not reason:
            fc = await FC.read(self.d, scan.get("pool"))
            if fc and self.d.s("brain.timesfm_mode") == "gate" and fc["ret"] < self.d.s("brain.timesfm_min_ret_pct"):
                reason = f"TimesFM {fc['h']}m forecast {fc['ret']:+.1f}%"
        self.log.info("%s score=%s social_pts=%s cash=%.2f raw=%.4f pool_cap=%s ticket_cap=%s cap=%s final=%s reason=%s",
                      mint, score, verdict.get("socialPts"), cash, r["raw"], liq and liq * self.d.s("brain.max_pool_pct") / 100,
                      self.d.s("brain.max_ticket_usd"), r["cap"], r["size"], reason)
        out = {"bot": "brain", "mint": mint, "score": score, "sizeUsd": None if reason else r["size"],
               "pctOfCash": r["pct"], "capHit": r["cap"], "reason": reason, "forecast": fc}
        self.d.cards["brain"] = {"mint": mint, "size": out["sizeUsd"], "pct": r["pct"], "cap": r["cap"], "ts": now(),
                                 "full": score is not None and score >= self.d.s("brain.full_size_score")}
        self.d.bus.emit("size", out)
        if reason:
            self.d.decision("brain", mint, "skip", reason, line=f"{name.upper()} not sized: {reason}.")
            self.d.activity("rejected", mint, "brain", f"Skipped {name}", f"Brain · {reason}", "Skipped")
            return out
        tier = "full size" if score >= self.d.s("brain.full_size_score") else "half size"
        self.d.decision("brain", mint, "size", f"${r['size']:.2f}",
                        line=f"{name.upper()} sized ${r['size']:.2f} · {r['pct']:g}% of cash · {tier} (score {score}) · cap {r['cap']}"
                             + (f" · TimesFM {fc['h']}m {fc['ret']:+.1f}% [{fc['q10']:+.0f}%..{fc['q90']:+.0f}%]" if fc else "") + ". Sent to Executor.")
        self.d.bus.executor.put_nowait({**item, "brain": out})
        return out

    async def run(self):
        while True:
            self.d.heartbeat("brain")
            try:
                item = await asyncio.wait_for(self.d.bus.brain.get(), timeout=30)
            except asyncio.TimeoutError:
                continue
            while self.d.paused("brain"):
                self.d.heartbeat("brain"); await asyncio.sleep(5)
            try:
                await self.handle(item)
            except Exception as e:
                self.log.exception("brain crash: %s", e)
