"""SOCIAL (v2 PART 6), the 5th part of Analyst's score. Only for coins with 8/8 green, never passes a coin.
The desk process cannot read X by itself. Plan A/B (a routine or the X plugin writing social/{mint}.json) is
not wired yet, so the default is Plan C: social.enabled=false -> w = 0, the score uses 4 parts, "social: off"."""
import json, time
from pathlib import Path
from common import ROOT

DIR = ROOT / "social"


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def value(d: dict) -> tuple[float | None, float]:
    """social/{mint}.json -> (social 0..1 or None, shill). Formula from PART 6 VALUE."""
    if not isinstance(d, dict):
        return None, 0.0
    u15, u60 = d.get("u15"), d.get("u60")
    if u15 is None:
        return None, 0.0
    accel = u15 * 4 / max(1, u60 or 0)
    v = min(u15 / 20, 1) * (0.5 if accel < 1 else 1)
    b = min((d.get("big") or 0) / 3, 1)
    c = 1.0 if d.get("catalyst") else 0.0
    cx = d.get("coinX") or None
    x = 0.0
    if cx:
        x = 1.0 if (cx.get("age_days") or 0) > 7 and (cx.get("replies") or 0) > 0 else 0.5
    sm = min((d.get("smart") or 0) / 2, 1)
    shill = float(d.get("shill") or 0)
    return round(clamp(0.30 * v + 0.15 * b + 0.15 * c + 0.10 * x + 0.30 * sm - shill), 4), shill


def read(mint: str, s) -> tuple[float | None, float, str]:
    """Returns (social or None, shill, plan). None = no answer / Social off."""
    if not s("social.enabled"):
        return None, 0.0, "C"
    p = DIR / f"{mint}.json"
    if not p.exists() or time.time() - p.stat().st_mtime > 3600:
        return None, 0.0, "A"
    try:
        v, sh = value(json.loads(p.read_text()))
        return v, sh, "A"
    except Exception:
        return None, 0.0, "A"


# ---- Plan A plumbing (v2 PART 6): ask the "social" webhook routine, wait up to social_timeout_s for social/{mint}.json.
# The routine (Grok Bot with its public X search) writes the file; the process never reads X itself.
REQ = DIR / "requests"
LOG = None


def _log(line):
    global LOG
    try:
        from common import LOGS
        LOGS.mkdir(parents=True, exist_ok=True)
        with open(LOGS / "social.log", "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _asked_last_hour():
    if not REQ.exists():
        return 0
    t = time.time() - 3600
    return sum(1 for p in REQ.glob("*.json") if p.stat().st_mtime >= t)


def coin_x(pair):
    try:
        for so in ((pair or {}).get("info") or {}).get("socials") or []:
            if (so.get("type") or "").lower() in ("twitter", "x"):
                return so.get("url") or so.get("handle")
    except Exception:
        pass
    return None


async def ask(mint, pair, s, client=None, leaders=None):
    """Returns (social or None, shill, plan). Plan C (off) = (None, 0, 'C') and logs 'social: off'."""
    import asyncio, json as _j
    from common import SECRETS
    if not s("social.enabled"):
        _log(f"{mint} plan C social: off")
        return None, 0.0, "C"
    p = DIR / f"{mint}.json"
    if not p.exists():
        if _asked_last_hour() >= s("social.max_per_h"):
            _log(f"{mint} plan A skipped: social_max_per_h reached")
            return None, 0.0, "A"
        REQ.mkdir(parents=True, exist_ok=True)
        base = (pair or {}).get("baseToken") or {}
        body = {"mint": mint, "symbol": base.get("symbol"), "name": base.get("name"), "coinX": coin_x(pair), "leaders": leaders or []}
        (REQ / f"{mint}.json").write_text(_j.dumps(body))
        url, key = SECRETS.get("SOCIAL_WEBHOOK_URL"), SECRETS.get("SOCIAL_WEBHOOK_KEY")
        if url and client is not None:
            try:
                await client.post(url, json=body, headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=15)
            except Exception as e:
                _log(f"{mint} plan A webhook failed {type(e).__name__}")
        t0 = time.time()
        while time.time() - t0 < s("social.timeout_s") and not p.exists():
            await asyncio.sleep(2)
    if not p.exists():
        _log(f"{mint} plan A late past {s('social.timeout_s')}s: social = null")
        return None, 0.0, "A"
    try:
        raw = _j.loads(p.read_text())
        v, sh = value(raw)
        _log(f"{mint} plan A raw={_j.dumps(raw)[:400]} value={v} shill={sh}")
        return v, sh, "A"
    except Exception as e:
        _log(f"{mint} plan A bad file {type(e).__name__}")
        return None, 0.0, "A"
