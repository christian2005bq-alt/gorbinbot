"""Raw key mapping from STEP 2 (samples in logs/raw/). Agents read raw JSON ONLY through here.
A field that is not in the raw source maps to None and stays null. Never guess a key."""

# field the agents need -> exact path in the raw JSON (None = not present in that source)
PUMPPORTAL = {   # logs/raw/pumpportal_migration.json  keys: signature, mint, txType, pool
    "mint": ("mint",),
    "signature": ("signature",),
    "tx_type": ("txType",),
    "pool_kind": ("pool",),        # value is a pool TYPE label ("pump-amm"), not an address
    "pool": None,                  # no pool address in the message -> DexScreener pairAddress
    "creator": None,               # not in the message -> RugCheck report "creator"
    "name": None, "symbol": None,  # not in the message -> DexScreener baseToken
}
DEXSCREENER = {  # logs/raw/dexscreener_pair.json (list of pairs)
    "dex_id": ("dexId",),
    "pair_address": ("pairAddress",),
    "base_address": ("baseToken", "address"),
    "name": ("baseToken", "name"),
    "symbol": ("baseToken", "symbol"),
    "price_usd": ("priceUsd",),
    "liquidity_usd": ("liquidity", "usd"),
    "market_cap": ("marketCap",),
    "fdv": ("fdv",),
    "volume_m5": ("volume", "m5"),
    "volume_h1": ("volume", "h1"),
    "volume_h24": ("volume", "h24"),
    "buys_m5": ("txns", "m5", "buys"),
    "sells_m5": ("txns", "m5", "sells"),
    "buys_h1": ("txns", "h1", "buys"),
    "sells_h1": ("txns", "h1", "sells"),
    "change_m5": ("priceChange", "m5"),
    "change_h1": ("priceChange", "h1"),
    "change_h24": ("priceChange", "h24"),
    "pair_created_at": ("pairCreatedAt",),   # ms epoch
}
RUGCHECK_REPORT = {  # logs/raw/rugcheck_report.json
    "creator": ("creator",),
    "creator_balance": ("creatorBalance",),
    "detected_at": ("detectedAt",),          # ISO time RugCheck first saw the coin (curve start proxy)
    "creator_tokens": ("creatorTokens",),    # [{mint, marketCap, createdAt}] or null
    "insider_networks": ("insiderNetworks",),  # [{id,size,type,tokenAmount,currentHolding,activeAccounts}] or null
    "supply": ("token", "supply"),
    "ct_mint": ("mint",),                    # per creatorTokens entry
    "net_holding": ("currentHolding",),      # per insiderNetworks entry
    "markets": ("markets",),
    "market_pool": ("pubkey",),              # per market entry
    "market_type": ("marketType",),          # per market entry ("pump_fun_amm")
    "lp_locked_pct": ("lp", "lpLockedPct"),  # per market entry (burned LP counts as locked)
    "lp_burned_pct": None,                   # no separate burned key in the report
    "total_holders": ("totalHolders",),
    "mint_authority": ("mintAuthority",),
    "freeze_authority": ("freezeAuthority",),
}
RUGCHECK_GRAPH = {   # logs/raw/rugcheck_insiders_graph.json (list of networks)
    "nodes": ("nodes",),
    "edges": ("links",),           # edges key is "links": [{source, target}]
    "node_id": ("id",),
    "node_holdings": ("holdings",),
    "edge_source": ("source",),
    "edge_target": ("target",),
}
RPC_ACCOUNT_INFO = {  # logs/raw/rpc_getAccountInfo.json
    "owner_program": ("result", "value", "owner"),
    "mint_authority": ("result", "value", "data", "parsed", "info", "mintAuthority"),
    "freeze_authority": ("result", "value", "data", "parsed", "info", "freezeAuthority"),
    "supply": ("result", "value", "data", "parsed", "info", "supply"),
    "decimals": ("result", "value", "data", "parsed", "info", "decimals"),
}
RPC_TOKEN_ACCOUNT = {  # getProgramAccounts / getTokenAccountsByOwner jsonParsed items
    "pubkey": ("pubkey",),
    "owner": ("account", "data", "parsed", "info", "owner"),
    "delegate": ("account", "data", "parsed", "info", "delegate"),
    "amount": ("account", "data", "parsed", "info", "tokenAmount", "amount"),
    "ui_amount": ("account", "data", "parsed", "info", "tokenAmount", "uiAmount"),
}
JEV = {  # logs/raw/jev_response.json
    "model": ("model",),
    "answer": ("answers",),        # answers.{name}.noul
    "noul": ("noul",),
    "input_tokens": ("usage", "input_tokens"),
    "output_tokens": ("usage", "output_tokens"),
}

SOURCES = {"pumpportal": PUMPPORTAL, "dexscreener": DEXSCREENER, "rugcheck_report": RUGCHECK_REPORT,
           "rugcheck_graph": RUGCHECK_GRAPH, "rpc_account_info": RPC_ACCOUNT_INFO,
           "rpc_token_account": RPC_TOKEN_ACCOUNT, "jev": JEV}


def get(source: str, obj, field: str):
    path = SOURCES[source].get(field)
    if path is None or obj is None:
        return None
    cur = obj
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def num(source, obj, field):
    v = get(source, obj, field)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def table():
    rows = []
    for src, m in SOURCES.items():
        for f, p in m.items():
            rows.append((src, f, ".".join(p) if p else None))
    return rows


if __name__ == "__main__":
    for src, f, p in table():
        print(f"{src:18} {f:20} -> {p if p else 'null (not in raw JSON)'}")
