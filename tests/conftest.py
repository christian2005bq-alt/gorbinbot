import os, sys, tempfile, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
os.environ.setdefault("DESK_LOGS", tempfile.mkdtemp(prefix="desk-test-logs-"))


class FakeNotifier:
    def __init__(self):
        self.sent = []

    async def push(self, text, mint, kind="info", buttons=None):
        self.sent.append({"text": text, "mint": mint, "kind": kind, "buttons": buttons})
        return True


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setenv("DESK_STATUS", str(tmp_path / "status"))
    import links
    from db import DB
    from desk import Desk
    links.set_ref_code("gorbindx")
    import journal
    monkeypatch.setattr(journal, "DIR", tmp_path / "journal")
    d = Desk(DB(tmp_path / "t.db"))
    d.notifier = FakeNotifier()
    d.in_night = lambda t=None: True      # tests run at any hour; the window itself is tested in test_metrics
    d.start_night()
    d.settings.set("desk.journal_url", "")    # tests never post to the real local journal
    d.settings.set("brain.timesfm_mode", "off")  # nor call GeckoTerminal / the TimesFM sidecar
    return d


def pair(mint, price=1.0, liq=100000, **kw):
    p = {"dexId": "pumpswap", "pairAddress": "POOL" + mint[:4], "baseToken": {"address": mint, "name": kw.get("name", "Test"), "symbol": kw.get("symbol", "TST")},
         "priceUsd": str(price), "liquidity": {"usd": liq}, "marketCap": kw.get("mcap", 500000),
         "volume": {"m5": kw.get("v5", 1000), "h1": kw.get("v1", 30000), "h24": kw.get("v24", 90000)},
         "txns": {"m5": {"buys": kw.get("b5", 20), "sells": kw.get("s5", 10)}, "h1": {"buys": kw.get("b1", 200), "sells": kw.get("s1", 100)}},
         "priceChange": {"m5": kw.get("p5", 1), "h1": kw.get("p1", 10), "h24": kw.get("p24", 10)}, "pairCreatedAt": 0}
    return p
