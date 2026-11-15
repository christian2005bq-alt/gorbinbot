"""savipww's 5 repos folded in: GeckoTerminal source, TradingView-style checks, Nansen (off without key), journal."""
import asyncio, csv
import httpx
import pytest
import tech, journal, smart_money, sources as S
from tests.conftest import pair


def candles(trend=1.0, n=60):
    out, p = [], 1.0
    for i in range(n):
        o = p; p = p * (1 + 0.004 * trend) + (0.002 if i % 3 == 0 else -0.001) * p
        out.append([i * 60, o, max(o, p) * 1.002, min(o, p) * 0.998, p, 100 + i])
    return out


def test_tech_up_vs_down():
    up, ups = tech.checks(candles(1.0))
    dn, _ = tech.checks(candles(-1.5))
    assert up is not None and dn is not None and up > dn
    assert set(k for k, v in ups.items() if isinstance(v, bool) or v is None) >= {"rsi_ok", "ema_trend", "above_vwap", "no_dump_bar"}
    assert tech.checks(candles(1.0, 10))[0] is None          # too few candles -> unknown, never a kill


def test_gecko_new_pools_parse():
    body = {"data": [
        {"attributes": {"address": "POOL1", "pool_created_at": "2026-11-15T03:37:00Z", "reserve_in_usd": "1500.5"},
         "relationships": {"dex": {"data": {"id": "pumpswap"}}, "base_token": {"data": {"id": "solana_ABCpump"}},
                           "quote_token": {"data": {"id": "solana_" + S.WSOL}}}},
        {"attributes": {"address": "POOL2", "pool_created_at": "2026-11-15T03:37:00Z"},
         "relationships": {"dex": {"data": {"id": "pump-fun"}}, "base_token": {"data": {"id": "solana_XYZpump"}},
                           "quote_token": {"data": {"id": "solana_" + S.WSOL}}}}]}
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    pools = asyncio.run(S.Gecko(client).new_pumpswap_pools(pages=1))
    assert [p["mint"] for p in pools] == ["ABCpump"] and pools[0]["liq_usd"] == 1500.5 and pools[0]["created_ts"]


def test_nansen_off_without_key(monkeypatch):
    monkeypatch.setitem(smart_money.SECRETS, "NANSEN_API_KEY", "") if "NANSEN_API_KEY" in smart_money.SECRETS else None
    called = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: called.append(r) or httpx.Response(200, json={})))
    assert not smart_money.enabled()
    assert asyncio.run(smart_money.holders(client, "M" * 44)) is None and not called


def test_journal_logs_buy_and_sell(desk):
    mint = "J" * 40 + "pump"
    desk.db.exec("INSERT OR IGNORE INTO coins(mint,migrated_at,symbol) VALUES(?,?,?)", (mint, 0, "JRN"))
    journal.record(desk, "PAPER", mint, "Buy", 1000.0, 0.002, 0.1)
    journal.record(desk, "PAPER", mint, "Sell", 500.0, 0.004, 0.1)
    rows = list(csv.reader(open(journal.path("PAPER"))))
    assert rows[0] == journal.HEADER and [r[1] for r in rows[1:]] == ["Buy", "Sell"] and rows[1][0] == "JRN-JJJJ"
    assert asyncio.run(journal.sync(desk, "PAPER")) is None     # journal_url empty in tests -> never posts


def test_brain_timesfm_gate(desk, monkeypatch):
    import forecast
    from agents.brain import Brain
    async def fake(d, pool):
        return {"ret": -12.0, "q10": -30.0, "q90": 5.0, "h": 15, "ms": 100, "n": 60}
    monkeypatch.setattr(forecast, "read", fake)
    desk.settings.set("brain.timesfm_mode", "gate")
    mint = "T" * 40 + "pump"
    item = {"scan": {"mint": mint, "liquidityUsd": 50000, "pool": "P"}, "verdict": {"score": 85, "parts": {}}}
    out = asyncio.run(Brain(desk).handle(item))
    assert out["sizeUsd"] is None and "TimesFM" in out["reason"]
    desk.settings.set("brain.timesfm_mode", "log")
    out = asyncio.run(Brain(desk).handle(item))
    assert out["sizeUsd"] and out["forecast"]["ret"] == -12.0
