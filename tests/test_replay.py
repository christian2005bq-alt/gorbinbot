"""STEP 13.6 test_replay: run recorded live migrations (logs/raw/migrations.jsonl, last N hours) through the PAPER
pipeline with live sources (DexScreener, RugCheck, RPC, Jev) in a throwaway db, pushes captured (not sent). Shows the Activity.
Usage: .venv/bin/python tests/test_replay.py [--hours 2] [--extra MINT ...]
pytest runs the offline variant below (synthetic migrations, fake sources) to prove the wiring."""
import asyncio, json, sys, time, tempfile, os, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if __name__ == "__main__":
    os.environ.setdefault("DESK_LOGS", tempfile.mkdtemp(prefix="desk-replay-logs-"))


async def replay(hours=2.0, extra=()):
    tmp = os.environ.get("REPLAY_DIR") or tempfile.mkdtemp()
    os.environ["DESK_STATUS"] = tmp + "/status"
    from db import DB
    from desk import Desk
    from tests.conftest import FakeNotifier
    from agents.scanner import Scanner
    from agents.auditor import Auditor
    from agents.analyst import Analyst
    from agents.brain import Brain
    from agents.executor import Executor
    from agents.risk import Risk
    from common import LOGS
    import views
    live = DB()
    d = Desk(DB(Path(tmp) / "replay.db"))
    for k in ("desk.paper_start_stack", "desk.stack", "analyst.mode", "desk.rpc_url"):
        d.settings.set(k, live.one("SELECT value FROM settings WHERE key=?", (k,)) and json.loads(live.one("SELECT value FROM settings WHERE key=?", (k,))["value"]) or d.s(k))
    d.db.kv_set("paper_cash", d.s("desk.paper_start_stack"))
    d.notifier = FakeNotifier()
    d.start_night()
    d.in_night = lambda t=None: True
    sc, au, an, br, ex, rk = Scanner(d), Auditor(d), Analyst(d), Brain(d), Executor(d), Risk(d)
    d.agents = {"scanner": sc, "auditor": au, "analyst": an, "brain": br, "executor": ex, "risk": rk}
    msgs = []
    f = Path(__file__).resolve().parents[1] / "logs" / "raw" / "migrations.jsonl"
    if f.exists():
        for line in f.read_text().splitlines():
            r = json.loads(line)
            if r["ts"] >= time.time() - hours * 3600:
                msgs.append(r)
    for m in extra:
        msgs.append({"ts": time.time() - 30 * 60, "msg": {"mint": m, "txType": "migrate", "pool": "pump-amm"}})
    print(f"replaying {len(msgs) - len(extra)} recorded migrations from the last {hours}h + {len(extra)} extra mints")
    for r in msgs:
        await sc.on_migration(r["msg"], ts=r["ts"])
    await asyncio.sleep(8)   # creator lookups
    await sc.poll_once()
    while not d.bus.auditor.empty():
        await au.audit(d.bus.auditor.get_nowait())
    while not d.bus.analyst.empty():
        await an.judge(d.bus.analyst.get_nowait())
    while not d.bus.brain.empty():
        await br.handle(d.bus.brain.get_nowait())
    while not d.bus.executor.empty():
        await ex.handle(d.bus.executor.get_nowait())
    await rk.poll_once()
    print("\nSCANS")
    for s in d.db.all("SELECT s.*, c.symbol FROM scans s LEFT JOIN coins c USING(mint)"):
        print(f"  {s['symbol'] or s['mint'][:8]:12} {s['verdict']:5} {s['reason'] or '→ auditor'}  liq={s['liquidity_usd']} age={s['age_min'] and round(s['age_min'])}m")
    print(f"  still waiting (DexScreener unknown or too young): {len(sc.room)}")
    print("\nAUDITS")
    for r in d.db.all("SELECT mint, layer, name, value_text, pass FROM audits ORDER BY id"):
        print(f"  {d.coin_name(r['mint']):10} L{r['layer']} {r['name']:17} {'✓' if r['pass'] == 1 else '✗' if r['pass'] == 0 else '·'} {r['value_text']}")
    print("\nACTIVITY")
    for a in views.activity(d)["rows"][::-1]:
        print(f"  {a['title']} / {a['subtitle']} / {a['value']}")
    print("\nPUSHES (captured, not sent)")
    for p in d.notifier.sent:
        print("  " + p["text"].replace("\n", " | "), [b[1] for b in (p["buttons"] or []) if str(b[1]).startswith("http")])
    print(f"\nPAPER balance {views.state(d)['balance']}")
    await d.client.aclose()


