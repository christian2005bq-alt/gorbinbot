"""Brain's optional TimesFM read (savipww's Brain repo: google-research/timesfm, 2.5 200M, CPU sidecar).

closes = GeckoTerminal 1-minute candles of the coin's pool -> POST 127.0.0.1:8795/forecast (sidecars/timesfm_server.py)
-> expected % move over brain.timesfm_horizon_min minutes (median) + the 10% / 90% quantiles.
brain.timesfm_mode: off | log (default: shown next to the size, sizing stays the author's score rule) |
gate (skip when the median forecast is under brain.timesfm_min_ret_pct). Any failure -> None, never blocks a buy."""
from common import get_logger

log = get_logger("brain")


async def read(desk, pool):
    mode = desk.s("brain.timesfm_mode")
    if mode == "off" or not pool:
        return None
    try:
        rows = await desk.gecko.ohlcv(pool, 120)
        closes = [float(r[4]) for r in rows if len(r) >= 5 and r[4]]
        if len(closes) < 20:
            return None
        h = int(desk.s("brain.timesfm_horizon_min"))
        r = await desk.client.post(desk.s("brain.timesfm_url").rstrip("/") + "/forecast",
                                   json={"series": closes, "horizon": h}, timeout=8)
        if r.status_code != 200:
            return None
        j = r.json(); last = closes[-1]
        pct = lambda x: round(100 * (x / last - 1), 1)
        return {"ret": pct(j["point"][-1]), "q10": pct(j["q10"][-1]), "q90": pct(j["q90"][-1]), "h": h, "ms": j.get("ms"),
                "n": len(closes)}
    except Exception as e:
        log.info("timesfm unavailable: %s", type(e).__name__)
        return None
