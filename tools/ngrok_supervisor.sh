#!/usr/bin/env bash
# Keep an ngrok tunnel up for the desk app at 127.0.0.1:8787.
# Quick/auto ngrok-free.app URLs change on every process restart; when
# that happens we rewrite the private link file and Telegram a button.
# If NGROK_DOMAIN (or logs/ngrok.domain reserved) is set to a dashboard
# claimed static domain, we start with --url so the hostname stays put.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="${NGROK_BIN:-/workspace/bin/ngrok}"
CFG="/home/box/secrets/fomo-desk/ngrok.yml"
LOG="$ROOT/logs/ngrok-supervisor.log"
AGENTLOG="$ROOT/logs/ngrok.log"
URLFILE="$ROOT/logs/ngrok.url"
DOMAINFILE="$ROOT/logs/ngrok.domain"
PROVIDER="$ROOT/logs/stable_provider"
PY="$ROOT/.venv/bin/python"

mkdir -p "$ROOT/logs"
echo $$ > "$ROOT/logs/ngrok-supervisor.pid"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; }

load_domain() {
  # Prefer an explicit reserved domain; never invent one from a previous
  # ephemeral assignment (those cannot be reclaimed with --url on the free plan).
  local d="${NGROK_DOMAIN:-}"
  if [ -z "$d" ] && [ -f /home/box/secrets/fomo-desk/.env ]; then
    d=$(sed -n 's/^NGROK_DOMAIN=//p' /home/box/secrets/fomo-desk/.env | tail -n1 | tr -d '"' | tr -d "'" | tr -d '[:space:]')
  fi
  if [ -n "${d:-}" ]; then
    d="${d#https://}"
    d="${d%%/*}"
    echo "$d"
    return
  fi
  if [ -f "$DOMAINFILE" ] && [ "$(cat "$DOMAINFILE" 2>/dev/null)" != "" ]; then
    # Only reuse a saved domain if it was marked reserved
    if [ -f "$ROOT/logs/ngrok.domain.reserved" ]; then
      cat "$DOMAINFILE"
      return
    fi
  fi
}

announce_if_new() {
  local base="$1"
  "$PY" "$ROOT/tools/write_public_link.py" "$base"
  local rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "$base" > "$URLFILE"
    echo ngrok > "$PROVIDER"
    log "new public base $base (private link written, notifying owner)"
    "$PY" "$ROOT/tools/announce_public_link.py" >>"$LOG" 2>&1 || log "telegram announce failed"
  elif [ "$rc" -eq 2 ]; then
    echo "$base" > "$URLFILE"
    echo ngrok > "$PROVIDER"
    log "public base unchanged $base"
  else
    log "failed to write public link for $base"
  fi
}

extract_url() {
  # Prefer the local inspector API; fall back to the agent log.
  local url=""
  url=$("$PY" - <<'PY'
import json, urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2) as r:
        data = json.loads(r.read().decode())
    for t in data.get("tunnels") or []:
        u = (t.get("public_url") or "")
        if u.startswith("https://"):
            print(u.rstrip("/"))
            break
except Exception:
    pass
PY
  )
  if [ -n "$url" ]; then
    echo "$url"
    return
  fi
  grep -oE 'https://[a-z0-9-]+\.ngrok(-free)?\.(app|dev|io)' "$AGENTLOG" 2>/dev/null | tail -n 1
}

probe() {
  local base="$1"
  "$PY" "$ROOT/tools/probe_public.py" "$base" >>"$LOG" 2>&1
}

log "supervisor start pid=$$"

if ! "$PY" "$ROOT/tools/ensure_ngrok_config.py" >>"$LOG" 2>&1; then
  log "cannot write ngrok config; sleeping then retrying"
fi

while true; do
  if [ ! -s "$CFG" ]; then
    "$PY" "$ROOT/tools/ensure_ngrok_config.py" >>"$LOG" 2>&1 || true
    if [ ! -s "$CFG" ]; then
      log "missing $CFG, sleeping"
      sleep 5
      continue
    fi
  fi
  if ! curl -sf --max-time 2 -o /dev/null http://127.0.0.1:8787/; then
    log "warning: origin 127.0.0.1:8787 is not responding; still starting the tunnel"
  fi
  # Drop a stale agent
  if [ -f "$ROOT/logs/ngrok.pid" ]; then
    old=$(cat "$ROOT/logs/ngrok.pid" 2>/dev/null || true)
    if [ -n "${old:-}" ] && kill -0 "$old" 2>/dev/null; then
      kill "$old" 2>/dev/null || true
      sleep 1
      kill -0 "$old" 2>/dev/null && kill -9 "$old" 2>/dev/null || true
    fi
    rm -f "$ROOT/logs/ngrok.pid"
  fi
  # free 4040 if a leftover holds it
  if ss -ltn 2>/dev/null | grep -q '127.0.0.1:4040'; then
    pkill -f '/workspace/bin/ngrok http' 2>/dev/null || true
    sleep 1
  fi

  : > "$AGENTLOG"
  domain=$(load_domain || true)
  url_args=()
  if [ -n "${domain:-}" ]; then
    url_args=(--url "https://${domain}")
    log "starting ngrok with reserved domain $domain"
  else
    log "starting ngrok (ephemeral free URL; will announce if it changes)"
  fi
  "$BIN" http 127.0.0.1:8787 \
    --config "$CFG" \
    "${url_args[@]}" \
    --log "$AGENTLOG" \
    --log-format json \
    --log-level info \
    >>"$LOG" 2>&1 &
  cpid=$!
  echo "$cpid" > "$ROOT/logs/ngrok.pid"
  url=""
  for i in $(seq 1 45); do
    if ! kill -0 "$cpid" 2>/dev/null; then
      log "ngrok exited during startup"
      break
    fi
    url=$(extract_url)
    if [ -n "$url" ]; then
      break
    fi
    sleep 1
  done
  if [ -n "$url" ]; then
    log "tunnel url $url pid=$cpid"
    announce_if_new "$url"
    fail=0
    while kill -0 "$cpid" 2>/dev/null; do
      if ! probe "$url"; then
        fail=$((fail + 1))
        log "health probe fail $fail/3 for $url"
        if [ "$fail" -ge 3 ]; then
          log "health probe failed 3 times; restarting ngrok"
          kill "$cpid" 2>/dev/null || true
          sleep 1
          kill -0 "$cpid" 2>/dev/null && kill -9 "$cpid" 2>/dev/null || true
          break
        fi
      else
        fail=0
      fi
      for j in $(seq 1 15); do
        kill -0 "$cpid" 2>/dev/null || break
        sleep 1
      done
    done
  else
    log "no tunnel url yet for pid=$cpid"
    kill "$cpid" 2>/dev/null || true
    sleep 1
    kill -0 "$cpid" 2>/dev/null && kill -9 "$cpid" 2>/dev/null || true
  fi
  wait "$cpid" 2>/dev/null || true
  rc=$?
  log "ngrok pid=$cpid exited rc=$rc; restarting in 3s"
  sleep 3
done
