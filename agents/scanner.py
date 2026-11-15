"""AGENT 1 · SCANNER (v2). Counts and cuts. Every coin that graduates off pumpfun onto PumpSwap.
Coin source: Helius logsSubscribe on the pump.fun migration account (primary). PumpPortal websocket stays
as fallback (it answers 403 to this box since 2026-11-14 21:57)."""
import asyncio, datetime as _dt, json, re, time, unicodedata
import websockets
import fields as F
import sources as S
from common import now, iso, get_logger, fmt_k, LOGS, SECRETS

WS_URL = "wss://pumpportal.fun/api/data"


def parse_iso(v) -> float:
    """RugCheck times look like 2026-11-15T02:51:12.848453819Z (nanoseconds): trim to microseconds."""
    t = str(v).rstrip("Z")
    if "." in t:
        a, b = t.split(".", 1)
        t = a + "." + b[:6]
    return _dt.datetime.fromisoformat(t).replace(tzinfo=_dt.timezone.utc).timestamp()


def warnings_kill(w):
    """FOMO /proxy/tokenWarnings -> kill reason or None (keys named by the v2 prompt: disableSelling,
    disableBuying, warnings)."""
    if not isinstance(w, dict):
        return None
    if w.get("disableSelling") or w.get("disableBuying"):
        return "FOMO: selling off" if w.get("disableSelling") else "FOMO: buying off"
    ws = w.get("warnings")
    if ws:
        t = ws[0] if isinstance(ws, list) else ws
        t = t.get("text") or t.get("message") or str(t) if isinstance(t, dict) else str(t)
        return f"FOMO warns: {t}"[:80]
    return None


