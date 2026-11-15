"""TradingView-style technical checks for coins TradingView doesn't list.

savipww's Analyst repo is atilaahmettaner/tradingview-mcp. That server reads TradingView screener data for
centralized exchanges and listed symbols (Binance, KuCoin, MEXC, stocks...). Freshly migrated pump.fun / PumpSwap
coins are not TradingView symbols, so the MCP has nothing to return for them. Same idea, computed here from
GeckoTerminal 1-minute OHLCV (CoinGecko's free onchain API): 8 checks, tech score = passed/8*100, under 70 = dead
(only enforced when analyst.tech_gate is on; off by default = logged next to the v2 score)."""
import math


def ema(xs, n):
    if not xs:
        return None
    k = 2 / (n + 1); e = xs[0]
    for x in xs[1:]:
        e = x * k + e * (1 - k)
    return e


def rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    g = l = 0.0
    for a, b in zip(closes[-n - 1:-1], closes[-n:]):
        d = b - a
        g += max(d, 0); l += max(-d, 0)
    if l == 0:
        return 100.0
    rs = (g / n) / (l / n)
    return 100 - 100 / (1 + rs)


def checks(candles):
    """candles: [[ts, o, h, l, c, v_usd], ...] oldest first. Returns (score 0..100 | None, {check: bool|None, ...})."""
    rows = [r for r in candles or [] if len(r) >= 6 and r[4]]
    if len(rows) < 20:
        return None, {"candles": len(rows)}
    o = [float(r[1]) for r in rows]; h = [float(r[2]) for r in rows]; lo = [float(r[3]) for r in rows]
    c = [float(r[4]) for r in rows]; v = [float(r[5] or 0) for r in rows]
    last = c[-1]
    r = rsi(c)
    e9, e21 = ema(c, 9), ema(c, 21)
    tp = [(a + b + d) / 3 for a, b, d in zip(h, lo, c)]
    vs = sum(v)
    vwap = sum(p * w for p, w in zip(tp, v)) / vs if vs > 0 else None
    mean20 = sum(c[-20:]) / 20
    sd20 = math.sqrt(sum((x - mean20) ** 2 for x in c[-20:]) / 20)
    upper = mean20 + 2 * sd20
    green = sum(1 for a, b in zip(o[-10:], c[-10:]) if b >= a)
    v5, v15 = sum(v[-5:]) / 5, (sum(v[-20:-5]) / 15 if len(v) >= 20 else None)
    lows = lo[-15:]
    hi10 = max(h[-10:])
    res = {
        "rsi_ok": None if r is None else (45 <= r <= 80),          # momentum, not exhausted
        "ema_trend": e9 > e21 if e9 and e21 else None,             # EMA9 over EMA21
        "above_vwap": None if vwap is None else last >= vwap,      # buyers in control on average price
        "under_upper_band": last <= upper if sd20 > 0 else True,   # not stretched past Bollinger 2sd
        "volume_alive": None if not v15 else v5 >= 0.5 * v15,      # volume not dying
        "higher_lows": min(lows[-5:]) >= min(lows[:5]) if len(lows) >= 10 else None,
        "green_ratio": green >= 5,                                  # at least half the last 10 bars green
        "no_dump_bar": max((a - b) / a for a, b in zip(o[-10:], c[-10:]) if a > 0) < 0.25 if any(o[-10:]) else None,
    }
    known = [x for x in res.values() if x is not None]
    if len(known) < 6:
        return None, {**res, "rsi": r}
    score = round(100 * sum(1 for x in known if x) / len(known))
    return score, {**res, "rsi": round(r, 1) if r is not None else None, "vwap": vwap, "hi10": hi10}
