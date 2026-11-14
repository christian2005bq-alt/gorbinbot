"""Starts everything in ONE asyncio event loop: 5 agents + API + Telegram long polling. Writes heartbeats."""
import asyncio, datetime as dt, os, signal, sys
from pathlib import Path
import uvicorn
from common import ROOT, now, get_logger, quiet_libs, SECRETS
from desk import Desk
from agents.scanner import Scanner
from agents.auditor import Auditor
from agents.analyst import Analyst
from agents.executor import Executor
from agents.risk import Risk
from telegram import Telegram
from notifier import Notifier
import api, report

log = get_logger("main")
PORT = int(os.environ.get("DESK_PORT", "8787"))


async def balance_loop(d):
    while True:
        d.heartbeat("main")
        d.db.exec("INSERT INTO balance(ts,value) VALUES(?,?)", (now(), d.balance()))
        d.bus.emit("balance", {"value": d.balance(), "ts": now()})
        await asyncio.sleep(60)


async def night_loop(d):
    """At settings.report_time: close the night, write the morning report file, clear skips, start a new night."""
    while True:
        try:
            hh, mm = map(int, d.s("desk.report_time").split(":"))
            n = d.night()
            today_cut = dt.datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0).timestamp()
            if n and n["started_at"] < today_cut <= now():
                path = report.build(d, n)
                d.end_night()
                d.db.exec("DELETE FROM skips")
                d.db.kv_set("last_report_file", str(path))
                for a in ("scanner", "auditor", "analyst", "executor"):
                    ag = d.agents.get(a)
                    for attr in ("sent", "decided", "rejected", "asked", "pushed"):
                        if ag and hasattr(ag, attr):
                            getattr(ag, attr).clear()
                await start_night(d)
        except Exception as e:
            log.exception("night loop %s", e)
        await asyncio.sleep(30)


async def start_night(d):
    d.start_night()
    tc = d.settings.ticket_check()
    if tc and d.notifier:
        await d.notifier.push(("PAPER · " if d.mode() == "PAPER" else "") + tc[1], None, kind="ticket", buttons=False)
    log.info("night started, ticket check: %s", tc)


async def main():
    quiet_libs()
    Path(ROOT / "desk.pid").write_text(str(os.getpid()))
    d = Desk()
    if not d.s("desk.fomo_handle"):
        d.settings.set("desk.fomo_handle", "gorbindx", who="setup")
    if SECRETS.get("TYPESAFE_API_KEY") and d.db.one("SELECT 1 FROM settings WHERE key='analyst.mode'") is None:
        d.settings.set("analyst.mode", "jev", who="setup")
    tg = Telegram(d) if SECRETS.get("TG_TOKEN") else None
    d.notifier = Notifier(d, tg)
    d.agents = {"scanner": Scanner(d), "auditor": Auditor(d), "analyst": Analyst(d), "executor": Executor(d), "risk": Risk(d)}
    d.telegram = tg
    if not d.night():
        await start_night(d)
    for p in d.open_positions():
        d.bus.risk.put_nowait(p["id"])
    app = api.make_app(d)
    cfg = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning", access_log=False, lifespan="off")
    server = uvicorn.Server(cfg)
    tasks = [d.agents[a].run() for a in d.agents] + [server.serve(), balance_loop(d), night_loop(d),
             api.price_writer(d, app), api.planb_writer(d, ROOT / "out" / "site")]
    if tg:
        tasks.append(tg.poll())
    log.info("desk up: mode=%s port=%s agents=%s", d.mode(), PORT, list(d.agents))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
