"""VERIFY (v2 STEP 9), after every real click: screen + FOMO API + chain.
  screen  "Bought" / "Sold" read from the page (browser.py)
  api     /v2/users/{id}/swaps page 1 has a new swap of this mint, right side, $ within [3]% of the order
  chain   RPC token balance of the FOMO solana address for this mint went up (buy) or down (sell)
The FOMO session token is read from Chrome's own requests to the FOMO API (CDP), held in memory only:
never printed, logged, stored in the db, the app or a push.
The swap JSON keys are NOT known yet (no raw sample before Christian logs in). fields.FOMO_SWAP stays empty
until the first real response is saved to logs/raw/fomo_swaps.json and mapped, and until then api_ok = None,
so every LIVE click ends "unverified" (safe: no double clicks, Risk still guards the position)."""
import asyncio, json, time
import httpx
import links
from common import LOGS, now, get_logger

log = get_logger("verify")
BASE = links.API_BASE

# raw key mapping, filled from logs/raw/fomo_swaps.json after the first logged-in read. None = unknown.
FOMO_SWAP = {"list": None, "mint": None, "side": None, "usd": None, "ts": None}
FOMO_USER = {"id": None, "solana_address": None}
STABLES = {"USDC", "USDT", "SOL", "WETH"}


def _get(obj, path):
    if path is None:
        return None
    cur = obj
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        elif isinstance(cur, list) and isinstance(k, int) and k < len(cur):
            cur = cur[k]
        else:
            return None
    return cur


class FomoAPI:
    def __init__(self, desk):
        self.d = desk
        self._tok = None
        self._tok_ts = 0.0
        self.gap = 1.2
        self.last_call = 0.0

    def on_request(self, req):
        """Playwright request hook: keep the Bearer token of the app's own API calls (memory only)."""
        try:
            if links.is_api(req.url):
                h = req.headers.get("authorization") or ""
                if h.startswith("Bearer ") and len(h) > 20:
                    self._tok, self._tok_ts = h[7:], time.time()
        except Exception:
            pass

    def has_token(self):
        return bool(self._tok) and time.time() - self._tok_ts < 55 * 60

    async def get(self, path, save_raw=None):
        if not self.has_token():
            return None
        wait = self.last_call + self.gap - time.time()
        if wait > 0:
            await asyncio.sleep(wait)
        self.last_call = time.time()
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(BASE + path, headers={"Authorization": f"Bearer {self._tok}"})
        except Exception:
            return None
        if r.status_code == 429:
            self.gap = min(20, self.gap * 2); return None
        if r.status_code == 401:
            self._tok = None; return None
        if r.status_code != 200:
            return None
        self.gap = max(1.2, self.gap * 0.9)
        j = r.json()
        if save_raw:
            p = LOGS / "raw" / save_raw
            if not p.exists():
                p.write_text(json.dumps(j)[:200000])
        return j

    async def chain_balance(self, mint):
        addr = self.d.s("desk.fomo_sol_address")
        if not addr:
            return None
        try:
            return await self.d.rpc.owner_balance(addr, mint)
        except Exception:
            return None

    async def swaps(self):
        uid = self.d.db.kv_get("fomo.user_id")
        if not uid:
            return None
        return await self.get(f"/v2/users/{uid}/swaps", save_raw="fomo_swaps.json")


def api_match(swaps_json, side, mint, usd, tol_pct=3.0):
    """True / False if the mapping is known, None if FOMO_SWAP keys are not mapped yet."""
    if swaps_json is None or FOMO_SWAP["list"] is None or FOMO_SWAP["mint"] is None:
        return None
    for sw in _get(swaps_json, FOMO_SWAP["list"]) or []:
        if _get(sw, FOMO_SWAP["mint"]) != mint:
            continue
        sd = _get(sw, FOMO_SWAP["side"])
        if sd and str(sd).lower() != side:
            continue
        v = _get(sw, FOMO_SWAP["usd"])
        if usd is None or v is None:
            return True
        try:
            if abs(float(v) - usd) <= usd * tol_pct / 100:
                return True
        except (TypeError, ValueError):
            pass
    return False


async def verify_after(lane, side, mint, usd, chain_before, timeout=30):
    """Poll api + chain for up to timeout s. Returns api_ok, chain_ok, chain_na, fill_usd."""
    out = {"api_ok": None, "chain_ok": None, "chain_na": chain_before is None, "fill_usd": None}
    api = lane.api
    t_end = time.time() + timeout
    while time.time() < t_end:
        if api:
            out["api_ok"] = api_match(await api.swaps(), side, mint, usd)
            if not out["chain_na"]:
                b = await api.chain_balance(mint)
                if b is not None:
                    out["chain_ok"] = (b > chain_before) if side == "buy" else (b < chain_before)
        if out["api_ok"] and (out["chain_ok"] or out["chain_na"]):
            break
        await asyncio.sleep(2)
    return out
