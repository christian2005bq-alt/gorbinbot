"""AGENT 3 · ANALYST (v2). Scores what survived the 8 layers, in code, no outside model (analyst.mode=v2).
alive + organic + flush + (1 - chase) [+ w * social], pass at >= min_score. Passed -> Brain.
(analyst.mode jev|rules keeps the v1 paths for comparison.)"""
import tech as TECH
import asyncio, hashlib, json
import httpx
import fields as F
import social as SOC
from common import now, iso, get_logger, SECRETS


def score_v2(pair, ctx, coin, fresh_pct, social, s, details=None):
    """v2 PART 5 SCORE. pair = fresh DexScreener read. ctx = the audit's _ctx. social None = off.
    No FOMO tokenDetails here (needs the FOMO session), so organic/flush use DexScreener txns (logged)."""
    n = lambda f: F.num("dexscreener", pair, f) or 0
    notes = []
    alive = clamp(n("volume_h1") / s("analyst.alive_volume_h1"))
    b1, s1 = n("buys_h1"), n("sells_h1")
    organic = clamp(b1 / s("analyst.organic_buys_h1")); notes.append("organic: txns")
    pen = s("analyst.bundled_penalty")
    if s1 > b1:
        organic *= pen; notes.append("sellers > buyers 1h")
    if (ctx or {}).get("bundled", 0) >= s("analyst.bundled_from"):
        organic *= pen; notes.append(f"{ctx.get('bundled')} bundled")
    cm = (coin or {}).get("curve_min")
    if cm is not None and cm < s("analyst.fast_curve_min"):
        organic *= pen; notes.append(f"curve {cm:.0f}m")
    if fresh_pct is not None and fresh_pct >= s("analyst.max_fresh_pct"):
        organic *= pen; notes.append(f"fresh {fresh_pct:.0f}%")
    b5, s5 = n("buys_m5"), n("sells_m5")
    r = s("analyst.flush_sell_ratio")
    flush = 1.0 if s5 <= b5 else (0.5 if s5 <= r * b5 else 0.0); notes.append("flush: txns")
    chase = clamp(n("change_h1") / s("analyst.chase_h1_pct"))
    core = alive + organic + flush + (1 - chase)
    w = s("social.weight") if social is not None else 0.0
    score = round(100 * (core + w * (social or 0)) / (4 + w))
    social_pts = score - round(100 * core / 4)
    if social is None:
        notes.append("social: off")
    parts = {"alive": round(alive, 4), "organic": round(organic, 4), "flush": flush, "chase": round(chase, 4),
             "social": social, "socialPts": social_pts, "freshPct": fresh_pct, "curveMin": cm, "notes": notes}
    return score, parts

QUESTIONS = {
    "alive_6h": {"type": "noul", "instructions": "This coin is still actively traded 6 hours from now"},
    "organic": {"type": "noul", "instructions": "Most buyers in the last 30 minutes are separate real wallets"},
    "flush": {"type": "noul", "instructions": "Price just flushed down and buyers are absorbing it"},
    "chase": {"type": "noul", "instructions": "This entry is chasing a green candle that already ran"},
}
JEV_URL = "https://api.typesafe.ai/v1/systemone"


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def gate(ans: dict, s) -> tuple[int, bool, list[str]]:
    """Code-only gate. s = settings getter. Returns score, passed, failed rules."""
    failed = []
    if ans["alive_6h"] < s("analyst.min_alive_6h"):
        failed.append(f"alive {ans['alive_6h']:.2f}")
    if ans["organic"] < s("analyst.min_organic"):
        failed.append(f"organic {ans['organic']:.2f}")
    if ans["chase"] > s("analyst.max_chase"):
        failed.append(f"chase {ans['chase']:.2f}")
    score = round(100 * (ans["alive_6h"] + ans["organic"] + ans["flush"] + (1 - ans["chase"])) / 4)
    if score < s("analyst.min_score"):
        failed.append(f"score {score}")
    return score, not failed, failed


