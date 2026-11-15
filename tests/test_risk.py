"""v2 STEP 15.4 test_risk: -25.1% = stop; 2.0x = sell 50%; then 40% off the top = sell the rest; 3h at +4% = timeout;
a looser stop setting never moves an open stop down. Dip: at the 10m high waits; -15% with sellers running waits;
-15% with buyers back buys; no dip in 30 min = skip "no dip"; -41% = crash."""
import asyncio, time
from agents.risk import evaluate, Risk, exit_line
from agents.executor import dip_decision, Executor
from tests.conftest import pair
import views


def mkpos(desk, mint, entry=1.0, size=3.6, stop_pct=None, opened=None):
    stop_pct = stop_pct if stop_pct is not None else desk.s("risk.stop_pct")
    desk.db.exec("INSERT OR IGNORE INTO coins(mint,name,symbol,migrated_at) VALUES(?,?,?,?)", (mint, mint[:4], mint[:4], 0))
    pid = desk.db.exec("INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,trail_active,mode,stop_pct,status,last_price,tokens,size_open,tp_done,realized_usd,fees_usd) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (mint, opened or time.time(), entry, size, entry, entry * (1 - stop_pct / 100), 0, "PAPER", stop_pct, "open", entry, size / entry, size, 0, 0, 0.1))
    desk.db.kv_set("paper_cash", float(desk.db.kv_get("paper_cash")) - size - 0.1)
    return pid


def pos(desk, pid):
    return dict(desk.db.one("SELECT * FROM positions WHERE id=?", (pid,)))


def run(desk, rk, pid, price, liq=100000):
    asyncio.run(rk.step(pos(desk, pid), price, liq))
    return pos(desk, pid)


def test_stop_tp_trail_timeout(desk):
    rk = Risk(desk)
    b = mkpos(desk, "BBBB1")
    p = run(desk, rk, b, 0.749)                  # -25.1%
    assert p["exit_reason"] == "stop" and p["status"] == "closed"
    a = mkpos(desk, "AAAA1")
    cash0 = float(desk.db.kv_get("paper_cash"))
    p = run(desk, rk, a, 2.0)                    # 2.0x -> sell 50%
    assert p["tp_done"] == 1 and p["status"] == "open" and abs(p["tokens"] - 1.8) < 1e-9
    assert round(float(desk.db.kv_get("paper_cash")) - cash0, 4) == 3.5         # $3.60 out minus the $0.10 fee
    p = run(desk, rk, a, 3.0)                    # new peak
    p = run(desk, rk, a, 3.0 * 0.61)             # 39% off the top: hold
    assert p["status"] == "open"
    p = run(desk, rk, a, 3.0 * 0.60)             # 40% off the top -> the rest
    assert p["exit_reason"] == "trail" and p["status"] == "closed" and p["pnl_usd"] > 0
    acts = [r["subtitle"] for r in desk.db.all("SELECT subtitle FROM activity WHERE mint='AAAA1' ORDER BY id")]
    assert acts == ["Executor · take profit 50%", "Executor · trail"], acts
    c = mkpos(desk, "CCCC1", opened=time.time() - 3 * 3600 - 1)
    p = run(desk, rk, c, 1.04)                   # 3h at +4%
    assert p["exit_reason"] == "dead money"
    d = mkpos(desk, "DDDD1")
    run(desk, rk, d, 1.0, liq=100000)
    p = run(desk, rk, d, 1.0, liq=15000)         # -85% liquidity in 1 poll
    assert p["exit_reason"] == "pulled"
    print("\n-25.1% stop · 2x sells 50% · 40% off the top sells the rest · 3h +4% dead money · liquidity -85% pulled")


def test_stop_never_moves_down(desk):
    rk = Risk(desk)
    old = mkpos(desk, "OLD11")                    # opened at -25%
    desk.settings.set("risk.stop_pct", 30)        # loosen
    p = run(desk, rk, old, 0.99)
    assert p["stop_pct"] == 25 and abs(p["stop_price"] - 0.75) < 1e-9
    desk.settings.set("risk.stop_pct", 20)        # tighten -> applies to open
    p = run(desk, rk, old, 0.99)
    assert p["stop_pct"] == 20
    desk.settings.set("risk.stop_pct", 30)
    p = run(desk, rk, old, 0.99)
    assert p["stop_pct"] == 20                    # never loosens back


def test_no_price_12_polls(desk):
    rk = Risk(desk)
    a = mkpos(desk, "NOPX1")
    for _ in range(11):
        asyncio.run(rk.step(pos(desk, a), None, None))
    assert pos(desk, a)["status"] == "open"
    asyncio.run(rk.step(pos(desk, a), None, None))
    assert pos(desk, a)["exit_reason"] == "no price"


def test_dip_rules(desk):
    s = desk.s
    hist = [1.0, 0.98, 0.95]
    assert dip_decision(hist, 1.0, 20, 10, s)[0] == "wait"                    # at its 10m high
    assert dip_decision(hist, 0.85, 10, 20, s)[0] == "wait"                   # -15%, sellers 2x buyers
    act, depth, high = dip_decision(hist, 0.85, 10, 15, s)
    assert act == "buy" and depth == 15.0                                      # -15%, sellers 1.5x = buyers back
    assert dip_decision(hist, 0.59, 10, 5, s)[:2] == ("crash", 41.0)          # -41% = crash


def test_no_dip_in_30_min(desk):
    ex = Executor(desk)
    desk.agents = {"executor": ex}
    m = "Wait1111111111111111111111111111111111pump"
    desk.db.exec("INSERT INTO coins(mint,symbol) VALUES(?,?)", (m, "WAIT"))
    item = {"scan": {"mint": m, "liquidityUsd": 50000}, "verdict": {"price": 1.0, "score": 85}, "audit": {"_ctx": {}},
            "brain": {"sizeUsd": 3.6, "pctOfCash": 12, "capHit": "none"}}
    out = asyncio.run(ex.handle(item))
    sid = out["signal_id"]
    assert desk.free_cash() == round(float(desk.db.kv_get("paper_cash")) - 3.6, 4)
    ex.waiting[sid]["since"] -= 31 * 60
    asyncio.run(ex.on_poll({m: pair(m, 1.0)}))
    sig = desk.db.one("SELECT status, reason FROM signals WHERE id=?", (sid,))
    assert sig["status"] == "skipped" and sig["reason"] == "no dip"


def test_dip_buy_paper(desk):
    ex = Executor(desk)
    desk.agents = {"executor": ex}
    m = "Dipp1111111111111111111111111111111111pump"
    desk.db.exec("INSERT INTO coins(mint,symbol) VALUES(?,?)", (m, "DIPP"))
    item = {"scan": {"mint": m, "liquidityUsd": 50000}, "verdict": {"price": 1.0, "score": 85}, "audit": {"_ctx": {}},
            "brain": {"sizeUsd": 3.6, "pctOfCash": 12, "capHit": "none"}}
    sid = asyncio.run(ex.handle(item))["signal_id"]
    desk.db.exec("INSERT INTO prices(mint,ts,price) VALUES(?,?,?)", (m, time.time() - 120, 1.0))
    asyncio.run(ex.on_poll({m: pair(m, 0.84, b5=20, s5=10)}))
    p = desk.db.one("SELECT * FROM positions WHERE mint=?", (m,))
    assert p and p["entry_price"] == 0.84 and p["size_usd"] == 3.6
    sig = desk.db.one("SELECT * FROM signals WHERE id=?", (sid,))
    assert sig["status"] == "bought" and sig["dip_depth_pct"] == 16.0
