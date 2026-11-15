# Grok Bot desk · v2.0 (PAPER)

One always-on asyncio process (`main.py`): Scanner → Auditor (8 layers) → Analyst (v2 score, code only) → Brain (size)
→ Executor (dip entry, take profit) → Risk (5s guard), the API/app on 127.0.0.1:8787, Telegram long polling, the
auto-click lane (`browser.py`, off by default), night window 22:00 → 06:30 (sell all at lock time), report at 08:00.

- Coin source: Helius `logsSubscribe` on the pump.fun migration account (HELIUS_RPC_URL in the secrets .env).
  PumpPortal websocket stays as fallback (403 to this box since 2026-11-14 21:57; retried every 10 min while Helius is down).
- Start / restart: `./run.sh` · Stop: `kill $(cat desk.pid)` · Health: `.venv/bin/python tools/desk_cli.py health [--fix]`
- Status lines for the 5 Grok Bot teammate chats: `status/{agent}.txt` (latest; idle heartbeat after 10 quiet min) + `.log`
- Tests: `.venv/bin/python -m pytest -q tests/`
- Reinstall packages: `./setup.sh`
- v1 backup: /workspace/desk_v1_backup

## Auto-click lane (v2 STEP 9) — ships OFF
- `desk.autoclick`: `off` (default) | `dryrun` (opens the coin, types the amount, reads the quote, screenshots, never
  presses the button) | `on` (refused by config until a verified $2 test trade Christian approved).
- Chrome: `tools/start_chrome.sh` (profile ./chrome, CDP on 127.0.0.1:9222 only). Christian logs in to FOMO there himself.
- Cursor rules and the Withdraw ban are code (`browser.guard_click`, `browser.guard_url`, `browser.withdraw` always raises).
- `tools/desk_cli.py lane-check` · `dry-run MINT [USD]` · `test-trade MINT --i-approve-real-money` (real money, only with his ok).
- VERIFY (`verify.py`): screen + FOMO API swaps + chain balance. The FOMO swaps JSON keys are unmapped until the first
  logged-in sample lands in logs/raw/fomo_swaps.json; until then every LIVE click ends "unverified" (no 2nd click).

Secrets: /home/box/secrets/fomo-desk/.env (600), never in this folder. Every FOMO URL comes from links.py (r=gorbindx).

## savipww's 5 repos (one per bot) — how each is folded in
| Bot | Repo | Here |
|---|---|---|
| Scanner | coingecko/skills | `sources.Gecko` (keyless GeckoTerminal API, ~25 req/min limiter). `scanner.gecko_loop`: new PumpSwap pools every 60 s as the 3rd coin source after Helius + PumpPortal (dedupe). Holders count fallback when RPC fails (both samples of a coin from the same source). |
| Analyst | atilaahmettaner/tradingview-mcp | Not usable for these coins: the MCP reads TradingView screener data for CEX / listed symbols; PumpSwap memecoins aren't TradingView symbols. `tech.py` computes 8 TradingView-style checks (RSI, EMA9/21, VWAP, Bollinger, volume, higher lows, green ratio, dump bar) on GeckoTerminal 1-min OHLCV → `tech` score in the verdict. Rule "8 checks, under 70 is dead" = the 8 Auditor layers + v2 score ≥ 70 (unchanged); `analyst.tech_gate` (off) also kills tech < `analyst.tech_min`. |
| Brain | google-research/timesfm | TimesFM 2.5 200M (PyTorch CPU) sidecar `sidecars/timesfm_server.py` on 127.0.0.1:8795 (own venv /workspace/ext/tfm-venv; ~6 s load, 0.1–0.35 s per forecast, ~2.2 GB RAM). `brain.timesfm_mode`: off / **log** (default, sizing stays the author's score rule) / gate (skip if 15-min median forecast < `brain.timesfm_min_ret_pct`). Weights licence on Hugging Face: apache-2.0. |
| Executor | nansen-ai/nansen-cli | `smart_money.py`: read-only `tgm/holders` smart-money lookup (same call as `nansen research token holders --smart-money`), only when NANSEN_API_KEY is in the secrets .env (absent now → nothing runs). `executor.nansen_min_sm` 0 = log only. `nansen trade` / `wallet` are never used; execution stays FOMO. |
| Risk | LuxAlgo/trade-journal | Self-hosted on 127.0.0.1:3010 (`tools/start_journal.sh`, data in data/journal). `journal.py` logs every PAPER/LIVE fill to data/journal/{MODE}.csv (TradingView paper format) and commits it to account "FOMO desk {MODE}" (dedup). The −25 % stop and all exits stay in agents/risk.py. Open it: `ssh -L 3010:127.0.0.1:3010` or the box browser. |

`./run.sh` starts both sidecars if they're down; `tools/desk_cli.py health` shows them.
