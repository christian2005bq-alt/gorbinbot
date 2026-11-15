#!/usr/bin/env bash
# savipww's Risk repo: LuxAlgo/trade-journal, self-hosted on 127.0.0.1:3010 ONLY (never tunneled).
# Data: /workspace/desk/data/journal (SQLite). The desk posts every PAPER/LIVE fill to it (journal.py).
cd /workspace/ext/trade-journal || exit 1
if curl -s -m 3 -o /dev/null http://127.0.0.1:3010/api/accounts; then echo "journal already up"; exit 0; fi
export JOURNAL_DATA_DIR=/workspace/desk/data/journal NEXT_TELEMETRY_DISABLED=1 PORT=3010 HOSTNAME=127.0.0.1
cd apps/web && setsid nohup npx next start -H 127.0.0.1 -p 3010 >> /workspace/desk/logs/journal_app.log 2>&1 < /dev/null &
echo $! > /workspace/desk/data/journal/journal.pid
