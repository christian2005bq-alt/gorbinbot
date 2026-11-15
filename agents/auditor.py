"""AGENT 2 · AUDITOR = v2 Analyst's 8 layers (v2 merges audit + score into 1 judgement: this module runs the
layers, analyst.py scores what survives). Fixed order, first red kills the coin. v2 adds: serial-rugger dev
history (layer 3, db.rugs from RugCheck), insiders >= 15% (layer 7), top-20 holder owners for fresh wallets."""
import asyncio, time, uuid
import fields as F
import sources as S
from common import now, iso, get_logger, short
import links

LAYERS = ["Mint authority", "Freeze authority", "Dev wallet", "Top 10 holders", "Liquidity", "Pool age",
          "Bundled wallets", "Delegations"]
NODATA = {1: "mint", 2: "freeze", 3: "dev", 4: "top 10", 5: "liquidity", 6: "pool age", 7: "bundles", 8: "delegations"}


class Red(Exception):
    def __init__(self, value, source):
        self.value, self.source = value, source


class Auditor:
    name = "auditor"

    def __init__(self, desk):
        self.d = desk
        self.log = get_logger("auditor")
        self.rejected: set[str] = set()
        self.layer8_down_notified = False
        for r in self.d.db.all("SELECT mint FROM decisions WHERE agent='auditor' AND verdict='reject' AND ts>=?", (self.d.night_start_ts(),)):
            self.rejected.add(r["mint"])

    async def retry(self, n, fn, *a):
        tries = int(self.d.s("auditor.retries"))
        last = None
        for i in range(tries + 1):
            try:
                return await fn(*a)
            except Exception as e:
                last = e
                if i < tries:
                    await asyncio.sleep(2)
        raise Red(f"no data: {NODATA[n]}", "rpc")

    async def audit(self, scan: dict, forward=True):
        mint = scan["mint"]
        run_id = uuid.uuid4().hex[:10]
        coin = self.d.db.coin(mint) or {}
        layers = []
        holders = None
        ctx = {}
        self.d.cards["auditor"] = {"mint": mint, "running": True}
        self.d.bus.emit("audit_start", {"mint": mint, "run": run_id, "coin_url": links.coin_url(mint, "solana")})

        async def rc_report():
            if "rep" not in ctx:
                ctx["rep"] = await self.d.rug.report(mint)
            return ctx["rep"]

        async def rc_graph():
            if "graph" not in ctx:
                ctx["graph"] = await self.d.rug.graph(mint)
            return ctx["graph"]

        async def acct():
            if "acct" not in ctx:
                ctx["acct"] = await self.d.rpc.account_info(mint)
            return ctx["acct"]

        async def layer(n):
            nonlocal holders
            mx = self.d.s
            if n in (1, 2):
                j = await self.retry(n, acct)
                if not F.get("rpc_account_info", j, "owner_program"):
                    raise Red(f"no data: {NODATA[n]}", "rpc")
                key = "mint_authority" if n == 1 else "freeze_authority"
                if F.get("rpc_account_info", j, key) is not None:
                    raise Red("mint not revoked" if n == 1 else "freeze not revoked", "rpc")
                return "Revoked", "rpc", F.get("rpc_account_info", j, key)
            if n == 3:
                j = await self.retry(n, acct)
                try:
                    supply = int(F.get("rpc_account_info", j, "supply"))
                except Exception:
                    supply = 0
                if not supply:
                    raise Red("no supply", "rpc")
                ctx["supply"] = supply
                creator = coin.get("creator")
                if not creator:
                    try:
                        creator = F.get("rugcheck_report", await rc_report(), "creator")
                    except Exception:
                        creator = None
                if not creator:
                    raise Red("no data: dev", "rpc")
                bal = await self.retry(n, self.d.rpc.owner_balance, creator, mint)
                at_mig = coin.get("creator_balance_at_migration")
                pct = 100 * bal / supply
                if pct >= mx("auditor.max_dev_pct"):
                    raise Red(f"dev holds {pct:.0f}%", "rpc")
                if at_mig is None:
                    raise Red("no data: dev", "rpc")      # can't prove "never dropped"
                if bal < at_mig:
                    raise Red("dev sold", "rpc")
                # v2 history: the creator's other mints (our coin log + the report's creatorTokens) found in db.rugs
                others = {r["mint"] for r in self.d.db.all("SELECT mint FROM coins WHERE creator=? AND mint<>?", (creator, mint))}
                try:
                    for ct in F.get("rugcheck_report", await rc_report(), "creator_tokens") or []:
                        m2 = F.get("rugcheck_report", ct, "ct_mint")
                        if m2 and m2 != mint:
                            others.add(m2)
                except Exception:
                    pass
                rugged = 0
                if others:
                    q = ",".join("?" * len(others))
                    rugged = self.d.db.one(f"SELECT COUNT(*) c FROM rugs WHERE mint IN ({q})", tuple(others))["c"]
                ctx["dev_other_mints"] = len(others)
                ctx["dev_bal"] = bal
                if rugged:
                    raise Red(f"dev rugged {rugged} before", "rugcheck")
                return f"{pct:.1f}% · sold 0", "rpc", {"creator": creator, "bal": bal, "at_migration": at_mig, "others": len(others)}
            if n == 4:
                t, _ = await self.retry(n, S.top10_pct, self.d.rpc, mint, scan.get("pool") or coin.get("pool"))
                if t is None:
                    raise Red("no data: top 10", "rpc")
                if t >= mx("auditor.max_top10_pct"):
                    raise Red(f"top 10 hold {t:.0f}%", "rpc")
                return f"{t:.1f}%", "rpc", t
            if n == 5:
                rep = await self.retry(n, rc_report)
                pool = scan.get("pool") or coin.get("pool")
                markets = F.get("rugcheck_report", rep, "markets") or []
                m = next((x for x in markets if F.get("rugcheck_report", x, "market_pool") == pool), None)
                pct = F.get("rugcheck_report", m, "lp_locked_pct") if m else None
                if pct is None:
                    raise Red("no data: liquidity", "rugcheck")
                if pct < mx("auditor.min_lp_locked_pct"):
                    raise Red("liquidity unlocked", "rugcheck")
                liq0 = scan.get("liquidityUsd")
                try:
                    pair = (await self.d.dex.tokens([mint])).get(mint)
                except Exception:
                    pair = None
                liq = F.num("dexscreener", pair, "liquidity_usd") if pair else None
                if liq is None:
                    raise Red("no data: liquidity", "rugcheck")
                if liq0 and liq < liq0 * (1 - mx("auditor.max_liq_drop_pct") / 100):
                    raise Red("liquidity pulled", "rugcheck")
                return ("100% burned" if pct >= 99.995 else f"{pct:.2f}% locked"), "rugcheck", {"lp": pct, "liq": liq}
            if n == 6:
                mig = coin.get("migrated_at")
                if not mig:
                    raise Red("no data: pool age", "rpc")
                age = (now() - mig) / 60
                if age < mx("auditor.min_pool_age_min"):
                    raise Red("pool too young", "rpc")
                return (f"{age/60:.0f}h {age%60:.0f}m" if age >= 60 else f"{age:.0f}m"), "rpc", age
            if n == 7:
                g = await self.retry(n, rc_graph)
                nets = g if isinstance(g, list) else [g]
                if not nets or any(F.get("rugcheck_graph", x, "edges") is None for x in nets if isinstance(x, dict)):
                    if not nets:
                        ctx["bundled"] = 0
                        ins = await self.insiders_pct(rc_report)
                        ctx["insiders_pct"] = ins
                        if ins is not None and ins >= mx("auditor.max_insiders_pct"):
                            raise Red(f"insiders hold {ins:.0f}%", "rugcheck")
                        return ("None · 0 insider networks" if not ins else f"None · insiders {ins:.0f}%"), "rugcheck", 0
                    raise Red("no data: bundles", "rugcheck")
                holders_set, adj = set(), {}
                for net in nets:
                    for nd in F.get("rugcheck_graph", net, "nodes") or []:
                        if (F.get("rugcheck_graph", nd, "node_holdings") or 0) > 0:
                            holders_set.add(F.get("rugcheck_graph", nd, "node_id"))
                    for e in F.get("rugcheck_graph", net, "edges") or []:
                        a, b = F.get("rugcheck_graph", e, "edge_source"), F.get("rugcheck_graph", e, "edge_target")
                        adj.setdefault(a, set()).add(b); adj.setdefault(b, set()).add(a)
                biggest, seen = 0, set()
                for h in holders_set:
                    if h in seen:
                        continue
                    stack, comp = [h], 0
                    seen.add(h)
                    while stack:
                        x = stack.pop(); comp += 1
                        for y in adj.get(x, ()):
                            if y in holders_set and y not in seen:
                                seen.add(y); stack.append(y)
                    biggest = max(biggest, comp)
                ctx["bundled"] = biggest
                if biggest >= mx("auditor.max_bundled"):
                    raise Red(f"{biggest} bundled wallets", "rugcheck")
                ins = await self.insiders_pct(rc_report)
                ctx["insiders_pct"] = ins
                if ins is not None and ins >= mx("auditor.max_insiders_pct"):
                    raise Red(f"insiders hold {ins:.0f}%", "rugcheck")
                base = "None" if biggest <= 1 else f"{biggest} wallets"
                return f"{base} · insiders {ins:.0f}%" if ins else f"{base} · 0 insider networks", "rugcheck", biggest
            if n == 8:
                try:
                    accts = await self.retry(n, S.all_token_accounts, self.d.rpc, mint)
                except Red:
                    await self.layer8_down()
                    raise
                by_del, hold = {}, 0
                excl = {x for x in (scan.get("pool") or coin.get("pool"), S.bonding_curve(mint)) if x}
                own_amt = {}
                for a in accts:
                    amt = int(F.get("rpc_token_account", a, "amount") or 0)
                    if amt > 0:
                        ow = F.get("rpc_token_account", a, "owner")
                        if ow and ow not in excl and F.get("rpc_token_account", a, "pubkey") not in excl:
                            own_amt[ow] = own_amt.get(ow, 0) + amt
                        hold += 1
                        dl = F.get("rpc_token_account", a, "delegate")
                        if dl:
                            by_del[dl] = by_del.get(dl, 0) + 1
                holders = hold
                ctx["owners_top"] = [o for o, _ in sorted(own_amt.items(), key=lambda x: -x[1])[:50]]
                self.d.db.exec("UPDATE coins SET holders=? WHERE mint=?", (hold, mint))
                top = max(by_del.items(), key=lambda x: x[1]) if by_del else None
                ctx["delegations"] = top[1] if top else 0
                if top and top[1] >= mx("auditor.max_delegated_accounts"):
                    raise Red(f"{top[1]} wallets → {short(top[0])}", "rpc")
                return "None", "rpc", {"holders": hold, "max_delegate": top}

        passed, reason = True, None
        for n in range(1, 9):
            t0 = time.time()
            try:
                value, source, raw = await layer(n)
                ok = True
            except Red as r:
                value, source, raw, ok = r.value, r.source, None, False
            except Exception as e:
                value, source, raw, ok = f"no data: {NODATA[n]}", "rpc", None, False
            ms = int(1000 * (time.time() - t0))
            L = {"n": n, "name": LAYERS[n - 1], "pass": ok, "value": value, "source": source}
            layers.append(L)
            self.d.db.exec("INSERT INTO audits(mint,ts,layer,name,value_text,pass,source,run_id) VALUES(?,?,?,?,?,?,?,?)",
                           (mint, now(), n, LAYERS[n - 1], value, int(ok), source, run_id))
            self.log.info("%s layer %d %s pass=%s value=%r raw=%r %dms", mint, n, LAYERS[n - 1], ok, value, raw, ms)
            self.d.bus.emit("audit_layer", {"mint": mint, "run": run_id, **L})
            if not ok:
                passed, reason = False, value
                for m in range(n + 1, 9):
                    layers.append({"n": m, "name": LAYERS[m - 1], "pass": None, "value": "not checked", "source": None})
                    self.d.db.exec("INSERT INTO audits(mint,ts,layer,name,value_text,pass,source,run_id) VALUES(?,?,?,?,?,?,?,?)",
                                   (mint, now(), m, LAYERS[m - 1], "not checked", None, None, run_id))
                break
        out = {"agent": "auditor", "mint": mint, "ts": iso(), "passed": passed, "layersChecked": len([l for l in layers if l["pass"] is not None]),
               "layers": layers, "holders": holders, "reason": reason, "_ctx": {k: v for k, v in ctx.items() if k in ("bundled", "delegations", "supply", "insiders_pct", "owners_top", "dev_other_mints", "dev_bal")}}
        self.log.info("%s verdict %s %s", mint, "PASS" if passed else "RED", reason)
        self.d.cards["auditor"] = {"mint": mint, "running": False, "passed": passed, "reason": reason, "layers": [l["pass"] for l in layers]}
        self.d.bus.emit("audit", {k: v for k, v in out.items() if k != "_ctx"})
        if forward:
            name = self.d.coin_name(mint)
            if passed:
                self.d.decision("auditor", mint, "pass", "8/8 → Analyst score")
                self.d.bus.analyst.put_nowait({"scan": scan, "audit": out})
            else:
                self.rejected.add(mint)
                self.d.decision("auditor", mint, "reject", reason)
                self.d.activity("rejected", mint, "auditor", f"Rejected {name}", f"Auditor · {reason}", "Skipped")
                if self.d.s("desk.push_rejects") and self.d.notifier:
                    await self.d.notifier.push(f"Rejected {name} · Auditor · {reason}", mint, kind="reject", buttons=False)
        return out

    async def insiders_pct(self, rc_report):
        """report insiderNetworks: sum(currentHolding) / token supply. No key = 0 networks (said so)."""
        try:
            rep = await rc_report()
        except Exception:
            return None
        nets = F.get("rugcheck_report", rep, "insider_networks")
        if not nets:
            return 0.0
        try:
            sup = float(F.get("rugcheck_report", rep, "supply") or 0)
            held = sum(float(F.get("rugcheck_report", n, "net_holding") or 0) for n in nets)
            return round(100 * held / sup, 2) if sup else None
        except Exception:
            return None

    async def rugs_loop(self):
        """db.rugs: RugCheck's rug list, backfilled at start and every 2 min (ticker, 50 newest)."""
        while True:
            try:
                items = await self.d.rug.rugs_ticker(50)
                for it in items:
                    if it.get("mint"):
                        self.d.db.exec("INSERT OR IGNORE INTO rugs(mint,ts,pulled_usd) VALUES(?,?,?)",
                                       (it["mint"], float(it.get("ruggedAt") or now()), it.get("liquidityPulledUSD")))
            except Exception as e:
                self.log.info("rugs ticker error %s", type(e).__name__)
            await asyncio.sleep(120)

    async def layer8_down(self):
        if not self.layer8_down_notified and self.d.notifier:
            self.layer8_down_notified = True
            self.d.event("layer8_down", "")
            await self.d.notifier.push("layer 8 down, every coin is red until rpc_url changes", None, kind="alert", buttons=False)

    async def run(self):
        await asyncio.gather(self.rugs_loop(), self.main_loop())

    async def main_loop(self):
        while True:
            self.d.heartbeat("auditor")
            try:
                scan = await asyncio.wait_for(self.d.bus.auditor.get(), timeout=30)
            except asyncio.TimeoutError:
                continue
            mint = scan["mint"]
            if mint in self.rejected:
                continue
            while self.d.paused("auditor"):
                self.d.heartbeat("auditor"); await asyncio.sleep(5)
            if not self.d.s("auditor.enabled"):
                self.d.decision("auditor", mint, "pass", "auditor off: not checked")
                self.d.bus.analyst.put_nowait({"scan": scan, "audit": {"passed": True, "layers": [], "holders": None, "_ctx": {}, "skipped": True}})
                continue
            try:
                await self.audit(scan)
            except Exception as e:
                self.log.exception("audit crash %s: %s", mint, e)
