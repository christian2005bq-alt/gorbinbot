"""SQLite schema (STEP 4) + helpers. WAL mode."""
import sqlite3, threading, os
from common import ROOT

SCHEMA = """
CREATE TABLE IF NOT EXISTS coins (mint TEXT PRIMARY KEY, name TEXT, symbol TEXT, pool TEXT, migrated_at REAL,
  creator TEXT, creator_balance_at_migration REAL, holders INTEGER, signature TEXT, first_seen REAL, h24_change REAL);
CREATE TABLE IF NOT EXISTS scans (id INTEGER PRIMARY KEY, mint TEXT, ts REAL, liquidity_usd REAL, top10_pct REAL,
  h1_change_pct REAL, age_min REAL, verdict TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS audits (id INTEGER PRIMARY KEY, mint TEXT, ts REAL, layer INTEGER, name TEXT, value_text TEXT,
  pass INTEGER, source TEXT, run_id TEXT);
CREATE TABLE IF NOT EXISTS verdicts (id INTEGER PRIMARY KEY, mint TEXT, ts REAL, alive_6h REAL, organic REAL, flush REAL,
  chase REAL, score INTEGER, pass INTEGER, reason TEXT, input_tokens INTEGER, model TEXT);
CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY, mint TEXT, ts REAL, price REAL, size_usd REAL, stack_pct REAL,
  link TEXT, mode TEXT, status TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS positions (id INTEGER PRIMARY KEY, mint TEXT, opened_at REAL, entry_price REAL, size_usd REAL,
  peak_price REAL, stop_price REAL, trail_active INTEGER DEFAULT 0, closed_at REAL, exit_price REAL, exit_reason TEXT,
  pnl_usd REAL, fees_usd REAL, mode TEXT, stop_pct REAL, status TEXT DEFAULT 'open', signal_id INTEGER, exit_pushed_at REAL,
  no_price_polls INTEGER DEFAULT 0, last_price REAL);
CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY, ts REAL, kind TEXT, mint TEXT, agent TEXT, title TEXT,
  subtitle TEXT, value TEXT);
CREATE TABLE IF NOT EXISTS prices (mint TEXT, ts REAL, price REAL, volume_m5 REAL, liquidity_usd REAL, market_cap REAL, volume_h24 REAL);
CREATE INDEX IF NOT EXISTS prices_mint_ts ON prices(mint, ts);
CREATE TABLE IF NOT EXISTS balance (ts REAL, value REAL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS change_log (ts REAL, key TEXT, old TEXT, new TEXT, who TEXT);
CREATE TABLE IF NOT EXISTS skips (mint TEXT PRIMARY KEY, until REAL);
CREATE TABLE IF NOT EXISTS heartbeats (agent TEXT PRIMARY KEY, ts REAL);
CREATE TABLE IF NOT EXISTS push_subs (endpoint TEXT PRIMARY KEY, p256dh TEXT, auth TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS nights (id INTEGER PRIMARY KEY, started_at REAL, ended_at REAL, mode TEXT, start_balance REAL, end_balance REAL);
CREATE TABLE IF NOT EXISTS events (ts REAL, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS pushes (id INTEGER PRIMARY KEY, ts REAL, mint TEXT, kind TEXT, text TEXT, link TEXT, channel TEXT, ok INTEGER, read INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY, ts REAL, agent TEXT, mint TEXT, verdict TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS jev_calls (ts REAL, mint TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER);
"""


class DB:
    def __init__(self, path=None):
        self.path = str(path or os.environ.get("DESK_DB", ROOT / "desk.db"))
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(SCHEMA)

    def exec(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).lastrowid

    def one(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchone()

    def all(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def kv_get(self, key, default=None):
        r = self.one("SELECT value FROM kv WHERE key=?", (key,))
        return r["value"] if r else default

    def kv_set(self, key, value):
        self.exec("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, None if value is None else str(value)))

    def coin(self, mint):
        r = self.one("SELECT * FROM coins WHERE mint=?", (mint,))
        return dict(r) if r else None

    def find_coins(self, q):
        q = q.strip()
        exact = self.all("SELECT * FROM coins WHERE mint=?", (q,))
        if exact:
            return exact
        return self.all("SELECT * FROM coins WHERE lower(symbol)=lower(?) OR lower(name)=lower(?) OR lower(symbol)=lower(?)",
                        (q, q, q.lstrip("$")))
