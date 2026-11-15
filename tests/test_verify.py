"""v2 STEP 15.6 test_verify: a fake "Bought" screen with no swap in the API -> "unverified", and no 2nd click."""
import asyncio
import verify as V


class FakeAPI:
    def __init__(self, swaps, bal_seq):
        self._swaps, self._bal = swaps, list(bal_seq)

    async def swaps(self):
        return self._swaps

    async def chain_balance(self, mint):
        return self._bal.pop(0) if len(self._bal) > 1 else self._bal[0]


class FakeLane:
    def __init__(self, api):
        self.api = api


def test_bought_screen_without_swap_is_unverified(monkeypatch):
    monkeypatch.setitem(V.FOMO_SWAP, "list", ("items",))
    monkeypatch.setitem(V.FOMO_SWAP, "mint", ("mint",))
    monkeypatch.setitem(V.FOMO_SWAP, "side", ("side",))
    monkeypatch.setitem(V.FOMO_SWAP, "usd", ("usd",))
    lane = FakeLane(FakeAPI({"items": []}, [100, 100]))
    out = asyncio.run(V.verify_after(lane, "buy", "MINT", 2.0, 100, timeout=1))
    assert out["api_ok"] is False and out["chain_ok"] is False
    lane = FakeLane(FakeAPI({"items": [{"mint": "MINT", "side": "buy", "usd": 2.02}]}, [100, 250]))
    out = asyncio.run(V.verify_after(lane, "buy", "MINT", 2.0, 100, timeout=3))
    assert out["api_ok"] is True and out["chain_ok"] is True


def test_unmapped_api_is_never_ok():
    """Before the first real swaps sample is mapped, api_ok stays None -> a LIVE click can only end unverified."""
    assert V.api_match({"anything": 1}, "buy", "M", 2.0) is None


def test_executor_never_reclicks_unverified(desk):
    """Lane returns unverified with screen_ok: 1 click, the position is guarded, no 2nd order."""
    from agents.executor import Executor
    from tests.conftest import pair
    calls = []

    class Lane:
        def armed(self):
            return True

        async def order(self, side, mint, usd, **kw):
            calls.append((side, mint, usd, kw.get("dry")))
            return {"order_id": 1, "status": "unverified", "screen_ok": True, "api_ok": False, "chain_ok": None}
    desk.lane = Lane()
    desk.settings.set("desk.mode", "LIVE")
    desk.db.kv_set("autoclick.test_ok", "1")
    desk.settings.set("desk.autoclick", "on")
    ex = Executor(desk); desk.agents = {"executor": ex}
    m = "Unv11111111111111111111111111111111111pump"
    desk.db.exec("INSERT INTO coins(mint,symbol) VALUES(?,?)", (m, "UNV"))
    item = {"scan": {"mint": m, "liquidityUsd": 50000}, "verdict": {"price": 1.0, "score": 85}, "audit": {"_ctx": {}},
            "brain": {"sizeUsd": 2.0, "pctOfCash": 6, "capHit": "none"}}
    sid = asyncio.run(ex.handle(item))["signal_id"]
    import time
    desk.db.exec("INSERT INTO prices(mint,ts,price) VALUES(?,?,?)", (m, time.time() - 60, 1.0))
    asyncio.run(ex.on_poll({m: pair(m, 0.84, b5=20, s5=10)}))
    asyncio.run(ex.on_poll({m: pair(m, 0.80, b5=20, s5=10)}))
    assert len(calls) == 1 and calls[0][3] is False
    assert desk.db.one("SELECT COUNT(*) c FROM positions WHERE mint=?", (m,))["c"] == 1
    assert any("Unverified" in p["text"] for p in desk.notifier.sent)
