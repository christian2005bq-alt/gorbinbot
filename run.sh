#!/usr/bin/env bash
# Start (or restart) the desk: ONE always-on asyncio process. Logs in logs/.
cd "$(dirname "$0")"
if [ -f desk.pid ] && kill -0 "$(cat desk.pid)" 2>/dev/null; then
  kill "$(cat desk.pid)"; sleep 2
  kill -0 "$(cat desk.pid)" 2>/dev/null && kill -9 "$(cat desk.pid)"
fi
setsid nohup .venv/bin/python main.py >> logs/process.log 2>&1 < /dev/null &
sleep 3
echo "desk pid $(cat desk.pid)"
