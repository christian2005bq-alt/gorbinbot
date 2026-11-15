"""Read-only 'Cuenta FOMO' card: Christian's real FOMO cash, holdings and recent trades.

Never clicks, never signs, never touches Withdraw/Deposit/Send. Two sources:
  1. chain (live): when desk.fomo_sol_address (his FOMO wallet, public) is set, every 15s read its
     USDC (= FOMO cash) and token balances from Solana RPC; prices via DexScreener every 60s;
     the last 10 signatures every 60s. Public chain data only, no FOMO session, no FOMO API.
  2. snapshot: tools/desk_cli.py fomo-set ... writes what was read on the FOMO screen (e.g. after the $2 test).
Stored as JSON in kv 'fomo_account'; every change emits SSE 'fomo_account' so the app updates without reloading."""
import asyncio, json
from common import now, get_logger

log = get_logger("fomo_account")
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TOKEN_PROGRAMS = ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS5EHHf2CmU5wZnzVkzUNxMQ")
POLL_S = 15          # balances (2 cheap RPC calls)
SLOW_S = 60          # prices + recent signatures


def get(d):
    raw = d.db.kv_get("fomo_account")
    try:
        return json.loads(raw) if raw else None
    except Exception:
        return None


def put(d, snap):
    snap = dict(snap)
    snap.setdefault("synced_at", now())
    d.db.kv_set("fomo_account", json.dumps(snap))
    try:
        d.bus.emit("fomo_account", snap)
    except Exception:
        pass
    return snap


def view(d):
    s = get(d) or {}
    addr = d.s("desk.fomo_sol_address") or ""
    out = {"cash": s.get("cash"), "positions": s.get("positions") or [], "trades": s.get("trades") or [],
           "synced_at": s.get("synced_at"), "source": s.get("source") or "none", "note": s.get("note"),
           "error": s.get("error"), "live": bool(addr), "poll_s": POLL_S if addr else None,
           "handle": d.s("desk.fomo_handle") or None}
    pv = sum(float(p.get("value_usd") or 0) for p in out["positions"])
    out["holdings_usd"] = round(pv, 2)
    out["total_usd"] = round(float(out["cash"] or 0) + pv, 2) if out["cash"] is not None else None
    out["age_s"] = round(now() - out["synced_at"]) if out["synced_at"] else None
    return out


async def read_chain(d, addr, prices=None):
    """One read of the wallet: USDC cash + every non-zero token. Returns a snapshot dict."""
    cash, toks = 0.0, {}
    for prog in TOKEN_PROGRAMS:
        r = await d.rpc.call("getTokenAccountsByOwner", [addr, {"programId": prog}, {"encoding": "jsonParsed", "commitment": "confirmed"}])
        for a in (r or {}).get("value", []):
            info = a["account"]["data"]["parsed"]["info"]
            amt = float(info["tokenAmount"].get("uiAmount") or 0)
            if amt <= 0:
                continue
            if info["mint"] == USDC:
                cash += amt
            else:
                toks[info["mint"]] = toks.get(info["mint"], 0) + amt
    positions = []
    for m, amt in toks.items():
        pr = (prices or {}).get(m) or {}
        val = round(amt * pr["price"], 2) if pr.get("price") else None
        if val is not None and val < 0.01:
            continue      # dust
        positions.append({"mint": m, "symbol": pr.get("symbol") or d.coin_name(m), "tokens": amt, "value_usd": val})
    positions.sort(key=lambda p: -(p["value_usd"] or 0))
    return {"cash": round(cash, 2), "positions": positions, "source": "chain"}


async def loop(d):
    prices, trades, slow_at = {}, [], 0
    while True:
        addr = d.s("desk.fomo_sol_address")
        if addr:
            try:
                if now() - slow_at >= SLOW_S:
                    slow_at = now()
                    snap0 = await read_chain(d, addr, prices)
                    mints = [p["mint"] for p in snap0["positions"]]
                    if mints:
                        import fields as F
                        pairs = await d.dex.tokens(mints[:30])
                        prices = {m: {"price": F.num("dexscreener", p, "price_usd"), "symbol": F.get("dexscreener", p, "symbol")} for m, p in pairs.items()}
                    sigs = await d.rpc.call("getSignaturesForAddress", [addr, {"limit": 10}])
                    trades = [{"ts": s.get("blockTime"), "sig": s["signature"], "ok": s.get("err") is None} for s in (sigs or [])]
                snap = await read_chain(d, addr, prices)
                snap["trades"] = trades
                snap["address_tail"] = addr[-4:]
                old = get(d) or {}
                changed = any(old.get(k) != snap.get(k) for k in ("cash", "positions", "trades"))
                snap["synced_at"] = now()
                if changed:
                    put(d, snap)                                   # SSE -> the app repaints at once
                else:
                    d.db.kv_set("fomo_account", json.dumps(snap))  # just fresher 'actualizado hace Xs'
            except Exception as e:
                log.info("fomo account read failed: %s", type(e).__name__)
                s = get(d) or {}
                s["error"] = f"read failed {type(e).__name__}"
                d.db.kv_set("fomo_account", json.dumps(s))
        await asyncio.sleep(POLL_S)
