"""Optional smart-money lookup (savipww's Executor repo: nansen-ai/nansen-cli).

Read only: the same call `nansen research token holders --token MINT --chain solana --smart-money` makes
(POST https://api.nansen.ai/api/v1/tgm/holders, label_type smart_money, header `apikey`). Nansen is paid: with no
NANSEN_API_KEY in the secrets .env this returns None and nothing is called. The key is read from SECRETS only and
never logged or printed. Execution stays on FOMO: nansen-cli's `trade` / `wallet` commands are never used."""
import time
from common import SECRETS

URL = "https://api.nansen.ai/api/v1/tgm/holders"
_cache: dict[str, tuple[float, dict | None]] = {}


def enabled() -> bool:
    return bool(SECRETS.get("NANSEN_API_KEY"))


async def holders(client, mint, ttl=300):
    """{'count': n smart-money holders, 'usd': their value $, 'labels': [...]} | None (no key / no data / error)."""
    key = SECRETS.get("NANSEN_API_KEY")
    if not key:
        return None
    hit = _cache.get(mint)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    out = None
    try:
        r = await client.post(URL, json={"token_address": mint, "chain": "solana", "label_type": "smart_money",
                                         "pagination": {"page": 1, "per_page": 25}},
                              headers={"apikey": key, "Content-Type": "application/json"}, timeout=20)
        if r.status_code == 200:
            rows = (r.json() or {}).get("data") or []
            usd = 0.0; labels = []
            for x in rows:
                v = x.get("value_usd") or x.get("token_value_usd") or 0
                try:
                    usd += float(v)
                except Exception:
                    pass
                lab = x.get("address_label") or x.get("label")
                if lab:
                    labels.append(str(lab)[:40])
            out = {"count": len(rows), "usd": round(usd, 2), "labels": labels[:5]}
    except Exception:
        out = None   # never raises, never logs the key
    _cache[mint] = (time.time(), out)
    return out
