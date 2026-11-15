"""Live feed + status strip, the liq-kill case (AURA, liq $44.1K killed while the rule says $20K),
the settings-slider step bug, the PAPER/LIVE gate on /api/settings, and the read-only Cuenta FOMO card."""
import asyncio, json, shutil, subprocess, time
from pathlib import Path
import pytest
from tests.conftest import pair
from tests.test_metrics import _scanner_with

AURA = "EvbSSzACWAxqFhXdiPypjv6jMhRfHU257x65oFrjpump"


def test_liq_44k_passes_the_20k_rule(desk):
    """$44.1K is above the v2 minimum ($20K): the liquidity rule must not kill it."""
    desk.settings.set("scanner.min_liquidity_usd", 20000)
    sc = _scanner_with(desk, AURA)
    asyncio.run(sc.evaluate(AURA, pair(AURA, liq=44130.68, p1=-22.7), 15))
    r = desk.db.one("SELECT verdict, reason FROM scans WHERE mint=?", (AURA,))
    assert r is not None and not (r["reason"] or "").startswith("liq ")


def test_liq_kill_comes_only_from_the_setting(desk):
    """What happened on 2026-11-14: the app slider stored $150,985, so $44.1K was killed as 'liq $44.1K'."""
    desk.settings.set("scanner.min_liquidity_usd", 150985)
    sc = _scanner_with(desk, AURA)
    asyncio.run(sc.evaluate(AURA, pair(AURA, liq=44130.68), 15))
    assert desk.db.one("SELECT reason FROM scans WHERE mint=?", (AURA,))["reason"] == "liq $44.1K"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_slider_can_pick_20k_and_never_jumps_50k():
    js = Path(__file__).resolve().parents[1] / "web" / "slider.js"
    code = f"""const S=require({json.dumps(str(js))});
      const vals=[...Array(201).keys()].map(p=>S.valueAt(1000,1e7,'float',p));
      console.log(JSON.stringify({{p20:S.valueAt(1000,1e7,'float',S.posFor(1000,1e7,'float',20000)),
        has20:vals.includes(20000), first:vals.slice(0,3), maxgapUnder100k:Math.max(...vals.filter(v=>v<=100000).map((v,i,a)=>i?v-a[i-1]:0)),
        dev:S.valueAt(0,100,'float',S.posFor(0,100,'float',5))}}));"""
    out = json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)
    assert out["p20"] == 20000 and out["has20"]
    assert out["first"][0] == 1000 and out["maxgapUnder100k"] <= 10000
    assert out["dev"] == 5


def test_decisions_feed_and_strip(desk):
    import views
    desk.decision("scanner", AURA, "waiting", "waiting room · helius")
    desk.decision("scanner", AURA, "kill", "liq $3.1K")
    L = views.live(desk)
    assert L["feed"][0]["verdict"] == "kill" and L["feed"][0]["reason"] == "liq $3.1K"
    assert L["feed"][0]["short"] == "EvbS…pump" and len(L["feed"][0]["time"]) == 8
    assert {a["name"] for a in L["agents"]} == {"scanner", "auditor", "analyst", "brain", "executor", "risk"}
    assert set(L["window"]) >= {"open", "start", "end", "closes_in_s", "opens_in_s"}
    assert L["window"]["start"] == "22:00" and L["window"]["end"] == "06:30"
    assert L["rules"]["min_liquidity_usd"] == desk.s("scanner.min_liquidity_usd")


def test_decision_emits_sse(desk):
    q = desk.bus.subscribe()
    desk.decision("auditor", AURA, "reject", "dev holds 31%")
    ev, data = q.get_nowait()
    assert ev == "decision" and json.loads(data)["reason"] == "dev holds 31%"


def _client(desk, monkeypatch):
    from fastapi.testclient import TestClient
    import api
    monkeypatch.setitem(api.SECRETS, "APP_TOKEN", "test-token")
    return TestClient(api.make_app(desk)), {"Authorization": "Bearer test-token"}


def test_settings_cannot_flip_live(desk, monkeypatch):
    c, h = _client(desk, monkeypatch)
    r = c.post("/api/settings", json={"desk.mode": "LIVE"}, headers=h)
    assert r.status_code == 400 and desk.mode() == "PAPER"
    r = c.post("/api/mode", json={"mode": "LIVE"}, headers=h)
    assert r.status_code == 400 and desk.mode() == "PAPER"


def test_live_and_fomo_endpoints(desk, monkeypatch):
    import fomo_account
    c, h = _client(desk, monkeypatch)
    assert c.get("/api/live").status_code == 401
    desk.decision("scanner", AURA, "kill", "liq $2")
    assert c.get("/api/live", headers=h).json()["feed"][0]["reason"] == "liq $2"
    fomo_account.put(desk, {"cash": 37.89, "positions": [], "trades": [], "source": "screen"})
    f = c.get("/api/fomo_account", headers=h).json()
    assert f["cash"] == 37.89 and f["total_usd"] == 37.89 and f["live"] is False and f["age_s"] is not None


def test_fomo_chain_read(desk):
    """Chain read: USDC = cash, other tokens = positions. Read-only RPC calls only."""
    import fomo_account
    calls = []

    async def call(method, params, **kw):
        calls.append(method)
        if params[1]["programId"].startswith("Tokenkeg"):
            return {"value": [
                {"account": {"data": {"parsed": {"info": {"mint": fomo_account.USDC, "tokenAmount": {"uiAmount": 37.89}}}}}},
                {"account": {"data": {"parsed": {"info": {"mint": "Bonk", "tokenAmount": {"uiAmount": 1000.0}}}}}}]}
        return {"value": []}
    desk.rpc.call = call
    snap = asyncio.run(fomo_account.read_chain(desk, "Addr", {"Bonk": {"price": 0.002, "symbol": "BONK"}}))
    assert snap["cash"] == 37.89 and snap["positions"][0]["symbol"] == "BONK" and snap["positions"][0]["value_usd"] == 2.0
    assert set(calls) == {"getTokenAccountsByOwner"}
