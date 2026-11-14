"""AGENT 1 · SCANNER. Counts and cuts. Every coin that graduates off pumpfun onto PumpSwap."""
import asyncio, json, re, time, unicodedata
import websockets
import fields as F
import sources as S
from common import now, iso, get_logger, fmt_k, LOGS

WS_URL = "wss://pumpportal.fun/api/data"


def norm(s: str) -> str:
    s = (s or "").lower()
    s = "".join(ch for ch in s if ch.isascii() and ch.isalpha())  # strip spaces, digits, emoji
    return s


class Scanner:
    name = "scanner"

    def __init__(self, desk):
        self.d = desk
        self.log = get_logger("scanner")
        self.room: dict[str, dict] = {}      # mint -> {migrated_at, top10, top10_ts, ...}
        self.sent: set[str] = set()          # 1 coin passes once per night
        self.decided: set[str] = set()
        self.runners: dict[str, str] = {}    # norm(name/symbol) -> display name, today
        self.reconnects = 0
        self.last_msg = now()
        for r in self.d.db.all("SELECT mint FROM scans WHERE ts>=?", (self.d.night_start_ts(),)):
            self.decided.add(r["mint"])
        # after a restart, put undecided coins back in the waiting room
        for r in self.d.db.all("SELECT mint, migrated_at, pool FROM coins WHERE migrated_at>=?", (now() - 60 * self.d.s("scanner.max_wait_min"),)):
            if r["mint"] not in self.decided:
                self.room[r["mint"]] = {"migrated_at": r["migrated_at"], "pool": None, "pool_addr": r["pool"], "top10": None, "top10_ts": 0}

    # ---------- websocket (ONE connection for the whole desk)
    async def ws_loop(self):
        backoff = 1
        while True:
            try:
                async with websockets.connect(WS_URL, open_timeout=20, ping_interval=20) as ws:
                    await ws.send(json.dumps({"method": "subscribeMigration"}))
                    self.log.info("ws open, subscribed to migrations")
                    backoff = 1
                    self.last_msg = now()
                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=self.d.s("scanner.ws_silent_s"))
                        except asyncio.TimeoutError:
                            raise ConnectionError(f"silent {self.d.s('scanner.ws_silent_s')}s")
                        self.last_msg = now()
                        msg = json.loads(raw)
                        if F.get("pumpportal", msg, "mint"):
                            with open(LOGS / "raw" / "migrations.jsonl", "a") as f:
                                f.write(json.dumps({"ts": now(), "msg": msg}) + "\n")
                            await self.on_migration(msg)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.reconnects += 1
                self.d.event("ws_reconnect", f"{type(e).__name__}: {e}")
                self.log.info("ws closed (%s: %s), reconnect in %ss", type(e).__name__, e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def on_migration(self, msg, ts=None):
        mint = F.get("pumpportal", msg, "mint")
        if not mint or mint in self.room or mint in self.decided:
            return
        if self.d.paused("scanner"):
            self.log.info("%s ignored: scanner paused", mint); return
        migrated_at = ts or now()
        creator = F.get("pumpportal", msg, "creator")   # null in PumpPortal's message (see fields.py)
        self.room[mint] = {"migrated_at": migrated_at, "pool": F.get("pumpportal", msg, "pool"), "top10": None, "top10_ts": 0}
        self.d.db.exec("INSERT OR IGNORE INTO coins(mint,migrated_at,signature,first_seen,creator) VALUES(?,?,?,?,?)",
                       (mint, migrated_at, F.get("pumpportal", msg, "signature"), now(), creator))
        self.d.bus.emit("scan", {"mint": mint, "state": "waiting"})
        asyncio.create_task(self.store_creator(mint, creator))

    async def store_creator(self, mint, creator):
        try:
            if not creator:
                rep = await self.d.rug.report(mint)
                creator = F.get("rugcheck_report", rep, "creator")
            bal = await self.d.rpc.owner_balance(creator, mint) if creator else None
            self.d.db.exec("UPDATE coins SET creator=?, creator_balance_at_migration=? WHERE mint=?", (creator, bal, mint))
        except Exception as e:
            self.log.info("%s creator lookup failed: %s (stays null, Auditor layer 3 red)", mint, e)

    # ---------- poll
    async def poll_loop(self):
        while True:
            self.d.heartbeat("scanner")
            if not self.d.paused("scanner") and self.room:
                try:
                    await self.poll_once()
                except S.RateLimited:
                    self.log.info("dexscreener 429, wait 30s, room kept (%d coins)", len(self.room))
                    await asyncio.sleep(30)
                except Exception as e:
                    self.log.info("poll error %s", e)
            await asyncio.sleep(self.d.s("scanner.poll_s"))

    async def poll_once(self):
        mints = list(self.room)
        pairs = await self.d.dex.tokens(mints)
        for mint in mints:
            st = self.room[mint]
            age = (now() - st["migrated_at"]) / 60
            pair = pairs.get(mint)
            if pair:
                self.d.write_price(mint, pair, "scanner")
                name = F.get("dexscreener", pair, "name"); sym = F.get("dexscreener", pair, "symbol")
                pool = F.get("dexscreener", pair, "pair_address")
                h24 = F.num("dexscreener", pair, "change_h24")
                self.d.db.exec("UPDATE coins SET name=?, symbol=?, pool=?, h24_change=? WHERE mint=?", (name, sym, pool, h24, mint))
                if h24 is not None and h24 >= self.d.s("scanner.runner_h24_pct"):
                    for k in (norm(name), norm(sym)):
                        if k:
                            self.runners[k] = sym or name
                st["pool_addr"] = pool
            if age >= self.d.s("scanner.max_wait_min"):
                self.decide(mint, pair, age, "kill", "never qualified", None)
                continue
            if not pair:
                continue                               # never pass a coin DexScreener doesn't know
            if age < self.d.s("scanner.min_pool_age_min"):
                continue
            await self.evaluate(mint, pair, age)

    async def evaluate(self, mint, pair, age):
        st = self.room[mint]
        liq = F.num("dexscreener", pair, "liquidity_usd")
        if liq is None:
            return                                     # no liquidity number yet: keep waiting, never guess
        h1 = F.num("dexscreener", pair, "change_h1") or 0
        name = F.get("dexscreener", pair, "name") or ""; sym = F.get("dexscreener", pair, "symbol") or ""
        if liq < self.d.s("scanner.min_liquidity_usd"):
            return self.decide(mint, pair, age, "kill", f"liq {fmt_k(liq)}", None)
        top10 = st.get("top10") if now() - st.get("top10_ts", 0) < 180 else None   # 3 min cache, spares the RPC
        if top10 is None:
            try:
                top10, _ = await S.top10_pct(self.d.rpc, mint, st.get("pool_addr"))
                st["top10"], st["top10_ts"] = top10, now()
            except Exception as e:
                self.log.info("%s top10 read failed (%s), stays in room", mint, e)
                return
        if top10 is None:
            return
        if top10 > self.d.s("scanner.max_top10_pct"):
            return self.decide(mint, pair, age, "kill", f"top 10 hold {top10:.0f}%", top10)
        if h1 > self.d.s("scanner.max_h1_change_pct"):
            return self.decide(mint, pair, age, "kill", f"+{h1:.0f}% in 1h", top10)
        cp = self.copycat(name, sym, mint)
        if cp:
            return self.decide(mint, pair, age, "kill", f"copycat of {cp}", top10)
        return self.decide(mint, pair, age, "pass", None, top10)

    def copycat(self, name, sym, mint):
        mine = {norm(name), norm(sym)} - {""}
        own_h24 = (self.d.db.coin(mint) or {}).get("h24_change") or 0
        for k, disp in self.runners.items():
            if own_h24 >= self.d.s("scanner.runner_h24_pct") and k in mine:
                continue   # it is the runner itself
            for m in mine:
                if m == k or (len(m) >= 3 and len(k) >= 3 and (m in k or k in m)):
                    return disp
        return None

    def decide(self, mint, pair, age, verdict, reason, top10):
        self.room.pop(mint, None)
        if mint in self.sent and verdict == "pass":
            return
        self.decided.add(mint)
        liq = F.num("dexscreener", pair, "liquidity_usd") if pair else None
        h1 = F.num("dexscreener", pair, "change_h1") if pair else None
        out = {"agent": "scanner", "mint": mint, "name": F.get("dexscreener", pair, "name") if pair else None,
               "symbol": F.get("dexscreener", pair, "symbol") if pair else None,
               "pool": F.get("dexscreener", pair, "pair_address") if pair else None,
               "liquidityUsd": liq, "top10Pct": top10, "h1ChangePct": h1, "ageMin": int(age),
               "verdict": verdict, "reason": reason, "ts": iso()}
        self.d.db.exec("INSERT INTO scans(mint,ts,liquidity_usd,top10_pct,h1_change_pct,age_min,verdict,reason) VALUES(?,?,?,?,?,?,?,?)",
                       (mint, now(), liq, top10, h1, age, verdict, reason))
        self.d.decision("scanner", mint, verdict, reason or "→ auditor")
        self.log.info("%s %s %s %s liq=%s top10=%s h1=%s age=%d", out["ts"], mint, verdict, reason, liq, top10, h1, age)
        self.d.bus.emit("scan", out)
        if verdict == "pass":
            self.sent.add(mint)
            self.d.bus.auditor.put_nowait(out)
        return out

    async def run(self):
        await asyncio.gather(self.ws_loop(), self.poll_loop())