def holders_count(accts) -> int:
    return sum(1 for a in accts if int(F.get("rpc_token_account", a, "amount") or 0) > 0)


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
        self._ws = None
        self._hws = None
        self.helius_ok_at = 0.0          # last good message from Helius
        self.pp_next_try = 0.0           # PumpPortal fallback backoff
        self.seen_by = {"helius": 0, "pumpportal": 0, "geckoterminal": 0}
        self.gecko_ok_at = 0.0
        self._hsrc: dict[str, str] = {}   # mint -> holders source of the 1st sample (rpc|gecko)
        self._last_hg: dict[str, float | None] = {}
        self.hg_min = 0.0
        for r in self.d.db.all("SELECT mint FROM scans WHERE ts>=?", (min(self.d.night_start_ts(), now() - 3 * 3600),)):
            self.decided.add(r["mint"])
        # after a restart, put undecided coins back in the waiting room
        for r in self.d.db.all("SELECT mint, migrated_at, pool FROM coins WHERE migrated_at>=?", (now() - 60 * self.d.s("scanner.max_wait_min"),)):
            if r["mint"] not in self.decided:
                self.room[r["mint"]] = {"migrated_at": r["migrated_at"], "pool": None, "pool_addr": r["pool"], "top10": None, "top10_ts": 0}

    # ---------- websocket (ONE connection for the whole desk)
    def helius_url(self):
        u = SECRETS.get("HELIUS_RPC_URL") or ""
        if not u:
            rpc = self.d.s("desk.rpc_url") or ""
            u = rpc if "helius" in rpc else ""
        return u.replace("https://", "wss://", 1) if u.startswith("https://") else None

    async def helius_loop(self):
        """Primary source: logsSubscribe(mentions: pump.fun migration account). Each successful Migrate ->
        getTransaction -> the coin's mint -> waiting room. Reconnect with backoff 1, 2, 4 ... 60s."""
        backoff = 1
        while True:
            url = self.helius_url()
            if not url:
                await asyncio.sleep(60); continue
            try:
                async with websockets.connect(url, open_timeout=20, ping_interval=20, ping_timeout=20, close_timeout=5,
                                              max_size=2 ** 22) as ws:
                    self._hws = ws
                    await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                                              "params": [{"mentions": [S.PUMP_MIGRATION_AUTH]}, {"commitment": "confirmed"}]}))
                    ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
                    if "error" in ack:
                        raise ConnectionError(f"subscribe refused {ack['error'].get('code')}")
                    self.log.info("helius ws open, subscribed to pump.fun migrations")
                    backoff = 1
                    self.helius_ok_at = self.last_msg = now()
                    silent = max(300, self.d.s("scanner.ws_silent_s"))   # migrations come ~1/min, quiet gaps happen
                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=silent)
                        except asyncio.TimeoutError:
                            raise ConnectionError(f"silent {silent}s")
                        self.helius_ok_at = self.last_msg = now()
                        m = json.loads(raw)
                        v = (((m.get("params") or {}).get("result") or {}).get("value")) or {}
                        if not S.is_migration_logs(v.get("logs"), v.get("err")):
                            continue
                        asyncio.create_task(self.on_helius_migration(v.get("signature")))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._hws = None
                self.reconnects += 1
                self.d.event("ws_reconnect", f"helius {type(e).__name__}")
                self.log.info("helius ws closed (%s), reconnect in %ss", type(e).__name__, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def on_helius_migration(self, sig):
        try:
            tx = None
            for i in range(3):
                tx = await self.d.rpc.transaction(sig)
                if tx:
                    break
                await asyncio.sleep(2 + 2 * i)
            mint = S.mint_from_tx(tx)
            if not mint:
                self.log.info("migration %s: no mint found in tx", sig[:16]); return
            bt = (tx or {}).get("blockTime")
            with open(LOGS / "raw" / "migrations.jsonl", "a") as f:
                f.write(json.dumps({"ts": float(bt) if bt else now(), "msg": {"mint": mint, "signature": sig, "txType": "migrate", "pool": "pump-amm", "source": "helius"}}) + "\n")
            await self.on_migration({"mint": mint, "signature": sig, "txType": "migrate", "pool": "pump-amm"},
                                    ts=float(bt) if bt else None, source="helius")
        except Exception as e:
            self.log.info("migration %s lookup failed: %s", (sig or "")[:16], e)

    def helius_healthy(self):
        return self._hws is not None and now() - self.helius_ok_at < 600

    async def ws_loop(self):
        """Fallback: PumpPortal. Only tried while Helius is down (or source=pumpportal); 403 -> 10 min backoff."""
        backoff = 1
        while True:
            if self.d.s("scanner.source") != "pumpportal" and self.helius_healthy():
                await asyncio.sleep(15); continue
            if now() < self.pp_next_try:
                await asyncio.sleep(5); continue
            try:
                async with websockets.connect(WS_URL, open_timeout=20, ping_interval=20, ping_timeout=20, close_timeout=5) as ws:
                    self._ws = ws
                    await ws.send(json.dumps({"method": "subscribeMigration"}))
                    self.log.info("ws open, subscribed to migrations")
                    backoff = 1
                    self.last_msg = now()
                    while True:
                        if self.d.s("scanner.source") != "pumpportal" and self.helius_healthy():
                            raise ConnectionError("helius back, fallback closed")
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=self.d.s("scanner.ws_silent_s"))
                        except asyncio.TimeoutError:
                            raise ConnectionError(f"silent {self.d.s('scanner.ws_silent_s')}s")
                        self.last_msg = now()
                        msg = json.loads(raw)
                        if F.get("pumpportal", msg, "mint"):
                            with open(LOGS / "raw" / "migrations.jsonl", "a") as f:
                                f.write(json.dumps({"ts": now(), "msg": msg}) + "\n")
                            await self.on_migration(msg, source="pumpportal")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._ws = None
                self.d.event("pumpportal_down", f"{type(e).__name__}: {str(e)[:120]}")   # fallback only: not a primary reconnect
                if "403" in str(e):
                    self.pp_next_try = now() + 600
                    self.log.info("pumpportal fallback 403, next try in 10 min")
                    continue
                self.log.info("ws closed (%s: %s), reconnect in %ss", type(e).__name__, e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)


    # ---------- 3rd source: CoinGecko / GeckoTerminal new PumpSwap pools (coingecko/skills, keyless API)
    async def gecko_loop(self):
        """Backup to Helius + PumpPortal: every scanner.gecko_poll_s, read GeckoTerminal's new Solana pools and send
        any PumpSwap pool of a pump.fun mint we did not see (dedupe in on_migration). Never kills a coin."""
        await asyncio.sleep(15)
        while True:
            try:
                if self.d.s("scanner.gecko_enabled") and not self.d.paused("scanner"):
                    pools = await self.d.gecko.new_pumpswap_pools(pages=2)
                    if now() - self.gecko_ok_at > 1800:
                        self.log.info("geckoterminal ok: %d pumpswap pools in new_pools", len(pools))
                    self.gecko_ok_at = now()
                    maxage = 60 * self.d.s("scanner.max_wait_min")
                    for p in pools:
                        m, ts = p["mint"], p["created_ts"]
                        if not m.endswith("pump") or not ts or now() - ts > maxage:
                            continue
                        if m in self.room or m in self.decided:
                            continue
                        await self.on_migration({"mint": m, "signature": None, "txType": "migrate", "pool": "pump-amm"},
                                                ts=ts, source="geckoterminal")
            except Exception as e:
                self.log.info("geckoterminal new pools failed: %s", e)
            await asyncio.sleep(self.d.s("scanner.gecko_poll_s"))

    async def on_migration(self, msg, ts=None, source="pumpportal"):
        mint = F.get("pumpportal", msg, "mint")
        if not mint or mint in self.room or mint in self.decided:
            return
        self.seen_by[source] = self.seen_by.get(source, 0) + 1
        if self.d.paused("scanner"):
            self.log.info("%s ignored: scanner paused", mint); return
        migrated_at = ts or now()
        creator = F.get("pumpportal", msg, "creator")   # null in PumpPortal's message (see fields.py)
        self.room[mint] = {"migrated_at": migrated_at, "pool": F.get("pumpportal", msg, "pool"), "top10": None, "top10_ts": 0}
        self.d.db.exec("INSERT OR IGNORE INTO coins(mint,migrated_at,signature,first_seen,creator,source) VALUES(?,?,?,?,?,?)",
                       (mint, migrated_at, F.get("pumpportal", msg, "signature"), now(), creator, source))
        self.d.bus.emit("scan", {"mint": mint, "state": "waiting"})
        self.d.decision("scanner", mint, "waiting", f"waiting room · {source}",
                        line=f"{mint[:4]}…{mint[-4:]} in the waiting room ({source}).")
        self.log.info("%s migrated (source %s), into the waiting room (%d)", mint, source, len(self.room))
        asyncio.create_task(self.store_creator(mint, creator))
        asyncio.create_task(self.sample_holders(mint, first=True))

    async def store_creator(self, mint, creator):
        try:
            rep = None
            try:
                rep = await self.d.rug.report(mint)
            except Exception:
                rep = None
            if not creator and rep:
                creator = F.get("rugcheck_report", rep, "creator")
            bal = await self.d.rpc.owner_balance(creator, mint) if creator else None
            if bal is None and rep is not None:
                cb = F.get("rugcheck_report", rep, "creator_balance")
                bal = int(cb) if isinstance(cb, (int, float)) else None
            # curve_min = migratedAt - first sight of the coin (RugCheck detectedAt, our 2nd source)
            curve_min = None
            det = F.get("rugcheck_report", rep, "detected_at") if rep else None
            mig = (self.d.db.coin(mint) or {}).get("migrated_at")
            if det and mig:
                try:
                    t0 = parse_iso(det)
                    curve_min = round(max(0.0, (mig - t0) / 60), 1)
                except Exception:
                    curve_min = None
            self.d.db.exec("UPDATE coins SET creator=?, creator_balance_at_migration=?, curve_min=? WHERE mint=?",
                           (creator, bal, curve_min, mint))
        except Exception as e:
            self.log.info("%s creator lookup failed: %s (stays null, Auditor layer 3 red)", mint, e)

    async def sample_holders(self, mint, first=False):
        """Holders = token accounts with a balance (Token + Token-2022 via RPC). First sample at migration,
        2nd at pass time -> holders_growth. Fallback: GeckoTerminal's holders count (coingecko/skills). Both samples
        of one coin come from the SAME source, so growth never mixes two counters. No answer -> null, never a kill."""
        src = self._hsrc.get(mint, "rpc") if not first else "rpc"
        n = None
        if src == "rpc":
            try:
                n = holders_count(await S.all_token_accounts(self.d.rpc, mint, max_age=0 if not first else 60))
            except Exception as e:
                if not first:
                    self.log.info("%s holders read failed: %s", mint, type(e).__name__)
                    return None
                src = "gecko"
        if src == "gecko":
            try:
                n = await self.d.gecko.holders(mint)
            except Exception as e:
                n = None
            if n is None:
                self.log.info("%s holders read failed (rpc + geckoterminal)", mint)
                return None
        if first:
            self._hsrc[mint] = src
        if first:
            self.d.db.exec("UPDATE coins SET holders0=?, holders0_ts=? WHERE mint=?", (n, now(), mint))
        return n

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
        # FOMO tokenWarnings need the FOMO session (browser lane) and a request body copied from Chrome.
        # Until both exist fomo_warnings() returns None: not checked (logged), never a pass by itself.
        wr = warnings_kill(await self.fomo_warnings(mint))
        if wr:
            return self.decide(mint, pair, age, "kill", wr, top10)
        hg = await self.holders_growth(mint)
        st["holders_growth"] = hg
        if hg is not None and hg * 100 < self.d.s("scanner.min_holders_growth_pct"):
            return self.decide(mint, pair, age, "kill", f"holders leaving {hg*100:+.0f}% in {self.hg_min:.0f}m", top10)
        return self.decide(mint, pair, age, "pass", None, top10)

    async def fomo_warnings(self, mint):
        return None

    async def holders_growth(self, mint):
        c = self.d.db.coin(mint) or {}
        h0, t0 = c.get("holders0"), c.get("holders0_ts")
        self.hg_min = (now() - t0) / 60 if t0 else 0
        if not h0 or not t0 or now() - t0 < 300:
            return None
        h1 = await self.sample_holders(mint)
        if h1 is None:
            return None
        self.d.db.exec("UPDATE coins SET holders=? WHERE mint=?", (h1, mint))
        return round(h1 / h0 - 1, 4)

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
        st = self.room.pop(mint, None) or {}
        self._last_hg[mint] = st.get("holders_growth")
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
        mcap = F.num("dexscreener", pair, "market_cap") if pair else None
        v5 = F.num("dexscreener", pair, "volume_m5") if pair else None
        v1 = F.num("dexscreener", pair, "volume_h1") if pair else None
        liq_mcap = round(liq / mcap, 4) if liq and mcap else None
        accel = round(v5 * 12 / v1, 3) if v5 is not None and v1 else None
        hg = self._last_hg.get(mint)
        out.update({"liqMcap": liq_mcap, "accel": accel, "holdersGrowth": hg})
        self.d.db.exec("INSERT INTO scans(mint,ts,liquidity_usd,top10_pct,h1_change_pct,age_min,verdict,reason,liq_mcap,accel,holders_growth) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (mint, now(), liq, top10, h1, age, verdict, reason, liq_mcap, accel, hg))
        self.d.decision("scanner", mint, verdict, reason or "→ auditor")
        self.log.info("%s %s %s %s liq=%s top10=%s h1=%s age=%d", out["ts"], mint, verdict, reason, liq, top10, h1, age)
        self.d.bus.emit("scan", out)
        if verdict == "pass":
            self.sent.add(mint)
            self.d.bus.auditor.put_nowait(out)
        return out

    async def kick_ws(self):
        """Close the live sockets so they reconnect (used after a clock jump)."""
        for ws in (self._ws, self._hws):
            if ws is not None:
                try:
                    await asyncio.wait_for(ws.close(), timeout=5)
                except Exception:
                    pass

    async def run(self):
        await asyncio.gather(self.helius_loop(), self.ws_loop(), self.gecko_loop(), self.poll_loop())
