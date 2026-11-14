"""HTTP clients: DexScreener (batched, rate limited), RugCheck, Solana RPC."""
import asyncio, time, collections
import httpx
import fields as F

PUMPSWAP = "pumpswap"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"


class RateLimited(Exception):
    pass


class SourceError(Exception):
    pass


class Dex:
    def __init__(self, client: httpx.AsyncClient, max_rpm=250):
        self.c = client
        self.max_rpm = max_rpm
        self.calls = collections.deque()
        self.lock = asyncio.Lock()

    async def _slot(self):
        async with self.lock:
            while True:
                t = time.time()
                while self.calls and t - self.calls[0] > 60:
                    self.calls.popleft()
                if len(self.calls) < self.max_rpm:
                    self.calls.append(t); return
                await asyncio.sleep(0.5)

    async def tokens(self, mints: list[str]) -> dict[str, dict]:
        """mint -> chosen pair (pumpswap; if several, most liquidity). Raises RateLimited on 429."""
        out = {}
        for i in range(0, len(mints), 30):
            chunk = mints[i:i + 30]
            await self._slot()
            r = await self.c.get("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(chunk), timeout=20)
            if r.status_code == 429:
                raise RateLimited()
            if r.status_code != 200:
                raise SourceError(f"dexscreener {r.status_code}")
            for p in r.json() or []:
                m = F.get("dexscreener", p, "base_address")
                if m not in chunk:
                    continue
                cur = out.get(m)
                is_ps = F.get("dexscreener", p, "dex_id") == PUMPSWAP
                liq = F.num("dexscreener", p, "liquidity_usd") or 0
                if cur is None:
                    out[m] = p
                else:
                    cur_ps = F.get("dexscreener", cur, "dex_id") == PUMPSWAP
                    cur_liq = F.num("dexscreener", cur, "liquidity_usd") or 0
                    if (is_ps and not cur_ps) or (is_ps == cur_ps and liq > cur_liq):
                        out[m] = p
        return out


class RugCheck:
    def __init__(self, client):
        self.c = client

    async def report(self, mint):
        r = await self.c.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report", timeout=30)
        if r.status_code != 200:
            raise SourceError(f"rugcheck report {r.status_code}")
        return r.json()

    async def graph(self, mint):
        r = await self.c.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/insiders/graph", timeout=30)
        if r.status_code != 200:
            raise SourceError(f"rugcheck graph {r.status_code}")
        return r.json()


class RPC:
    def __init__(self, client, url_fn):
        self.c = client
        self.url_fn = url_fn
        self.sem = asyncio.Semaphore(2)

    async def call(self, method, params, timeout=60, tries=5):
        async with self.sem:
            for i in range(tries):
                r = await self.c.post(self.url_fn(), json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=timeout)
                if r.status_code == 429:
                    await asyncio.sleep(2 * (i + 1)); continue
                if r.status_code != 200:
                    raise SourceError(f"rpc {method} http {r.status_code}")
                j = r.json()
                if "error" in j:
                    raise SourceError(f"rpc {method} error {j['error'].get('code')} {j['error'].get('message')}")
                return j
            raise SourceError(f"rpc {method} 429")

    async def account_info(self, addr):
        return await self.call("getAccountInfo", [addr, {"encoding": "jsonParsed"}])

    async def supply(self, mint):
        j = await self.call("getTokenSupply", [mint])
        v = j["result"]["value"]
        return int(v["amount"]), int(v["decimals"])

    async def largest(self, mint):
        j = await self.call("getTokenLargestAccounts", [mint], tries=2)
        return j["result"]["value"]  # [{address, amount, decimals, uiAmount}]

    async def owners(self, addrs):
        j = await self.call("getMultipleAccounts", [addrs, {"encoding": "jsonParsed"}])
        out = {}
        for a, v in zip(addrs, j["result"]["value"]):
            try:
                out[a] = v["data"]["parsed"]["info"]["owner"]
            except Exception:
                out[a] = None
        return out

    async def owner_balance(self, owner, mint):
        j = await self.call("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}])
        tot = 0
        for it in j["result"]["value"]:
            a = F.get("rpc_token_account", it, "amount")
            tot += int(a or 0)
        return tot

    async def program_accounts(self, program, mint):
        filters = [{"memcmp": {"offset": 0, "bytes": mint}}]
        if program == TOKEN_PROGRAM:
            filters.insert(0, {"dataSize": 165})
        j = await self.call("getProgramAccounts", [program, {"encoding": "jsonParsed", "filters": filters}], timeout=90)
        return j["result"]


def bonding_curve(mint: str) -> str | None:
    try:
        from solders.pubkey import Pubkey
        pda, _ = Pubkey.find_program_address([b"bonding-curve", bytes(Pubkey.from_string(mint))], Pubkey.from_string(PUMP_PROGRAM))
        return str(pda)
    except Exception:
        return None


_GPA_CACHE: dict = {}


async def all_token_accounts(rpc: RPC, mint: str, max_age=60):
    """Every token account of the mint on Token AND Token-2022 (jsonParsed). Cached 60s (Auditor layer 8 reuses it)."""
    hit = _GPA_CACHE.get(mint)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    accts = []
    for prog in (TOKEN_PROGRAM, TOKEN_2022):
        accts += await rpc.program_accounts(prog, mint)
    _GPA_CACHE[mint] = (time.time(), accts)
    if len(_GPA_CACHE) > 50:
        for k in sorted(_GPA_CACHE, key=lambda k: _GPA_CACHE[k][0])[:25]:
            _GPA_CACHE.pop(k, None)
    return accts


async def top10_pct(rpc: RPC, mint: str, pool: str | None):
    """Top 10 holders % of supply, accounts owned by the pool or the bonding curve dropped first.
    Primary: getTokenLargestAccounts (+ owners). The public RPC often 429s that one call, so on failure the
    same number is computed from getProgramAccounts (every token account, with owner and amount)."""
    supply, _ = await rpc.supply(mint)
    if not supply:
        return None, supply
    curve = bonding_curve(mint)
    excl = {x for x in (pool, curve) if x}
    try:
        largest = await rpc.largest(mint)
        addrs = [x["address"] for x in largest]
        owners = await rpc.owners(addrs) if addrs else {}
        kept = [int(x["amount"]) for x in largest if owners.get(x["address"]) not in excl and x["address"] not in excl]
    except SourceError:
        accts = await all_token_accounts(rpc, mint)
        kept = [int(F.get("rpc_token_account", a, "amount") or 0) for a in accts
                if F.get("rpc_token_account", a, "owner") not in excl and F.get("rpc_token_account", a, "pubkey") not in excl]
    return round(100 * sum(sorted(kept, reverse=True)[:10]) / supply, 2), supply
