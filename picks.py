"""COPY PICKS (savipww v2 copy-picks prompt, STEPS 1-4 + 6). Read only.

DATA: FOMO's app API (links.API_BASE, unofficial) /v2/leaderboard/{24h|7d|30d} and /v2/users/{id}/swaps,
1 call per 1.2s. Checked 2026-11-14 23:30 (Guayaquil): both answer HTTP 431 {"error":"unauthorized"} without the
logged-in Privy token. The author reads that token out of the browser's network traffic; the box rules forbid
scraping a session token, so the desk only uses FOMO_TOKEN if it is present in the secrets .env (never printed,
never logged). Without it a run is stored as status "blocked" with the exact reason."""
import json, time
import httpx
import links
from common import SECRETS, now, get_logger

log = get_logger("picks")
WINDOWS = ("24h", "7d", "30d")


class Blocked(Exception):
    pass


class FomoAPI:
    """Read-only GETs, 1 call per 1.2s. Never POST, never trade endpoints."""
    MIN_GAP = 1.2

    def __init__(self, token=None, client=None):
        self.token = token if token is not None else SECRETS.get("FOMO_TOKEN", "")
        self.c = client or httpx.Client(timeout=20, headers={"User-Agent": "grokbot-desk/1.0"})
        self._last = 0.0
        self.calls = 0

    def get(self, path):
        if not path.startswith("/v2/leaderboard/") and not (path.startswith("/v2/users/") and path.endswith("/swaps")):
            raise ValueError("picks only reads leaderboard and swaps")
        gap = self.MIN_GAP - (time.time() - self._last)
        if gap > 0:
            time.sleep(gap)
        h = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        r = self.c.get(links.API_BASE + path, headers=h)
        self._last = time.time(); self.calls += 1
        if r.status_code in (401, 403, 431):
            raise Blocked(f"FOMO API {path} -> HTTP {r.status_code} unauthorized: needs Christian's logged-in FOMO token"
                          + ("" if self.token else " (no FOMO_TOKEN in the secrets)"))
        r.raise_for_status()
        return r.json()


# ---- key mapping. There is no raw sample yet (the API refuses us), so every key is looked up from a short list
# of candidates and a miss is reported in `unmapped`, never guessed into a number.
K = {
    "id": ("id", "userId", "user_id"), "handle": ("handle", "userHandle", "username"),
    "pnl": ("pnl", "pnlUsd", "realizedPnl", "profit", "pnl_usd"), "trades": ("trades", "tradeCount", "numTrades", "txCount"),
    "volume": ("volume", "volumeUsd"), "private": ("private", "isPrivate"), "restricted": ("restricted", "isRestricted"),
    "wallets": ("wallets", "addresses"),
    # swaps
    "side": ("side", "type", "direction"), "mint": ("mint", "tokenAddress", "address", "token.address"),
    "symbol": ("symbol", "tokenSymbol", "token.symbol"), "usd": ("usd", "amountUsd", "valueUsd", "usdValue", "volumeUsd"),
    "ts": ("ts", "timestamp", "createdAt", "time", "blockTime"), "mcap": ("mcap", "marketCap", "marketCapUsd"),
    "chain": ("chain", "chainName", "network"), "sig": ("signature", "txHash", "id"),
}


def pick(d, key, unmapped=None):
    for k in K[key]:
        cur = d
        for part in k.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        if cur is not None:
            return cur
    if unmapped is not None:
        unmapped.add(key)
    return None


def _rows(j):
    if isinstance(j, list):
        return j
    for k in ("data", "items", "leaderboard", "users", "swaps", "results"):
        if isinstance(j, dict) and isinstance(j.get(k), list):
            return j[k]
    return []


