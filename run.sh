#!/usr/bin/env bash
# Start (or restart) the desk: ONE always-on asyncio process. Logs in logs/.
cd "$(dirname "$0")"
# self-heal: a box restore on 2026-11-14 23:16 dropped .venv (and node_modules); rebuild it if missing
if [ ! -x .venv/bin/python ]; then
  rm -rf .venv; python3 -m venv venv && ./venv/bin/pip install -q -r requirements.txt && ln -sfn venv .venv
fi
# Plan A: live token-protected API + web push (does not change PAPER/LIVE trading mode)
export DESK_PLAN="${DESK_PLAN:-A}"
if [ -f desk.pid ] && kill -0 "$(cat desk.pid)" 2>/dev/null; then
  kill "$(cat desk.pid)"; sleep 2
  kill -0 "$(cat desk.pid)" 2>/dev/null && kill -9 "$(cat desk.pid)"
fi
# savipww's repos as localhost sidecars (idempotent): LuxAlgo trade-journal :3010, TimesFM :8795
tools/start_journal.sh >/dev/null 2>&1 || true
tools/start_timesfm.sh >/dev/null 2>&1 || true
setsid nohup .venv/bin/python main.py >> logs/process.log 2>&1 < /dev/null &
sleep 3
echo "desk pid $(cat desk.pid)"
