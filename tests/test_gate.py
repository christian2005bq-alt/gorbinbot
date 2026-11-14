"""STEP 13.2 test_gate: jev mode thresholds + rules mode with fake DexScreener numbers."""
import asyncio
from agents.analyst import gate, rules_answers, Analyst
from tests.conftest import pair


def S(desk):
    return desk.s


def test_each_rejects(desk):
    s = desk.s
    base = {"alive_6h": 0.70, "organic": 0.65, "flush": 0.55, "chase": 0.30}   # score = round(100*(0.7+0.65+0.55+0.7)/4)=65 -> need flush high
    at = {"alive_6h": 0.70, "organic": 0.65, "flush": 1.0, "chase": 0.30}       # score = round(100*3.05/4)=76
    sc, ok, f = gate(at, s); assert ok, (sc, f)
    assert gate({**at, "alive_6h": 0.69}, s)[1] is False and gate({**at, "alive_6h": 0.69}, s)[2][0] == "alive 0.69"
    assert gate({**at, "organic": 0.64}, s)[2][0] == "organic 0.64"
    assert gate({**at, "chase": 0.31}, s)[2][0] == "chase 0.31"
    # score 69 rejects, score 70 at threshold passes (all other rules at threshold)
    a69 = {"alive_6h": 0.70, "organic": 0.65, "flush": 0.71, "chase": 0.30}   # 100*(0.7+0.65+0.71+0.7)/4 = 69
    a70 = {"alive_6h": 0.70, "organic": 0.65, "flush": 0.75, "chase": 0.30}   # = 70
    r69, r70 = gate(a69, s), gate(a70, s)
    assert r69[0] == 69 and r69[1] is False and r69[2] == ["score 69"]
    assert r70[0] == 70 and r70[1] is True
    print("\njev gate: alive .69 / organic .64 / chase .31 / score 69 reject; all at threshold pass")


def test_rules_mode(desk):
    desk.settings.set("analyst.mode", "rules")
    m = "RulesMint11111111111111111111111111111pump"
    desk.db.exec("INSERT INTO coins(mint,name,symbol,migrated_at) VALUES(?,?,?,?)", (m, "Rul", "RUL", 0))
    an = Analyst(desk)
    calls = {}

    async def fake_tokens(mints):
        return {x: calls["p"] for x in mints}
    desk.dex.tokens = fake_tokens
    # alive = 25000/25000 = 1, organic = 150/150 = 1, flush 0, chase = 24/80 = .30 -> score round(100*(1+1+0+.7)/4)=68 -> reject score
    calls["p"] = pair(m, v1=25000, b1=150, p5=1, p1=24)
    out = asyncio.run(an.judge({"scan": {"mint": m, "name": "Rul"}, "audit": {"layers": [], "_ctx": {"bundled": 0}}}))
    assert out["model"] == "rules" and out["inputTokens"] == 0 and out["failed"] == ["score 68"]
    # flush 1 (m5 -6%, buys>=sells) -> score round(100*(1+1+1+.7)/4)=92 (92.5, Python round) pass
    calls["p"] = pair(m, v1=25000, b1=150, p5=-6, b5=30, s5=10, p1=24)
    out = asyncio.run(an.judge({"scan": {"mint": m, "name": "Rul"}, "audit": {"layers": [], "_ctx": {"bundled": 0}}}))
    assert out["passed"] and out["score"] == 92
    # bundled 3+ halves organic -> .5 < .65 reject; chase .31 reject
    calls["p"] = pair(m, v1=25000, b1=150, p5=-6, b5=30, s5=10, p1=24.8)
    out = asyncio.run(an.judge({"scan": {"mint": m, "name": "Rul"}, "audit": {"layers": [], "_ctx": {"bundled": 3}}}))
    assert out["failed"][0] == "organic 0.50" and "chase 0.31" in out["failed"]
    rows = desk.db.all("SELECT subtitle FROM activity WHERE kind='rejected'")
    assert rows and all(r["subtitle"].startswith("Analyst (rules) · ") for r in rows), rows
    print("\nrules mode rows:", [r["subtitle"] for r in rows])


def test_jev_error_never_falls_back(desk):
    desk.settings.set("analyst.mode", "jev")
    m = "JevMint111111111111111111111111111111pump"
    desk.db.exec("INSERT INTO coins(mint,name,symbol,migrated_at) VALUES(?,?,?,?)", (m, "J", "J", 0))
    an = Analyst(desk)

    async def fake_tokens(mints):
        return {x: pair(x) for x in mints}

    async def broken(state):
        return None, "no answer"
    desk.dex.tokens = fake_tokens
    an.jev = broken
    out = asyncio.run(an.judge({"scan": {"mint": m, "name": "J"}, "audit": {"layers": [], "_ctx": {}}}))
    assert out["failed"] == ["no answer"] and not out["passed"]
