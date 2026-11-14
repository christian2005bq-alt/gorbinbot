"""Settings with defaults (STEP 10), validation, change log."""
import json
from common import now

# key: (default, min, max, type, label)
DEFAULTS = {
    "scanner.min_liquidity_usd": (40000, 1000, 10_000_000, float, "min liquidity $"),
    "scanner.max_top10_pct": (25, 1, 100, float, "max top 10 %"),
    "scanner.max_h1_change_pct": (80, 1, 10000, float, "max 1h change %"),
    "scanner.poll_s": (60, 15, 600, int, "poll seconds"),
    "scanner.min_pool_age_min": (10, 0, 240, float, "min pool age min"),
    "scanner.max_wait_min": (60, 5, 720, float, "max wait min"),
    "scanner.runner_h24_pct": (300, 10, 100000, float, "runner 24h %"),
    "scanner.ws_silent_s": (120, 30, 1800, int, "websocket silent s"),
    "scanner.max_dex_rpm": (250, 10, 290, int, "DexScreener req/min"),
    "auditor.enabled": (True, None, None, bool, "take apart before buying"),
    "auditor.max_dev_pct": (5, 0, 100, float, "max dev %"),
    "auditor.max_top10_pct": (25, 1, 100, float, "max top 10 %"),
    "auditor.min_lp_locked_pct": (99, 0, 100, float, "min LP locked %"),
    "auditor.max_liq_drop_pct": (50, 1, 100, float, "max liquidity drop %"),
    "auditor.min_pool_age_min": (10, 0, 240, float, "min pool age min"),
    "auditor.max_bundled": (5, 1, 1000, int, "max bundled"),
    "auditor.max_delegated_accounts": (10, 1, 100000, int, "max delegated accounts"),
    "auditor.retries": (3, 0, 10, int, "retries"),
    "analyst.mode": ("jev", None, None, str, "mode jev|rules"),
    "analyst.min_alive_6h": (0.70, 0, 1, float, "min alive 6h"),
    "analyst.min_organic": (0.65, 0, 1, float, "min organic"),
    "analyst.max_chase": (0.30, 0, 1, float, "max chase"),
    "analyst.min_score": (70, 0, 100, int, "min score"),
    "analyst.timeout_s": (10, 2, 60, int, "timeout s"),
    "analyst.max_state_chars": (3000, 200, 10000, int, "max state chars"),
    "analyst.rules.alive_volume_h1": (25000, 100, 10_000_000, float, "alive volume 1h $"),
    "analyst.rules.organic_buys_h1": (150, 1, 100000, float, "organic buys 1h"),
    "analyst.rules.bundled_penalty": (0.5, 0, 1, float, "bundled penalty"),
    "analyst.rules.bundled_from": (3, 1, 1000, int, "bundled penalty from wallets"),
    "analyst.rules.flush_drop_m5_pct": (5, 0.1, 100, float, "flush drop 5m %"),
    "analyst.rules.chase_h1_pct": (80, 1, 10000, float, "chase 1h %"),
    "executor.stack_pct": (8, 0.1, 100, float, "stack %"),
    "executor.max_pool_pct": (2, 0.01, 100, float, "max pool %"),
    "executor.min_ticket_usd": (47.50, 5, 100000, float, "min ticket $"),
    "executor.below_min": ("bump", None, None, str, "below min bump|skip"),
    "executor.recheck_liq_drop_pct": (20, 1, 100, float, "recheck liquidity drop %"),
    "executor.recheck_price_up_pct": (15, 1, 1000, float, "recheck price up %"),
    "executor.confirm_window_min": (5, 1, 60, float, "confirm window min"),
    "risk.poll_s": (15, 5, 120, int, "poll seconds"),
    "risk.stop_pct": (6, 0.5, 90, float, "stop %"),
    "risk.trail_start_pct": (20, 1, 1000, float, "trail start %"),
    "risk.trail_pct": (12, 0.5, 90, float, "trail %"),
    "risk.timeout_h": (3, 0.1, 72, float, "timeout h"),
    "risk.timeout_min_gain_pct": (5, 0, 1000, float, "timeout min gain %"),
    "risk.confirm_window_min": (2, 0.5, 60, float, "confirm window min"),
    "risk.no_price_polls": (4, 1, 100, int, "no price polls"),
    "desk.mode": ("PAPER", None, None, str, "mode"),
    "desk.paper_start_stack": (200, 10, 10_000_000, float, "paper start stack $"),
    "desk.stack": (200, 0, 100_000_000, float, "LIVE stack $"),
    "desk.report_time": ("08:00", None, None, str, "report time"),
    "desk.notifier": ("telegram", None, None, str, "notifier"),
    "desk.rpc_url": ("https://api.mainnet-beta.solana.com", None, None, str, "rpc url"),
    "desk.push_rejects": (False, None, None, bool, "push rejects"),
    "desk.fees_ref_discount": (0.10, 0, 1, float, "fees ref discount"),
    "desk.fomo_handle": ("", None, None, str, "FOMO handle"),
}
CHOICES = {"analyst.mode": ("jev", "rules"), "executor.below_min": ("bump", "skip"),
           "desk.mode": ("PAPER", "LIVE"), "desk.notifier": ("telegram", "webpush")}
