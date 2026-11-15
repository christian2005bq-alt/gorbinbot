"""Trade log for savipww's Risk repo: LuxAlgo/trade-journal, self-hosted on 127.0.0.1:3010 (tools/start_journal.sh).

Every PAPER and LIVE fill (buy, partial take-profit, stop, trail, timeout, sell-all...) is appended to
data/journal/{MODE}.csv in TradingView's paper-trading export format (the journal auto-detects it), then the whole
file is committed to the journal account "FOMO desk {MODE}" through its own import API. Commit dedups, so
re-sending the file is a no-op and a journal that was down catches up on the next trade.
The journal only records: the -25% stop and every exit rule stay in desk code (agents/risk.py)."""
import asyncio, csv, datetime as dt, os
from pathlib import Path
from common import get_logger

DIR = Path(__file__).resolve().parent / "data" / "journal"
HEADER = ["Symbol", "Side", "Qty", "Fill Price", "Commission", "Closing Time", "Status"]
log = get_logger("journal")
_acct: dict[str, str] = {}
_lock = asyncio.Lock()


def path(mode):
    return DIR / f"{mode.upper()}.csv"


def symbol(desk, mint):
    c = desk.db.coin(mint) or {}
    s = (c.get("symbol") or "COIN").upper().replace(",", "").replace(" ", "")[:12]
    return f"{s}-{mint[:4]}"


def record(desk, mode, mint, side, qty, price, fee, ts=None):
    """Append one fill; never raises (a journal problem must never block a trade)."""
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        p = path(mode)
        new = not p.exists()
        t = dt.datetime.fromtimestamp(ts or dt.datetime.now().timestamp(), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        with open(p, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(HEADER)
            w.writerow([symbol(desk, mint), side, f"{qty:.6f}", f"{price:.12g}", f"{fee:.4f}", t, "Filled"])
        try:
            asyncio.get_running_loop().create_task(sync(desk, mode))
        except RuntimeError:
            pass
    except Exception as e:
        log.info("journal record failed: %s", e)


async def account(desk, mode, base):
    if mode in _acct:
        return _acct[mode]
    name = f"FOMO desk {mode.upper()}"
    r = await desk.client.get(f"{base}/api/accounts", timeout=10)
    for a in (r.json() or {}).get("accounts") or []:
        if a.get("name") == name:
            _acct[mode] = a["id"]; return a["id"]
    r = await desk.client.post(f"{base}/api/accounts", json={"name": name, "kind": "import", "currency": "USD",
                                                             "initialBalance": float(desk.s("desk.stack") or 0)}, timeout=10)
    _acct[mode] = r.json()["id"]
    return _acct[mode]


async def sync(desk, mode):
    base = (desk.s("desk.journal_url") or "").rstrip("/")
    if not base or not (base.startswith("http://127.0.0.1:") or base.startswith("http://localhost:")):
        return None      # localhost only: the journal is never reached over the network
    async with _lock:
        try:
            p = path(mode)
            if not p.exists():
                return None
            aid = await account(desk, mode, base)
            r = await desk.client.post(f"{base}/api/import", json={"mode": "commit", "content": p.read_text(), "accountId": aid,
                                                                   "fileName": p.name, "timeZone": "UTC"}, timeout=30)
            if r.status_code != 200:
                log.info("journal sync %s: HTTP %s %s", mode, r.status_code, r.text[:200]); return None
            j = r.json()
            log.info("journal sync %s: %s", mode, {k: j.get(k) for k in ("inserted", "duplicates", "skipped") if k in j})
            return j
        except Exception as e:
            log.info("journal sync %s failed (journal down?): %s", mode, type(e).__name__)
            return None
