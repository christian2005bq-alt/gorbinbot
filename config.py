"""Settings with defaults (STEP 10), validation, change log."""
import json
from common import now

# key: (default, min, max, type, label)
DEFAULTS = {
    # ---- scanner (v2 STEP 12)
    "scanner.min_liquidity_usd": (20000, 1000, 10_000_000, float, "min liquidity $"),
    "scanner.max_top10_pct": (25, 1, 100, float, "max top 10 %"),
    "scanner.max_h1_change_pct": (200, 1, 10000, float, "max 1h change %"),
    "scanner.poll_s": (60, 15, 600, int, "poll seconds"),
    "scanner.min_pool_age_min": (10, 0, 240, float, "min pool age min"),
    "scanner.max_wait_min": (60, 5, 720, float, "max wait min"),
    "scanner.runner_h24_pct": (300, 10, 100000, float, "runner 24h %"),
    "scanner.min_holders_growth_pct": (0, -100, 1000, float, "min holders growth % (10m)"),
    "scanner.ws_silent_s": (120, 30, 1800, int, "websocket silent s"),
    "scanner.max_dex_rpm": (250, 10, 290, int, "DexScreener req/min"),
    "scanner.source": ("helius", None, None, str, "coin source helius|pumpportal"),
    "scanner.gecko_enabled": (True, None, None, bool, "GeckoTerminal new pools as 3rd source"),
    "scanner.gecko_poll_s": (60, 20, 3600, int, "GeckoTerminal new pools poll seconds"),
    # ---- auditor = Analyst's 8 layers (v2 merges audit + score into 1 judgement)
    "auditor.enabled": (True, None, None, bool, "take apart before buying"),
    "auditor.max_dev_pct": (5, 0, 100, float, "max dev %"),
    "auditor.max_top10_pct": (25, 1, 100, float, "max top 10 %"),
    "auditor.min_lp_locked_pct": (99, 0, 100, float, "min LP locked %"),
    "auditor.max_liq_drop_pct": (50, 1, 100, float, "max liquidity drop %"),
    "auditor.min_pool_age_min": (10, 0, 240, float, "min pool age min"),
    "auditor.max_bundled": (5, 1, 1000, int, "max bundled"),
    "auditor.max_insiders_pct": (15, 0, 100, float, "max insiders %"),
    "auditor.max_delegated_accounts": (10, 1, 100000, int, "max delegated accounts"),
    "auditor.retries": (3, 0, 10, int, "retries"),
    # ---- analyst score (v2: code only, no outside model)
    "analyst.mode": ("v2", None, None, str, "mode v2|jev|rules"),
    "analyst.min_score": (70, 0, 100, int, "min score"),
    "analyst.tech_gate": (False, None, None, bool, "kill under tech_min (8 TradingView-style checks)"),
    "analyst.tech_min": (70, 0, 100, int, "tech checks min score"),
    "analyst.alive_volume_h1": (25000, 100, 10_000_000, float, "alive volume 1h $"),
    "analyst.organic_unique_h1": (80, 1, 100000, float, "organic unique buyers 1h"),
    "analyst.organic_buys_h1": (150, 1, 100000, float, "organic buys 1h (txns)"),
    "analyst.bundled_penalty": (0.5, 0, 1, float, "penalty factor"),
    "analyst.bundled_from": (3, 1, 1000, int, "bundled penalty from wallets"),
    "analyst.fast_curve_min": (10, 0, 600, float, "fast curve min"),
    "analyst.max_fresh_pct": (50, 0, 100, float, "max fresh wallets %"),
    "analyst.fresh_top_n": (20, 1, 50, int, "fresh check top holders"),
    "analyst.fresh_sigs": (10, 1, 1000, int, "fresh = under N signatures"),
    "analyst.flush_sell_ratio": (1.5, 1, 10, float, "flush sell ratio"),
    "analyst.chase_h1_pct": (200, 1, 10000, float, "chase 1h %"),
    "analyst.timeout_s": (10, 2, 60, int, "timeout s"),
    "analyst.max_state_chars": (3000, 200, 10000, int, "max state chars"),
    # v1 Jev/rules knobs (only used when analyst.mode is jev|rules)
    "analyst.min_alive_6h": (0.70, 0, 1, float, "min alive 6h"),
    "analyst.min_organic": (0.65, 0, 1, float, "min organic"),
    "analyst.max_chase": (0.30, 0, 1, float, "max chase"),
    "analyst.rules.alive_volume_h1": (25000, 100, 10_000_000, float, "alive volume 1h $"),
    "analyst.rules.organic_buys_h1": (150, 1, 100000, float, "organic buys 1h"),
    "analyst.rules.bundled_penalty": (0.5, 0, 1, float, "bundled penalty"),
    "analyst.rules.bundled_from": (3, 1, 1000, int, "bundled penalty from wallets"),
    "analyst.rules.flush_drop_m5_pct": (5, 0.1, 100, float, "flush drop 5m %"),
    "analyst.rules.chase_h1_pct": (80, 1, 10000, float, "chase 1h %"),
    # ---- social (X). The process cannot read X itself: off unless social/{mint}.json shows up
    "social.enabled": (False, None, None, bool, "social on"),
    "social.weight": (0.5, 0, 4, float, "social weight"),
    "social.max_per_h": (20, 0, 200, int, "social max per hour"),
    "social.timeout_s": (120, 5, 600, int, "social timeout s"),
    "social.shill_cut": (0.5, 0, 1, float, "shill cut"),
    # ---- brain (sizing)
    "brain.risk_per_trade_pct": (3, 0.1, 20, float, "risk per trade %"),
    "brain.full_size_score": (80, 0, 100, int, "full size score"),
    "brain.below_full_pct": (50, 0, 100, float, "below full %"),
    "brain.max_pool_pct": (2, 0.01, 100, float, "max pool %"),
    "brain.min_ticket_usd": (2, 1, 100000, float, "min ticket $"),
    "brain.max_ticket_usd": (50, 2, 100000, float, "max ticket $"),
    "brain.max_trades_night": (30, 1, 500, int, "max trades a night"),
    "brain.timesfm_mode": ("log", None, None, str, "TimesFM forecast off|log|gate"),
    "brain.timesfm_url": ("http://127.0.0.1:8795", None, None, str, "TimesFM sidecar (localhost)"),
    "brain.timesfm_horizon_min": (15, 1, 64, int, "TimesFM horizon minutes"),
    "brain.timesfm_min_ret_pct": (-5, -100, 100, float, "gate: skip if median forecast under this %"),
    # ---- executor
    "executor.dip_pct": (15, 1, 90, float, "dip %"),
    "executor.nansen_min_sm": (0, 0, 1000, int, "min Nansen smart-money holders (0 = log only; needs NANSEN_API_KEY)"),
    "executor.dip_window_min": (10, 1, 120, float, "dip high window min"),
    "executor.dip_wait_min": (30, 1, 240, float, "dip wait min"),
    "executor.crash_pct": (35, 2, 99, float, "crash %"),
    "executor.dip_sell_ratio": (1.5, 1, 10, float, "dip sellers ratio"),
    "executor.tp_x": (2.0, 1.05, 100, float, "take profit x"),
    "executor.tp_sell_pct": (50, 1, 100, float, "take profit sell %"),
    "executor.trail_pct": (40, 1, 95, float, "trail %"),
    "executor.recheck_liq_drop_pct": (20, 1, 100, float, "recheck liquidity drop %"),
    "executor.recheck_price_up_pct": (15, 1, 1000, float, "recheck price up %"),
    "executor.quote_timeout_s": (10, 2, 60, int, "quote timeout s"),
    "executor.verify_timeout_s": (30, 5, 180, int, "verify timeout s"),
    "executor.confirm_window_min": (5, 1, 60, float, "confirm window min (manual LIVE taps)"),
    # v1 sizing (legacy, unused since Brain sizes)
    "executor.stack_pct": (12, 0.1, 100, float, "legacy stack %"),
    "executor.max_pool_pct": (2, 0.01, 100, float, "legacy max pool %"),
    "executor.min_ticket_usd": (2, 1, 100000, float, "legacy min ticket $"),
    "executor.below_min": ("skip", None, None, str, "legacy below min bump|skip"),
    # ---- risk
    "risk.poll_s": (5, 2, 120, int, "poll seconds"),
    "risk.stop_pct": (25, 0.5, 90, float, "stop %"),
    "risk.timeout_h": (3, 0.1, 72, float, "timeout h"),
    "risk.timeout_min_gain_pct": (5, 0, 1000, float, "timeout min gain %"),
    "risk.pulled_drop_pct": (80, 10, 100, float, "pulled liquidity drop % in 1 poll"),
    "risk.dev_dump_pct": (50, 1, 100, float, "dev dumping %"),
    "risk.night_loss_stop_pct": (30, 1, 100, float, "night loss stop %"),
    "risk.no_price_polls": (12, 1, 1000, int, "no price polls"),
    "risk.confirm_window_min": (2, 0.5, 60, float, "confirm window min (manual LIVE taps)"),
    "risk.trail_start_pct": (100, 1, 1000, float, "legacy trail start %"),
    "risk.trail_pct": (40, 0.5, 95, float, "trail % (mirror of executor.trail_pct)"),
    # ---- copy picks (copy-picks prompt STEPS 1-5). Read only; STEP 5 copy on desk stays off.
    "copy_picks.every": ("24h", None, None, str, "copy picks every off|24h|12h|6h"),
    "copy_picks.time": ("21:30", None, None, str, "copy picks time (before night start)"),
    "copy_picks.top_n": (5, 1, 20, int, "copy picks: keep top N"),
    "copy_picks.candidates": (40, 1, 150, int, "copy picks: 30d candidates that get a swaps read"),
    "copy_picks.min_trades": (20, 0, 10000, int, "copy picks: min trades"),
    "copy_picks.max_last_trade_h": (24, 1, 720, float, "copy picks: last trade within h"),
    "copy_picks.one_coin_pct": (60, 1, 100, float, "copy picks: 1 coin wonder over %"),
    "copy.enabled": (False, None, None, bool, "copy on desk (STEP 5), off"),
    "copy.max_traders": (2, 0, 10, int, "copy: max traders at a time"),
    "copy.poll_s": (20, 5, 600, int, "copy: read their swaps every s"),
    "copy.delay_s": (30, 0, 600, int, "copy: buy s after them"),
    "copy.stop_pct": (25, 1, 90, float, "copy: own stop %"),
    "copy.size_factor": (0.5, 0.05, 1, float, "copy: x normal Brain risk size"),
    # ---- desk
    "desk.mode": ("PAPER", None, None, str, "mode"),
    "desk.paper_start_stack": (30, 2, 10_000_000, float, "paper start cash $"),
    "desk.stack": (30, 0, 100_000_000, float, "LIVE stack $"),
    "desk.night_start": ("22:00", None, None, str, "night start"),
    "desk.lock_time": ("06:30", None, None, str, "lock time (sell all)"),
    "desk.report_time": ("08:00", None, None, str, "report time"),
    "desk.notifier": ("telegram", None, None, str, "notifier"),
    "desk.rpc_url": ("https://api.mainnet-beta.solana.com", None, None, str, "rpc url"),
    "desk.push_rejects": (False, None, None, bool, "push rejects"),
    "desk.fee_pct": (0.45, 0, 5, float, "fee % above $190"),
    "desk.fees_ref_discount": (0.0, 0, 1, float, "fees ref discount"),
    "desk.fomo_handle": ("", None, None, str, "FOMO handle"),
    "desk.ref_code": ("gorbindx", None, None, str, "FOMO referral code"),
    "desk.autoclick": ("off", None, None, str, "auto-click lane off|dryrun|on"),
    "desk.journal_url": ("http://127.0.0.1:3010", None, None, str, "LuxAlgo trade-journal (localhost), empty = csv only"),
    "desk.cdp_port": (9222, 1024, 65535, int, "Chrome debug port (127.0.0.1)"),
    "desk.fomo_sol_address": ("", None, None, str, "FOMO solana address (public, chain witness)"),
}
CHOICES = {"analyst.mode": ("v2", "jev", "rules"), "executor.below_min": ("bump", "skip"),
           "desk.autoclick": ("off", "dryrun", "on"), "brain.timesfm_mode": ("off", "log", "gate"), "scanner.source": ("helius", "pumpportal"),
           "desk.mode": ("PAPER", "LIVE"), "copy_picks.every": ("off", "24h", "12h", "6h"), "desk.notifier": ("telegram", "webpush")}