def rules_answers(pair, audit, s) -> dict:
    v1 = F.num("dexscreener", pair, "volume_h1") or 0
    b1 = F.num("dexscreener", pair, "buys_h1") or 0
    b5 = F.num("dexscreener", pair, "buys_m5") or 0
    s5 = F.num("dexscreener", pair, "sells_m5") or 0
    p5 = F.num("dexscreener", pair, "change_m5") or 0
    p1 = F.num("dexscreener", pair, "change_h1") or 0
    alive = clamp(v1 / s("analyst.rules.alive_volume_h1"))
    organic = clamp(b1 / s("analyst.rules.organic_buys_h1"))
    if ((audit or {}).get("_ctx") or {}).get("bundled", 0) >= s("analyst.rules.bundled_from"):
        organic *= s("analyst.rules.bundled_penalty")
    if p5 <= -s("analyst.rules.flush_drop_m5_pct") and b5 >= s5:
        flush = 1.0
    elif p5 < 0:
        flush = 0.5
    else:
        flush = 0.0
    chase = clamp(p1 / s("analyst.rules.chase_h1_pct"))
    return {"alive_6h": round(alive, 4), "organic": round(organic, 4), "flush": flush, "chase": round(chase, 4)}


def build_state(scan, audit, pair, coin, max_chars=3000) -> str:
    def n(f):
        return F.num("dexscreener", pair, f)
    lay = {l["n"]: l for l in (audit or {}).get("layers", [])}
    ctx = (audit or {}).get("_ctx") or {}
    age = int((now() - (coin.get("migrated_at") or now())) / 60)
    dev = lay.get(3, {}).get("value", "n/a").split("%")[0] if lay.get(3, {}).get("pass") else "n/a"
    lp = lay.get(5, {}).get("value", "n/a")
    top10 = lay.get(4, {}).get("value", "n/a").rstrip("%")
    st = (f"Coin {scan.get('name') or coin.get('name')} on Solana, graduated {age} min ago. Liquidity ${n('liquidity_usd') or 0:.0f}. "
          f"Market cap ${n('market_cap') or 0:.0f}.\n"
          f"Last 5 min: {n('buys_m5') or 0:.0f} buys, {n('sells_m5') or 0:.0f} sells, volume ${n('volume_m5') or 0:.0f}, price {n('change_m5') or 0}%.\n"
          f"Last 1h: {n('buys_h1') or 0:.0f} buys, {n('sells_h1') or 0:.0f} sells, volume ${n('volume_h1') or 0:.0f}, price {n('change_h1') or 0}%.\n"
          f"Top 10 hold {top10}%. Dev holds {dev}%, sold 0. LP {lp}. Bundled {ctx.get('bundled', 0)}. Delegations {ctx.get('delegations', 0)}.")
    return st[:max_chars]