ALIASES = {
    "stop": "risk.stop_pct", "trail": "risk.trail_pct", "trail start": "risk.trail_start_pct",
    "timeout": "risk.timeout_h", "stack pct": "executor.stack_pct", "stack_pct": "executor.stack_pct",
    "min liquidity": "scanner.min_liquidity_usd", "liquidity": "scanner.min_liquidity_usd",
    "top10": "scanner.max_top10_pct", "top 10": "scanner.max_top10_pct", "min score": "analyst.min_score",
    "score": "analyst.min_score", "alive": "analyst.min_alive_6h", "organic": "analyst.min_organic",
    "chase": "analyst.max_chase", "dev": "auditor.max_dev_pct", "bundled": "auditor.max_bundled",
    "below min": "executor.below_min", "rpc": "desk.rpc_url", "rpc_url": "desk.rpc_url",
    "report time": "desk.report_time", "pool pct": "executor.max_pool_pct", "min ticket": "executor.min_ticket_usd",
}
# Settings shown as signed negative percent in chat replies ("stop -6% -> -8%")
NEG_PCT = {"risk.stop_pct"}


class Settings:
    def __init__(self, db):
        self.db = db

    def get(self, key):
        row = self.db.one("SELECT value FROM settings WHERE key=?", (key,))
        if row is None:
            return DEFAULTS[key][0] if key in DEFAULTS else None
        try:
            return json.loads(row["value"])
        except Exception:
            return row["value"]

    def all(self):
        return {k: self.get(k) for k in DEFAULTS}

    def resolve(self, name: str):
        n = name.strip().lower().replace("-", "_")
        if n in DEFAULTS:
            return n
        if n.replace("_", " ") in ALIASES:
            return ALIASES[n.replace("_", " ")]
        if n in ALIASES:
            return ALIASES[n]
        hits = [k for k in DEFAULTS if k.split(".")[-1] == n or k.split(".")[-1] == n.replace(" ", "_")]
        return hits[0] if len(hits) == 1 else None

    def validate(self, key, value):
        if key not in DEFAULTS:
            raise ValueError(f"unknown setting {key}")
        default, lo, hi, typ, _ = DEFAULTS[key]
        if typ is bool:
            if isinstance(value, str):
                value = value.strip().lower() in ("1", "true", "on", "yes")
            return bool(value)
        if typ is str:
            v = str(value).strip()
            if key in CHOICES:
                m = {c.lower(): c for c in CHOICES[key]}
                if v.lower() not in m:
                    raise ValueError(f"{key} must be one of {', '.join(CHOICES[key])}")
                v = m[v.lower()]
            if key == "desk.report_time":
                hh, mm = v.split(":"); assert 0 <= int(hh) < 24 and 0 <= int(mm) < 60
            if key == "desk.rpc_url" and not v.startswith("https://"):
                raise ValueError("rpc_url must start with https://")
            return v
        try:
            v = typ(float(str(value).replace("%", "").replace("$", "").replace(",", "")))
        except Exception:
            raise ValueError(f"{key} needs a number")
        if key in NEG_PCT:
            v = abs(v)
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            raise ValueError(f"{key} out of range: {lo} to {hi}")
        return v

    def set(self, key, value, who="app", force=False):
        v = self.validate(key, value) if not force else value
        old = self.get(key)
        self.db.exec("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                     (key, json.dumps(v), now()))
        self.db.exec("INSERT INTO change_log(ts,key,old,new,who) VALUES(?,?,?,?,?)", (now(), key, json.dumps(old), json.dumps(v), who))
        return old, v

    # STEP 10 ticket check
    def ticket_check(self, stack=None):
        sp = self.get("executor.stack_pct"); mt = self.get("executor.min_ticket_usd"); bm = self.get("executor.below_min")
        if stack is None:
            stack = self.stack_now()
        min_stack = mt / (sp / 100)
        if stack >= min_stack:
            return None
        if bm == "bump":
            p = round(100 * mt / stack, 2) if stack else 0
            return ("bump", f"tickets bumped to ${mt:.2f} = {p}% of stack")
        return ("skip", f"every coin will be skipped, stack under ${min_stack:,.2f}. Switch below_min to bump or raise the stack.")

    def stack_now(self):
        if self.get("desk.mode") == "PAPER":
            r = self.db.one("SELECT value FROM kv WHERE key='paper_cash'")
            return float(r["value"]) if r else float(self.get("desk.paper_start_stack"))
        return float(self.get("desk.stack"))