ALIASES = {
    "stop": "risk.stop_pct", "trail": "executor.trail_pct", "trail start": "risk.trail_start_pct",
    "timeout": "risk.timeout_h", "stack pct": "executor.stack_pct", "stack_pct": "executor.stack_pct",
    "min liquidity": "scanner.min_liquidity_usd", "liquidity": "scanner.min_liquidity_usd",
    "top10": "scanner.max_top10_pct", "top 10": "scanner.max_top10_pct", "min score": "analyst.min_score",
    "score": "analyst.min_score", "alive": "analyst.min_alive_6h", "organic": "analyst.min_organic",
    "chase": "analyst.max_chase", "dev": "auditor.max_dev_pct", "bundled": "auditor.max_bundled",
    "below min": "executor.below_min", "rpc": "desk.rpc_url", "rpc_url": "desk.rpc_url",
    "report time": "desk.report_time", "autoclick": "desk.autoclick", "night start": "desk.night_start", "lock time": "desk.lock_time",
    "risk": "brain.risk_per_trade_pct", "max ticket": "brain.max_ticket_usd", "max trades": "brain.max_trades_night", "dip": "executor.dip_pct", "tp": "executor.tp_x", "pool pct": "brain.max_pool_pct", "min ticket": "brain.min_ticket_usd",
    "ref": "desk.ref_code", "ref_code": "desk.ref_code", "referral": "desk.ref_code",
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
            if key in ("desk.report_time", "desk.night_start", "desk.lock_time", "copy_picks.time"):
                hh, mm = v.split(":"); assert 0 <= int(hh) < 24 and 0 <= int(mm) < 60
            if key == "desk.rpc_url":
                if "[REDACTED]" in v:
                    raise ValueError("rpc_url looks masked; paste the full https URL")
                if not v.startswith("https://"):
                    raise ValueError("rpc_url must start with https://")
            if key == "desk.autoclick" and v == "on" and self.db.kv_get("autoclick.test_ok") != "1":
                raise ValueError("autoclick on is locked until a verified $2 test trade that Christian approved (tools/desk_cli.py test-trade)")
            if key == "desk.fomo_sol_address" and v:
                import re
                if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", v):
                    raise ValueError("fomo_sol_address must be a Solana address")
            if key == "desk.ref_code":
                import re
                v = v.lstrip("@")
                if not re.fullmatch(r"[A-Za-z0-9_]{1,32}", v):
                    raise ValueError("ref_code must be 1-32 letters, numbers, or _")
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
        if key == "desk.ref_code":
            import links
            links.set_ref_code(v)
        return old, v

    # v2 ticket check: Brain's full size must reach FOMO's $2 minimum
    def ticket_check(self, stack=None):
        if stack is None:
            stack = self.stack_now()
        full = stack * self.get("brain.risk_per_trade_pct") / self.get("risk.stop_pct")
        half = full * self.get("brain.below_full_pct") / 100
        mt = self.get("brain.min_ticket_usd")
        if full < mt:
            return ("skip", f"every coin will be skipped: full size ${full:.2f} is under ${mt:.2f}. Raise the cash.")
        if half < mt:
            return ("half", f"score 80+ buys ${full:.2f}; under 80 sizes ${half:.2f} < ${mt:.2f} and is skipped")
        return None

    def stack_now(self):
        if self.get("desk.mode") == "PAPER":
            r = self.db.one("SELECT value FROM kv WHERE key='paper_cash'")
            return float(r["value"]) if r else float(self.get("desk.paper_start_stack"))
        return float(self.get("desk.stack"))
