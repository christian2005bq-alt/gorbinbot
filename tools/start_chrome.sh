#!/usr/bin/env bash
# v2 STEP 2A: ONE dedicated Chrome for the click lane, on the box display, profile /workspace/desk/chrome,
# remote debugging on 127.0.0.1 ONLY (never exposed). Christian logs in to FOMO here himself (Take control).
# Grok Bot never types a password or a code.
cd "$(dirname "$0")/.."
PORT="${CDP_PORT:-9222}"
if curl -s -m 2 "http://127.0.0.1:${PORT}/json/version" >/dev/null; then echo "Chrome already on 127.0.0.1:${PORT}"; exit 0; fi
mkdir -p chrome logs
DISPLAY="${DISPLAY:-:7}" setsid nohup google-chrome \
  --user-data-dir="$PWD/chrome" --remote-debugging-address=127.0.0.1 --remote-debugging-port="$PORT" \
  --no-first-run --no-default-browser-check --start-maximized --window-size=1600,1000 \
  "https://fomo.family/r/gorbindx" >> logs/chrome.log 2>&1 < /dev/null &
sleep 3
curl -s -m 3 "http://127.0.0.1:${PORT}/json/version" >/dev/null && echo "Chrome up on 127.0.0.1:${PORT} (profile ./chrome)" || echo "Chrome did not start, see logs/chrome.log"
