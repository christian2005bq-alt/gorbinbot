"""v2 STEP 15.11 test_metrics, 1 fake coin per rule: tokenWarnings disableSelling -> Scanner kill; holders -4% in
10m -> kill; insiders 38% -> layer 7 red; creator with a mint in db.rugs -> layer 3 red; curve 4 min + fresh 60%
-> organic x0.25; a 41% dip -> "crash". Plus the 22:00-06:30 night window."""
import asyncio, time, datetime as dt
import sources as S
from agents.scanner import Scanner, warnings_kill
from agents.auditor import Auditor
from agents.analyst import score_v2
from agents.executor import dip_decision
from tests.conftest import pair


def test_warnings_kill():
    assert warnings_kill({"disableSelling": True}) == "FOMO: selling off"
    assert warnings_kill({"disableSelling": False, "warnings": ["High risk token"]}) == "FOMO warns: High risk token"
    assert warnings_kill(None) is None


def _scanner_with(desk, m, **kw):
    sc = Scanner(desk)
    desk.db.exec("INSERT INTO coins(mint,migrated_at,holders0,holders0_ts) VALUES(?,?,?,?)", (m, time.time() - 15 * 60, kw.get("h0"), time.time() - 600))
    sc.room[m] = {"migrated_at": time.time() - 15 * 60, "pool": None, "pool_addr": "POOL", "top10": 10.0, "top10_ts": time.time()}
    return sc


def test_scanner_kills(desk):
    m = "Warn11111111111111111111111111111111111pump"
    sc = _scanner_with(desk, m)

    async def fw(x):
        return {"disableSelling": True}
    sc.fomo_warnings = fw
    asyncio.run(sc.evaluate(m, pair(m, liq=50000), 15))
    assert desk.db.one("SELECT reason FROM scans WHERE mint=?", (m,))["reason"] == "FOMO: selling off"
    m2 = "Hold11111111111111111111111111111111111pump"
    sc = _scanner_with(desk, m2, h0=100)

    async def h(x, first=False):
        return 96
    sc.sample_holders = h
    asyncio.run(sc.evaluate(m2, pair(m2, liq=50000), 15))
    r = desk.db.one("SELECT reason, holders_growth FROM scans WHERE mint=?", (m2,))
    assert r["reason"] == "holders leaving -4% in 10m" and r["holders_growth"] == -0.04


def _auditor(desk, m, report, creator="DevX"):
    desk.db.exec("INSERT INTO coins(mint,name,symbol,migrated_at,creator,creator_balance_at_migration,pool) VALUES(?,?,?,?,?,?,?)",
                 (m, "T", "T", time.time() - 3600, creator, 0, "POOL" + m[:4]))
    au = Auditor(desk)

    async def acct(x):
        return {"result": {"value": {"owner": S.TOKEN_PROGRAM, "data": {"parsed": {"info": {"mintAuthority": None, "freezeAuthority": None, "supply": str(10**15)}}}}}}

    async def bal(o, x):
        return 0

    async def top10(rpc, x, pool):
        return 10.0, 10**15

    async def rep(x):
        return report

    async def graph(x):
        return [{"nodes": [{"id": "a", "holdings": 1}], "links": []}]

    async def tokens(ms):
        return {k: pair(k, liq=50000) for k in ms}
    desk.rpc.account_info = acct; desk.rpc.owner_balance = bal; desk.rug.report = rep; desk.rug.graph = graph
    desk.dex.tokens = tokens
    S.top10_pct = top10
    return au


def test_insiders_38_layer7_red(desk):
    m = "Insd11111111111111111111111111111111111pump"
    rep = {"creator": "DevX", "markets": [{"pubkey": "POOL" + m[:4], "lp": {"lpLockedPct": 100}}],
           "token": {"supply": 1000}, "insiderNetworks": [{"currentHolding": 380}]}
    au = _auditor(desk, m, rep)
    out = asyncio.run(au.audit({"mint": m, "pool": "POOL" + m[:4], "liquidityUsd": 50000}, forward=False))
    l7 = [l for l in out["layers"] if l["n"] == 7][0]
    assert not out["passed"] and l7["value"] == "insiders hold 38%", out["layers"]


def test_serial_rugger_layer3_red(desk):
    m = "Rugr11111111111111111111111111111111111pump"
    desk.db.exec("INSERT INTO rugs(mint,ts,pulled_usd) VALUES(?,?,?)", ("OldRug1", time.time(), 5000))
    desk.db.exec("INSERT INTO rugs(mint,ts,pulled_usd) VALUES(?,?,?)", ("OldRug2", time.time(), 5000))
    rep = {"creator": "DevX", "creatorTokens": [{"mint": "OldRug1"}, {"mint": "OldRug2"}, {"mint": "Fine"}],
           "markets": [{"pubkey": "POOL" + m[:4], "lp": {"lpLockedPct": 100}}]}
    au = _auditor(desk, m, rep)
    out = asyncio.run(au.audit({"mint": m, "pool": "POOL" + m[:4], "liquidityUsd": 50000}, forward=False))
    assert out["layers"][2]["value"] == "dev rugged 2 before" and out["reason"] == "dev rugged 2 before"


def test_curve_and_fresh_quarter_organic(desk):
    m = "Frsh11111111111111111111111111111111111pump"
    p = pair(m, v1=25000, b1=150, s1=100)
    _, base = score_v2(p, {}, {}, None, None, desk.s)
    _, hit = score_v2(p, {}, {"curve_min": 4}, 60, None, desk.s)
    assert base["organic"] == 1.0 and hit["organic"] == 0.25 and "curve 4m" in hit["notes"] and "fresh 60%" in hit["notes"]


def test_crash_41():
    from config import DEFAULTS
    s = lambda k: DEFAULTS[k][0]
    assert dip_decision([1.0], 0.59, 10, 1, s)[:2] == ("crash", 41.0)


def test_night_window(desk):
    from desk import Desk
    d = Desk(desk.db)
    at = lambda h, m: dt.datetime.now().replace(hour=h, minute=m, second=0).timestamp()
    assert d.in_night(at(22, 0)) and d.in_night(at(3, 0)) and d.in_night(at(6, 29))
    assert not d.in_night(at(6, 30)) and not d.in_night(at(12, 0)) and not d.in_night(at(21, 59))
