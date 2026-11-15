#!/usr/bin/env bash
# Daemonize (or restart) the ngrok supervisor for the desk app.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/logs/ngrok-supervisor.log"
SUP="$ROOT/logs/ngrok-supervisor.pid"
NG="$ROOT/logs/ngrok.pid"
mkdir -p "$ROOT/logs"

kill_pidfile() {
  local f="$1"
  if [ -f "$f" ]; then
    local p
    p=$(cat "$f" 2>/dev/null || true)
    if [ -n "${p:-}" ] && kill -0 "$p" 2>/dev/null; then
      kill "$p" 2>/dev/null || true
      sleep 1
      kill -0 "$p" 2>/dev/null && kill -9 "$p" 2>/dev/null || true
    fi
    rm -f "$f"
  fi
}

# Stop leftover test / previous agent and supervisor
kill_pidfile /tmp/ngrok-test.pid
pkill -f '/workspace/bin/ngrok http' 2>/dev/null || true
# Stop the cloudflared quick tunnel if it is still running. Its URLs expire
# and the supervisor would otherwise keep a dead edge connection around.
kill_pidfile "$ROOT/logs/tunnel-supervisor.pid"
kill_pidfile "$ROOT/logs/cloudflared.pid"
pkill -f '/workspace/bin/cloudflared tunnel --url http://127.0.0.1:8787' 2>/dev/null || true
# If the supervisor is already this script's child from a previous run
if [ -f "$SUP" ]; then
  kill_pidfile "$SUP"
fi
kill_pidfile "$NG"
sleep 1

if ! "$ROOT/.venv/bin/python" "$ROOT/tools/ensure_ngrok_config.py"; then
  echo "ngrok is not ready: set NGROK_AUTHTOKEN in the environment or /home/box/secrets/fomo-desk/.env" >&2
  exit 1
fi

printf '%s starting ngrok supervisor\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
# Inherit NGROK_AUTHTOKEN / NGROK_DOMAIN from this environment; never
# put the token on the command line (it would show up in ps).
setsid nohup bash "$ROOT/tools/ngrok_supervisor.sh" >>"$LOG" 2>&1 < /dev/null &
echo $! > "$SUP"
sleep 1
if [ -f "$SUP" ] && kill -0 "$(cat "$SUP")" 2>/dev/null; then
  echo "ngrok supervisor pid $(cat "$SUP")"
else
  echo "failed to start ngrok supervisor" >&2
  exit 1
fi