class Analyst:
    name = "analyst"

    def __init__(self, desk):
        self.d = desk
        self.log = get_logger("analyst")
        self.asked: set[str] = set()
        for r in self.d.db.all("SELECT mint FROM verdicts WHERE ts>=?", (self.d.night_start_ts(),)):
            self.asked.add(r["mint"])

    async def jev(self, state):
        key = SECRETS.get("TYPESAFE_API_KEY")
        body = {"model": "jev-latest", "state": state, "questions": QUESTIONS}
        t_end = now() + 60
        attempt = 0
        while True:
            try:
                r = await self.d.client.post(JEV_URL, headers={"Authorization": f"Bearer {key}"}, json=body,
                                             timeout=self.d.s("analyst.timeout_s"))
                if r.status_code == 429:
                    if now() < t_end:
                        await asyncio.sleep(5); continue
                    return None, "no answer"
                if r.status_code != 200:
                    raise RuntimeError(f"http {r.status_code}")
                return r.json(), None
            except Exception as e:
                attempt += 1
                self.log.info("jev error %s (attempt %d)", type(e).__name__, attempt)
                if attempt >= 2:
                    return None, "no answer"
                await asyncio.sleep(2)

    async def fresh_pct(self, owners):
        """Share of the top N holder owners (pool, curve out) with under [10] signatures. Spread over ~10s."""
        top = (owners or [])[: int(self.d.s("analyst.fresh_top_n"))]
        if not top:
            return None
        fresh, seen = 0, 0
        gap = 10 / max(1, len(top))
        for o in top:
            try:
                sigs = await self.d.rpc.signatures(o, 20)
                seen += 1
                if len(sigs) < self.d.s("analyst.fresh_sigs"):
                    fresh += 1
            except Exception:
                pass
            await asyncio.sleep(gap)
        return round(100 * fresh / seen, 1) if seen >= max(5, len(top) // 2) else None

    async def tech(self, pair):
        try:
            pool = F.get("dexscreener", pair, "pair_address") if pair else None
            if not pool:
                return None, {}
            return TECH.checks(await self.d.gecko.ohlcv(pool, 60))
        except Exception as e:
            self.log.info("tech checks unavailable: %s", e)
            return None, {}

    async def judge_v2(self, item, pair, coin):
        scan, audit = item["scan"], item["audit"]
        mint = scan["mint"]
        ctx = (audit or {}).get("_ctx") or {}
        if not pair:
            score, parts, passed, failed = 0, {}, False, ["no price"]
        else:
            fp = await self.fresh_pct(ctx.get("owners_top"))
            soc, shill, plan = await SOC.ask(mint, pair, self.d.s, client=self.d.client)
            score, parts = score_v2(pair, ctx, coin, fp, soc, self.d.s)
            parts["shill"] = shill; parts["plan"] = plan
            passed = score >= self.d.s("analyst.min_score")
            failed = [] if passed else [f"score {score}"]
            # TradingView-style 8 checks on GeckoTerminal 1m OHLCV (tradingview-mcp has no PumpSwap symbols)
            ts_, tparts = await self.tech(pair)
            parts["tech"] = ts_; parts["techChecks"] = {k: v for k, v in tparts.items() if isinstance(v, bool) or v is None}
            if passed and self.d.s("analyst.tech_gate") and ts_ is not None and ts_ < self.d.s("analyst.tech_min"):
                passed, failed = False, [f"tech {ts_} < {self.d.s('analyst.tech_min')}"]
        out = {"agent": "analyst", "bot": "analyst", "mint": mint, "layers": (audit or {}).get("layers"), "holders": (audit or {}).get("holders"),
               "score": score, "social": parts.get("social"), "socialPts": parts.get("socialPts"), "parts": parts,
               "passed": passed, "failed": failed, "reason": None if passed else failed[0], "model": "v2",
               "price": F.num("dexscreener", pair, "price_usd") if pair else None}
        self.d.db.exec("INSERT INTO verdicts(mint,ts,alive_6h,organic,flush,chase,score,pass,reason,input_tokens,model,social,social_pts,fresh_pct,curve_min) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (mint, now(), parts.get("alive"), parts.get("organic"), parts.get("flush"), parts.get("chase"), score, int(passed),
                        None if passed else failed[0], 0, "v2", parts.get("social"), parts.get("socialPts"), parts.get("freshPct"), parts.get("curveMin")))
        self.log.info("%s v2 %s score=%s social_pts=%s %s", mint, json.dumps(parts), score, parts.get("socialPts"),
                      "PASS" if passed else f"REJECT {failed}")
        return out

    async def judge(self, item):
        scan, audit = item["scan"], item["audit"]
        mint = scan["mint"]
        coin = self.d.db.coin(mint) or {}
        try:
            pair = (await self.d.dex.tokens([mint])).get(mint)
        except Exception:
            pair = None
        mode = self.d.s("analyst.mode")
        if mode == "v2":
            out = await self.judge_v2(item, pair, coin)
            return self.route(item, out, "Analyst")
        if mode == "jev" and not SECRETS.get("TYPESAFE_API_KEY"):
            mode = "rules"
        label = "Analyst (rules)" if mode == "rules" else "Analyst"
        state = build_state(scan, audit, pair, coin, self.d.s("analyst.max_state_chars")) if pair else ""
        ans, model, in_tok, out_tok, failed, raw = None, mode if mode == "rules" else None, 0, 0, [], None
        if not pair:
            failed = ["no price"]
        elif mode == "rules":
            ans = rules_answers(pair, audit, self.d.s); model = "rules"
        else:
            raw, err = await self.jev(state)
            if err:
                failed = [err]
            else:
                model = F.get("jev", raw, "model")
                in_tok = int(F.get("jev", raw, "input_tokens") or 0); out_tok = int(F.get("jev", raw, "output_tokens") or 0)
                self.d.db.exec("INSERT INTO jev_calls(ts,mint,model,input_tokens,output_tokens) VALUES(?,?,?,?,?)", (now(), mint, model, in_tok, out_tok))
                ans = {}
                for q in QUESTIONS:
                    v = F.get("jev", (F.get("jev", raw, "answer") or {}).get(q), "noul")
                    if not isinstance(v, (int, float)) or not (0 <= v <= 1):
                        ans = None; failed = ["bad answer"]
                        self.log.info("%s bad answer raw=%s", mint, json.dumps(raw)[:2000]); break
                    ans[q] = float(v)
        score, passed = 0, False
        if ans:
            score, passed, failed = gate(ans, self.d.s)
        if not failed and not passed:
            failed = ["rejected"]
        out = {"agent": "analyst", "mint": mint, "answers": ans, "score": score, "passed": passed, "failed": failed,
               "model": model, "inputTokens": in_tok, "price": F.num("dexscreener", pair, "price_usd") if pair else None}
        a = ans or {}
        self.d.db.exec("INSERT INTO verdicts(mint,ts,alive_6h,organic,flush,chase,score,pass,reason,input_tokens,model) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (mint, now(), a.get("alive_6h"), a.get("organic"), a.get("flush"), a.get("chase"), score, int(passed),
                        None if passed else failed[0], in_tok, model))
        self.log.info("%s state=%s %s score=%s %s tokens=%s", mint, hashlib.sha256(state.encode()).hexdigest()[:12],
                      a, score, "PASS" if passed else f"REJECT {failed}", in_tok)
        return self.route(item, out, label)

    def route(self, item, out, label):
        scan, audit = item["scan"], item["audit"]
        mint, score, passed, failed = out["mint"], out["score"], out["passed"], out.get("failed") or ["rejected"]
        self.d.cards["analyst"] = {"mint": mint, "score": score, "passed": passed, "socialPts": out.get("socialPts")}
        self.d.bus.emit("verdict", {k: v for k, v in out.items() if k != "layers"})
        name = self.d.coin_name(mint)
        if passed:
            self.d.decision("analyst", mint, "pass", f"score {score}", line=f"{name.upper()} scored {score}. Sent to Brain.")
            self.d.bus.brain.put_nowait({"scan": scan, "audit": audit, "verdict": out})
        else:
            self.d.decision("analyst", mint, "reject", failed[0], line=f"{name.upper()} rejected · {label} · {failed[0]}.")
            self.d.activity("rejected", mint, "analyst", f"Rejected {name}", f"{label} · {failed[0]}", "Skipped")
        return out

    async def run(self):
        while True:
            self.d.heartbeat("analyst")
            try:
                item = await asyncio.wait_for(self.d.bus.analyst.get(), timeout=30)
            except asyncio.TimeoutError:
                continue
            mint = item["scan"]["mint"]
            if mint in self.asked:
                continue                    # never re-asks the same coin
            self.asked.add(mint)
            while self.d.paused("analyst"):
                self.d.heartbeat("analyst"); await asyncio.sleep(5)
            try:
                await self.judge(item)
            except Exception as e:
                self.log.exception("analyst crash %s: %s", mint, e)
