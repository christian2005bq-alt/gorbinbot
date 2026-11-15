"""v2 STEP 15.3 test_brain: cash $100, score 80 -> $12 (12%: a -25% stop costs $3); 79 -> $6; under $2 -> skip;
pool $20,000 -> max $400. Plus Christian's $30 cash and the night limits."""
import asyncio
from agents.brain import size_order, Brain


def test_spec_numbers(desk):
    s = desk.s
    r = size_order(100, 80, 1_000_000, s)
    assert r["size"] == 12.0 and r["pct"] == 12.0 and r["cap"] == "none"
    assert round(r["size"] * desk.s("risk.stop_pct") / 100, 2) == 3.0          # a -25% stop costs $3 = 3% of cash
    assert size_order(100, 79, 1_000_000, s)["size"] == 6.0
    r = size_order(10, 79, 1_000_000, s)                                       # 10*12%*50% = $0.60
    assert r["size"] is None and r["reason"] == "under $2"
    desk.settings.set("brain.max_ticket_usd", 100000)
    r = size_order(1_000_000, 90, 20_000, s)
    assert r["size"] == 400.0 and r["cap"] == "pool"
    desk.settings.set("brain.max_ticket_usd", 50)
    r = size_order(1_000_000, 90, 10_000_000, s)
    assert r["size"] == 50.0 and r["cap"] == "ticket"
    print("\n$100: score 80 -> $12 · 79 -> $6 · under $2 skip · pool $20k -> $400 · ticket cap $50")


def test_christian_30(desk):
    """$30 cash: score 80+ -> $3.60, under 80 -> $1.80 = under $2 -> skipped (said in the ticket check)."""
    assert size_order(30, 85, 50_000, desk.s)["size"] == 3.6
    assert size_order(30, 75, 50_000, desk.s)["reason"] == "under $2"
    desk.db.kv_set("paper_cash", 30)
    tc = desk.settings.ticket_check(30)
    assert tc[0] == "half" and "$3.60" in tc[1]
    assert size_order(30, 85, 50_000, desk.s, shill=0.6)["size"] is None       # shill ring halves: $1.80


def test_night_limits(desk):
    b = Brain(desk)
    assert b.night_block() is None
    desk.settings.set("brain.max_trades_night", 1)
    desk.db.exec("INSERT INTO signals(mint,ts,status,size_usd) VALUES('X',?, 'bought', 3)", (desk.night_start_ts() + 1,))
    assert b.night_block().startswith("max 1 trades")
    desk.settings.set("brain.max_trades_night", 30)
    n = desk.night()
    desk.db.exec("UPDATE nights SET start_balance=? WHERE id=?", (desk.balance() / 0.69, n["id"]))   # -31% tonight
    assert b.night_block().startswith("night brake")
    desk.in_night = lambda t=None: False
    assert b.night_block() == "outside the night window"


def test_waiting_cash_is_not_free(desk):
    desk.db.kv_set("paper_cash", 30)
    desk.db.exec("INSERT INTO signals(mint,ts,status,size_usd) VALUES('W',?, 'waiting', 3.6)", (desk.night_start_ts() + 1,))
    assert desk.free_cash() == 26.4
