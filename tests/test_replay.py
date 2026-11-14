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
    from agents.executor import Executor
    from agents.risk import Risk
    from common import LOGS
    import views
    live = DB()
    d = Desk(DB(Path(tmp) / "replay.db"))
    for k in ("desk.paper_start_stack", "desk.stack", "executor.stack_pct", "executor.min_ticket_usd", "executor.below_min", "analyst.mode"):
        d.settings.set(k, live.one("SELECT value FROM settings WHERE key=?", (k,)) and json.loads(live.one("SELECT value FROM settings WHERE key=?", (k,))["value"]) or d.s(k))
    d.db.kv_set("paper_cash", d.s("desk.paper_start_stack"))
    d.notifier = FakeNotifier()
    d.start_night()
    sc, au, an, ex, rk = Scanner(d), Auditor(d), Analyst(d), Executor(d), Risk(d)
    d.agents = {"scanner": sc, "auditor": au, "analyst": an, "executor": ex, "risk": rk}
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
    """Synthetic migrations through the whole pipeline with fake sources."""
    import time as _t
    from agents.scanner import Scanner
    from agents.auditor import Auditor
    from agents.analyst import Analyst
    from agents.executor import Executor
    from agents.risk import Risk
    from tests.conftest import pair
    import sources as S
    good, thin = "Good111111111111111111111111111111111pump", "Thin111111111111111111111111111111111pump"
    sc, au, an, ex, rk = Scanner(desk), Auditor(desk), Analyst(desk), Executor(desk), Risk(desk)
    desk.agents = {"scanner": sc, "auditor": au, "analyst": an, "executor": ex, "risk": rk}
    desk.settings.set("analyst.mode", "rules")
    P = {good: pair(good, 1.0, 90000, name="Goodcoin", symbol="GOOD", v1=40000, b1=300, p5=-6, b5=30, s5=10, p1=10),
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
    desk.dex.tokens = tokens; S.top10_pct = top10; desk.rpc.account_info = acct; desk.rpc.owner_balance = bal
    desk.rug.report = report; desk.rug.graph = graph; desk.rpc.program_accounts = gpa; S._GPA_CACHE.clear()

    async def go():
        for m in (good, thin):
            await sc.on_migration({"mint": m, "txType": "migrate", "pool": "pump-amm"}, ts=_t.time() - 15 * 60)
        await asyncio.sleep(0.05)
        await sc.poll_once()
        await au.audit(desk.bus.auditor.get_nowait())
        await an.judge(desk.bus.analyst.get_nowait())
        await ex.handle(desk.bus.executor.get_nowait())
        P[good] = pair(good, 1.3, 90000); await rk.poll_once()
        P[good] = pair(good, 1.3 * 0.87, 90000); await rk.poll_once()
    asyncio.run(go())
    acts = [(a["title"], a["subtitle"]) for a in desk.db.all("SELECT * FROM activity ORDER BY id")]
    kills = desk.db.all("SELECT reason FROM scans WHERE verdict='kill'")
    assert kills[0]["reason"] == "liq $12.0K"
    assert acts[0][0] == "Bought GOOD" and acts[1] == ("Sold GOOD", "Risk · trailing stop"), acts
    assert desk.db.one("SELECT holders FROM coins WHERE mint=?", (good,))["holders"] == 40


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--hours", type=float, default=2.0); ap.add_argument("--extra", nargs="*", default=[])
    a = ap.parse_args()
    asyncio.run(replay(a.hours, a.extra))
