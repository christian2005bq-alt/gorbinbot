#!/usr/bin/env bash
# Keep a Cloudflare quick tunnel up for the desk app at 127.0.0.1:8787.
# The box DNS resolver returns 198.18.0.1 for every name, and that address
# cannot finish the Cloudflare *edge* handshake (this is why plan A failed
# earlier). Normal HTTPS still works. We bind-mount a hosts file with the
# real region*.v2.argotunnel.com IPs (from DNS-over-HTTPS) and connect with
# HTTP/2 on port 7844, which does reach the real edge.
# Quick-tunnel URLs change on every process restart; when that happens we
# rewrite the private link file and Telegram it to the owner.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="${CLOUDFLARED_BIN:-/workspace/bin/cloudflared}"
LOG="$ROOT/logs/tunnel.log"
URLFILE="$ROOT/logs/tunnel.url"
HOSTS="/tmp/fomo-cfhosts"
PY="$ROOT/.venv/bin/python"

mkdir -p "$ROOT/logs"
echo $$ > "$ROOT/logs/tunnel-supervisor.pid"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; }

refresh_hosts() {
  "$PY" - <<'PY'
import json, urllib.request
from pathlib import Path

def doh(name):
    req = urllib.request.Request(
        f"https://cloudflare-dns.com/dns-query?name={name}&type=A",
        headers={"accept": "application/dns-json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.load(r)
    return [a["data"] for a in data.get("Answer") or [] if a.get("type") == 1]

fallback = {
    "region1.v2.argotunnel.com": ["198.41.192.37", "198.41.192.7", "198.41.192.67"],
    "region2.v2.argotunnel.com": ["198.41.200.13", "198.41.200.33", "198.41.200.63"],
}
lines = Path("/etc/hosts").read_text().rstrip() + "\n\n# real Cloudflare tunnel edge IPs\n"
assigned = []
for host, fb in fallback.items():
    try:
        ips = doh(host) or fb
    except Exception:
        ips = fb
    if ips:
        lines += f"{ips[0]} {host}\n"
        assigned.append(f"{host}={ips[0]}")
Path("/tmp/fomo-cfhosts").write_text(lines)
print("hosts", " ".join(assigned))
PY
}

extract_url() {
  # Last trycloudflare URL in the log since this child started (byte offset $1)
  local offset="${1:-0}"
  tail -c +"$((offset + 1))" "$LOG" 2>/dev/null \
    | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' \
    | tail -n 1
}

announce_if_new() {
  local base="$1"
  echo "$base" > "$URLFILE"
  # When ngrok is the stable public entry, keep its private link and do not
  # Telegram a changing trycloudflare URL.
  if [ -f "$ROOT/logs/stable_provider" ] && [ "$(cat "$ROOT/logs/stable_provider" 2>/dev/null | tr -d "[:space:]")" = "ngrok" ]; then
    log "cloudflared base $base (not announced; ngrok is the stable entry)"
    return
  fi
  "$PY" "$ROOT/tools/write_public_link.py" "$base"
  local rc=$?
  if [ "$rc" -eq 0 ]; then
    log "new public base $base (private link written, notifying owner)"
    "$PY" "$ROOT/tools/announce_public_link.py" >>"$LOG" 2>&1 || log "telegram announce failed"
  elif [ "$rc" -eq 2 ]; then
    log "public base unchanged $base"
  else
    log "failed to write public link for $base"
  fi
}

edge_dead() {
  # True if this child has logged an edge "Tunnel not found" after starting.
  local offset="${1:-0}"
  tail -c +"$((offset + 1))" "$LOG" 2>/dev/null | grep -q "Tunnel not found"
}

probe() {
  local base="$1"
  "$PY" "$ROOT/tools/probe_public.py" "$base" >>"$LOG" 2>&1
}

log "supervisor start pid=$$"

while true; do
  refresh_hosts >>"$LOG" 2>&1 || log "hosts refresh failed, reusing previous file"
  if [ ! -s "$HOSTS" ]; then
    log "missing $HOSTS, sleeping"
    sleep 5
    continue
  fi
  if ! curl -sf --max-time 2 -o /dev/null http://127.0.0.1:8787/; then
    log "warning: origin 127.0.0.1:8787 is not responding; still starting the tunnel"
  fi
  offset=$(wc -c < "$LOG" | tr -d ' ')
  log "starting cloudflared"
  unshare --user --map-root-user --mount bash -c "
    mount --bind '$HOSTS' /etc/hosts
    exec '$BIN' tunnel --url http://127.0.0.1:8787 --protocol http2 --no-autoupdate --edge-ip-version 4 --metrics 127.0.0.1:20241
  " >>"$LOG" 2>&1 &
  cpid=$!
  echo "$cpid" > "$ROOT/logs/cloudflared.pid"
  url=""
  for i in $(seq 1 45); do
    if ! kill -0 "$cpid" 2>/dev/null; then
      log "cloudflared exited during startup"
      break
    fi
    url=$(extract_url "$offset")
    if [ -n "$url" ]; then
      # wait until the edge connection is registered when possible, but don't
      # block the announce if we only have the URL
      if tail -c +"$((offset + 1))" "$LOG" | grep -q 'Registered tunnel connection'; then
        break
      fi
    fi
    sleep 1
  done
  if [ -n "$url" ]; then
    log "tunnel url $url pid=$cpid"
    announce_if_new "$url"
    fail=0
    while kill -0 "$cpid" 2>/dev/null; do
      if edge_dead "$offset"; then
        log "edge reported Tunnel not found; restarting cloudflared (process stays up otherwise)"
        kill "$cpid" 2>/dev/null || true
        sleep 1
        kill -0 "$cpid" 2>/dev/null && kill -9 "$cpid" 2>/dev/null || true
        break
      fi
      if ! probe "$url"; then
        fail=$((fail + 1))
        log "health probe fail $fail/3 for $url"
        if [ "$fail" -ge 3 ]; then
          log "health probe failed 3 times; restarting cloudflared"
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
  fi
  wait "$cpid" 2>/dev/null || true
  rc=$?
  log "cloudflared pid=$cpid exited rc=$rc; restarting in 3s"
  sleep 3
done