def _ts(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v / 1000 if v > 1e12 else float(v)
    try:
        import datetime as dt
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def norm_board(rows, unmapped):
    out = {}
    for i, r in enumerate(rows):
        uid = pick(r, "id", unmapped)
        if uid is None:
            continue
        out[str(uid)] = {"id": str(uid), "handle": pick(r, "handle", unmapped), "rank": i + 1,
                         "pnl": _num(pick(r, "pnl", unmapped)), "trades": _num(pick(r, "trades", unmapped)),
                         "private": bool(pick(r, "private")), "restricted": bool(pick(r, "restricted"))}
    return out


def _num(v):
    try:
        return float(v)
    except Exception:
        return None


def norm_swaps(rows, unmapped):
    out = []
    for r in rows:
        side = str(pick(r, "side", unmapped) or "").lower()
        out.append({"side": "buy" if "buy" in side else "sell" if "sell" in side else side, "mint": pick(r, "mint", unmapped),
                    "symbol": pick(r, "symbol"), "usd": _num(pick(r, "usd")), "ts": _ts(pick(r, "ts", unmapped)),
                    "mcap": _num(pick(r, "mcap")), "chain": str(pick(r, "chain") or "solana").lower(), "sig": pick(r, "sig")})
    return out


def one_coin(swaps, pct):
    """STEP 2 '1 coin wonder': over pct % of the last 25 swaps' $ volume in 1 coin. None = no $ key."""
    vol = {}
    have = [s for s in swaps[:25] if s.get("usd") is not None]
    if not have:
        return None
    for s in have:
        vol[s["mint"]] = vol.get(s["mint"], 0) + abs(s["usd"])
    tot = sum(vol.values()) or 1
    m, v = max(vol.items(), key=lambda kv: kv[1])
    return {"mint": m, "pct": round(100 * v / tot, 1), "wonder": 100 * v / tot > pct,
            "symbol": next((s.get("symbol") for s in have if s["mint"] == m), None)}


def why(t):
    """1 line from the numbers only (STEP 3). No hype, no guesses."""
    bits = ["green on 7d and 30d"]
    if t.get("coins_25") is not None:
        bits.append(f"{t['coins_25']} coins in the last 25 trades")
    if t.get("sell_parts"):
        bits.append("sells in parts")
    if t.get("one_coin") is None:
        bits.append("1 coin check: no data")
    return ", ".join(bits)


def make_list(boards, swaps_by_id, s, t_now=None):
    """STEP 2. boards = {'24h':{id:row}, '7d':{...}, '30d':{...}} (normalized). Returns (picks, dropped)."""
    t_now = t_now or now()
    b7, b30 = boards.get("7d", {}), boards.get("30d", {})
    dropped, cands = [], []
    for uid, r in b30.items():
        h = r.get("handle") or uid
        why_drop = None
        if r["private"] or r["restricted"]:
            why_drop = "private/restricted"
        elif (r.get("trades") or 0) < s("copy_picks.min_trades"):
            why_drop = f"under {s('copy_picks.min_trades')} trades"
        elif uid not in b7:
            why_drop = "not on both 7d and 30d"
        elif (r.get("pnl") or 0) <= 0 or (b7[uid].get("pnl") or 0) <= 0:
            why_drop = "PnL 7d or 30d <= 0"
        if why_drop:
            dropped.append({"handle": h, "why": why_drop}); continue
        cands.append(uid)
    cands.sort(key=lambda u: (-(b30[u]["pnl"] or 0), -(b7[u]["pnl"] or 0)))
    out = []
    for uid in cands[: s("copy_picks.candidates")]:
        r, sw = b30[uid], swaps_by_id.get(uid)
        h = r.get("handle") or uid
        if sw is None:
            continue
        last_ts = max((x["ts"] for x in sw if x.get("ts")), default=None)
        if not last_ts or t_now - last_ts > s("copy_picks.max_last_trade_h") * 3600:
            dropped.append({"handle": h, "why": f"last trade older than {s('copy_picks.max_last_trade_h'):g}h"}); continue
        oc = one_coin(sw, s("copy_picks.one_coin_pct"))
        if oc and oc["wonder"]:
            dropped.append({"handle": h, "why": f"1 coin wonder: {oc['pct']:g}% of last 25 swaps' $ in {oc['symbol'] or oc['mint'][:6]}"}); continue
        lb = next((x for x in sw if x["side"] == "buy"), None)
        sells = {}
        for x in sw[:25]:
            if x["side"] == "sell":
                sells[x["mint"]] = sells.get(x["mint"], 0) + 1
        t = {"id": uid, "handle": h, "rank_7d": b7[uid]["rank"], "pnl_7d": b7[uid]["pnl"], "pnl_30d": r["pnl"],
             "trades": r.get("trades"), "last_ts": last_ts, "one_coin": oc,
             "coins_25": len({x["mint"] for x in sw[:25] if x.get("mint")}), "sell_parts": any(n >= 2 for n in sells.values()),
             "last_buy": ({"mint": lb["mint"], "symbol": lb.get("symbol"), "mcap": lb.get("mcap"), "chain": lb.get("chain")} if lb else None),
             "profile_url": links.profile_url(h)}
        if lb:
            t["last_buy"]["url"] = links.coin_url(lb["mint"], lb["chain"]) if lb["chain"] in links.CHAIN_ID else links.signup_url()
            t["last_buy"]["in_chain_map"] = lb["chain"] in links.CHAIN_ID
        t["why"] = why(t)
        out.append(t)
        if len(out) >= s("copy_picks.top_n"):
            break
    return out, dropped


def _ago(ts, t_now=None):
    s = (t_now or now()) - ts
    return f"{int(s // 60)}m ago" if s < 3600 else f"{s / 3600:.0f}h ago"


def _k(v):
    if v is None:
        return "n/a"
    return f"{v / 1e6:.1f}M" if abs(v) >= 1e6 else f"{v / 1e3:.0f}K" if abs(v) >= 1e3 else f"{v:.0f}"


def message(picks, t_now=None):
    """STEP 3 text + the buttons (all URLs from links.py)."""
    lines = [f"Grok Bot · {len(picks)} traders worth copying today"]
    buttons = []
    for i, t in enumerate(picks, 1):
        lines.append(f"#{i} {t['handle']} · 7d +${_k(t['pnl_7d'])} · 30d +${_k(t['pnl_30d'])} · {int(t['trades'] or 0)} trades · last trade {_ago(t['last_ts'], t_now)}")
        lb = t.get("last_buy")
        if lb:
            lines.append(f"  last buy: {lb.get('symbol') or lb['mint'][:6]} at ${_k(lb.get('mcap'))}")
        lines.append(f"  why: {t['why']}")
        lines.append(f"  Profile: {t['profile_url']}")
        if lb:
            lines.append(f"  {'Last buy' if lb.get('in_chain_map') else 'Open FOMO'}: {lb['url']}")
        buttons.append((f"#{i} Profile", t["profile_url"]))
    lines.append("New to FOMO? " + links.signup_url())
    return "\n".join(lines), buttons


def run(d, api=None):
    """1 full run. Stores it in picks_runs (status ok|blocked|error) and returns the row."""
    api = api or FomoAPI()
    unmapped, row = set(), {"ts": now(), "status": "ok", "message": None, "picks": [], "dropped": [], "calls": 0, "error": None}
    try:
        if not api.token:
            raise Blocked("FOMO API needs Christian's logged-in FOMO token (HTTP 431 unauthorized without it); "
                          "no FOMO_TOKEN in the secrets, and the box rules forbid scraping it from the browser")
        boards = {w: norm_board(_rows(api.get(f"/v2/leaderboard/{w}")), unmapped) for w in WINDOWS}
        # only the best candidates get 1 swaps call each (~1 min of API time)
        ids = sorted([u for u in boards["30d"] if u in boards["7d"]], key=lambda u: -(boards["30d"][u]["pnl"] or 0))[: d.s("copy_picks.candidates")]
        swaps = {u: norm_swaps(_rows(api.get(f"/v2/users/{u}/swaps")), unmapped) for u in ids}
        picks, dropped = make_list(boards, swaps, d.s)
        row["message"], _ = message(picks)
        row["picks"], row["dropped"] = picks, dropped
    except Blocked as e:
        row["status"], row["error"] = "blocked", str(e)
    except Exception as e:
        row["status"], row["error"] = "error", f"{type(e).__name__}"
    row["calls"] = api.calls
    row["unmapped"] = sorted(unmapped)
    rid = d.db.exec("INSERT INTO picks_runs(ts,status,message,json) VALUES(?,?,?,?)",
                    (row["ts"], row["status"], row["message"], json.dumps({k: row[k] for k in ("picks", "dropped", "calls", "error", "unmapped")})))
    row["id"] = rid
    return row


def recent(d, n=7):
    out = []
    for r in d.db.all("SELECT * FROM picks_runs ORDER BY id DESC LIMIT ?", (n,)):
        j = json.loads(r["json"] or "{}")
        out.append({"id": r["id"], "ts": r["ts"], "status": r["status"], "message": r["message"], **j})
    return out


# ---- STEP 5 COPY ON DESK: built, OFF. copy.enabled=false and every trader switch off by default.
def new_swaps(seen: set, swaps):
    """Swaps not seen before (by signature, else ts+mint+side). First call with an empty seen = mark all, copy nothing."""
    fresh = []
    for s in swaps:
        k = s.get("sig") or f"{s.get('ts')}|{s.get('mint')}|{s.get('side')}"
        if k not in seen:
            seen.add(k); fresh.append(s)
    return fresh