def test_replay_offline(desk):
    """Synthetic migrations through the whole v2 pipeline with fake sources:
    Scanner -> Auditor 8 layers -> Analyst v2 score -> Brain size -> Executor dip entry -> Risk TP 50% + 40% trail."""
    import time as _t
    from agents.scanner import Scanner
    from agents.auditor import Auditor
    from agents.analyst import Analyst
    from agents.brain import Brain
    from agents.executor import Executor
    from agents.risk import Risk
    from tests.conftest import pair
    import sources as S
    good, thin = "Good111111111111111111111111111111111pump", "Thin111111111111111111111111111111111pump"
    sc, au, an, br, ex, rk = Scanner(desk), Auditor(desk), Analyst(desk), Brain(desk), Executor(desk), Risk(desk)
    desk.agents = {"scanner": sc, "auditor": au, "analyst": an, "brain": br, "executor": ex, "risk": rk}
    desk.db.kv_set("paper_cash", 30)
    P = {good: pair(good, 1.0, 90000, name="Goodcoin", symbol="GOOD", v1=40000, b1=300, b5=30, s5=10, p1=10),
         thin: pair(thin, 1.0, 12000, name="Thin", symbol="THIN")}

    async def tokens(m):
        return {x: P[x] for x in m if x in P}

    async def top10(rpc, mint, pool):
        return 12.0, 10**15

    async def acct(m):
        return {"result": {"value": {"owner": S.TOKEN_2022, "data": {"parsed": {"info": {"mintAuthority": None, "freezeAuthority": None, "supply": str(10**15)}}}}}}

    async def bal(o, m):
        return 0

    async def report(m):
        return {"creator": "Dev1", "markets": [{"pubkey": "POOL" + m[:4], "lp": {"lpLockedPct": 100}}]}

    async def graph(m):
        return [{"nodes": [{"id": "a", "holdings": 1}, {"id": "b", "holdings": 1}], "links": [{"source": "a", "target": "b"}]}]

    async def gpa(prog, m):
        return [{"pubkey": f"acc{i}", "account": {"data": {"parsed": {"info": {"owner": f"o{i}", "tokenAmount": {"amount": "5"}}}}}} for i in range(40)] if prog == S.TOKEN_2022 else []

    async def sigs(addr, limit=20):
        return [{}] * 20                                   # nobody fresh
    desk.dex.tokens = tokens; S.top10_pct = top10; desk.rpc.account_info = acct; desk.rpc.owner_balance = bal
    desk.rug.report = report; desk.rug.graph = graph; desk.rpc.program_accounts = gpa; desk.rpc.signatures = sigs; S._GPA_CACHE.clear()

    async def go():
        for m in (good, thin):
            await sc.on_migration({"mint": m, "txType": "migrate", "pool": "pump-amm"}, ts=_t.time() - 15 * 60, source="helius")
        await asyncio.sleep(0.05)
        await sc.poll_once()
        await au.audit(desk.bus.auditor.get_nowait())
        an.fresh_pct = (lambda owners: asyncio.sleep(0, result=0.0))
        await an.judge(desk.bus.analyst.get_nowait())
        await br.handle(desk.bus.brain.get_nowait())
        await ex.handle(desk.bus.executor.get_nowait())
        await rk.poll_once()                               # at its high: waits
        assert desk.db.one("SELECT status FROM signals").__getitem__("status") == "waiting"
        P[good] = pair(good, 0.84, 90000, b5=30, s5=10); await rk.poll_once()      # -16%, buyers back: buy
        P[good] = pair(good, 1.70, 90000); await rk.poll_once()                    # 2.02x: sell 50%
        P[good] = pair(good, 2.50, 90000); await rk.poll_once()                    # new peak
        P[good] = pair(good, 1.45, 90000); await rk.poll_once()                    # 42% off the top: sell the rest
    asyncio.run(go())
    acts = [(a["title"], a["subtitle"]) for a in desk.db.all("SELECT * FROM activity ORDER BY id")]
    kills = desk.db.all("SELECT reason FROM scans WHERE verdict='kill'")
    assert kills[0]["reason"] == "liq $12.0K"
    assert [a[0] for a in acts] == ["Bought GOOD", "Sold GOOD", "Sold GOOD"], acts
    assert acts[1][1] == "Executor · take profit 50%" and acts[2][1] == "Executor · trail"
    p = desk.db.one("SELECT * FROM positions WHERE mint=?", (good,))
    assert p["size_usd"] == 3.6 and p["status"] == "closed" and p["pnl_usd"] > 0       # $30 cash, score >= 80: $3.60
    assert desk.db.one("SELECT holders FROM coins WHERE mint=?", (good,))["holders"] == 40
    assert desk.db.one("SELECT source FROM coins WHERE mint=?", (good,))["source"] == "helius"
    print("\nactivity:", acts, "pnl", p["pnl_usd"], "paper cash", desk.db.kv_get("paper_cash"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--hours", type=float, default=2.0); ap.add_argument("--extra", nargs="*", default=[])
    a = ap.parse_args()
    asyncio.run(replay(a.hours, a.extra))
