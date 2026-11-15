#!/usr/bin/env bash
# Daemonize (or restart) the Cloudflare tunnel supervisor.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/logs/tunnel.log"
SUP="$ROOT/logs/tunnel-supervisor.pid"
CF="$ROOT/logs/cloudflared.pid"
mkdir -p "$ROOT/logs"

# Prefer the ngrok static/supervised entry when a token or config is present.
if [ -n "${NGROK_AUTHTOKEN:-}" ] || [ -s /home/box/secrets/fomo-desk/ngrok.yml ]; then
  echo "starting ngrok as the stable public entry"
  exec bash "$ROOT/tools/start_ngrok.sh"
fi

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

# Also stop a leftover test tunnel that might not have a pid file
if [ -f /tmp/cf-test2.pid ]; then
  kill_pidfile /tmp/cf-test2.pid
fi
pkill -f '/workspace/bin/cloudflared tunnel --url http://127.0.0.1:8787' 2>/dev/null || true
kill_pidfile "$SUP"
kill_pidfile "$CF"
sleep 1

printf '%s starting public tunnel supervisor\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
setsid nohup bash "$ROOT/tools/tunnel_supervisor.sh" >>"$LOG" 2>&1 < /dev/null &
echo $! > "$SUP"
# the supervisor rewrites this pid to its own (after setsid the $! is the child)
sleep 1
if [ -f "$SUP" ] && kill -0 "$(cat "$SUP")" 2>/dev/null; then
  echo "tunnel supervisor pid $(cat "$SUP")"
else
  echo "failed to start tunnel supervisor" >&2
  exit 1
fi
