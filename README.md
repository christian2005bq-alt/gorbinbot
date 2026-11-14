# Grok Bot desk (PAPER)

One always-on asyncio process (`main.py`): Scanner, Auditor, Analyst, Executor, Risk, the API/app on 127.0.0.1:8787,
Telegram long polling (owner lock), plan B JSON writer (out/site/d/<DATA_PATH>/ every 15s), night rollover at report_time.

- Public demo: https://christian2005bq-alt.github.io/gorbinbot/ . GitHub Pages builds a static, read-only PAPER demo
  from a fresh synthetic database. It contains no live account data or credentials and does not run the bot.
  The free static demo is not an always-on live service. Build it locally with `python tools/build_demo.py _site`.
- Start / restart: `/workspace/desk/run.sh`  (kills the old pid from desk.pid, starts `setsid nohup`, logs to logs/process.log)
- Stop: `kill $(cat /workspace/desk/desk.pid)`
- Health: `.venv/bin/python tools/desk_cli.py health [--fix]`
- Logs: logs/{scanner,auditor,analyst,executor,risk,telegram,notifier,api,main}.log (rotated daily), raw samples logs/raw/
- Agent one-line status for the Grok Bot status chats: status/{agent}.txt (latest) + status/{agent}.log (append)
- Tests: `.venv/bin/python -m pytest -q tests/` · live: `tests/test_notify.py`, `tests/test_secrets.py`, `tests/test_replay.py --hours 2`
- Secrets: /home/box/secrets/fomo-desk/.env (600). Never in this folder.
- Every FOMO URL comes from links.py (r=savipww).
