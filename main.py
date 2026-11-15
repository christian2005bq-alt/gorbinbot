"""Starts everything in ONE asyncio event loop: 5 agents + API + Telegram long polling. Writes heartbeats."""
import asyncio, datetime as dt, os, signal, sys
from pathlib import Path
import uvicorn
from common import ROOT, now, get_logger, quiet_libs, SECRETS
from desk import Desk
from agents.scanner import Scanner
from agents.auditor import Auditor
from agents.analyst import Analyst
from agents.brain import Brain
from agents.executor import Executor
from agents.risk import Risk
from browser import Lane
from telegram import Telegram
from notifier import Notifier
from watchdog import Watchdog
import api, report, fomo_account

log = get_logger("main")
PORT = int(os.environ.get("DESK_PORT", "8787"))


async def balance_loop(d):
    n = 0
    while True:
        d.heartbeat("main")
        d.db.exec("INSERT INTO balance(ts,value) VALUES(?,?)", (now(), d.balance()))
        d.bus.emit("balance", {"value": d.balance(), "ts": now()})
        n += 1
        if n % 10 == 0:
            d.db.checkpoint()
        await asyncio.sleep(60)


def window_start_ts(d, t=None):
    """The most recent night_start (22:00) at or before t."""
    t = t or now()
    hh, mm = map(int, d.s("desk.night_start").split(":"))
    x = dt.datetime.fromtimestamp(t)
    ws = x.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if ws > x:
        ws -= dt.timedelta(days=1)
    return ws.timestamp()


def clear_night_sets(d):
    d.db.exec("DELETE FROM skips")
    for a in ("scanner", "auditor", "analyst", "executor"):
        ag = d.agents.get(a)
        for attr in ("sent", "decided", "rejected", "asked", "pushed"):
            if ag and hasattr(ag, attr):
                getattr(ag, attr).clear()


async def lock_night(d, n):
    """v2 lock_time: no new buys, sell every open position 100%, push "Night over · $N", end the night."""
    d.db.kv_set("night.locked", "1")
    rk = d.agents.get("risk")
    if rk:
        await rk.sell_all("lock time")
    ex = d.agents.get("executor")
    if ex:
        for sid in list(getattr(ex, "waiting", {})):
            ex.drop(sid, "night over")
    bal = d.balance()
    d.end_night()
    if d.notifier:
        pre = "PAPER · " if d.mode() == "PAPER" else ""
        await d.notifier.push(f"{pre}Night over · ${bal:,.2f}", None, kind="night", buttons=False)
    log.info("night %s locked at %s, balance %.2f", n and n.get("id"), dt.datetime.now().strftime("%H:%M"), bal)


async def night_loop(d):
    """v2 window: night_start 22:00 starts a night, lock_time 06:30 sells all and ends it, report_time builds the report."""
    while True:
        try:
            n = d.night()
            if d.in_night():
                ws = window_start_ts(d)
                if not n or n["started_at"] < ws - 60:
                    if n:
                        d.end_night()
                    clear_night_sets(d)
                    await start_night(d)
            elif n:
                await lock_night(d, n)
            hh, mm = map(int, d.s("desk.report_time").split(":"))
            cut = dt.datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0).timestamp()
            last = d.db.one("SELECT * FROM nights WHERE ended_at IS NOT NULL ORDER BY id DESC LIMIT 1")
            if last and now() >= cut and last["ended_at"] <= cut and d.db.kv_get("last_report_night") != str(last["id"]):
                path = report.build(d, dict(last))
                d.db.kv_set("last_report_file", str(path))
                d.db.kv_set("last_report_night", str(last["id"]))
        except Exception as e:
            log.exception("night loop %s", e)
        await asyncio.sleep(30)


async def status_loop(d):
    """Heartbeat lines for the 5 Grok Bot teammate chats: every agent's status/{agent}.txt is refreshed when it
    has been quiet for 10 min, so each chat can show the agent is alive and what it is waiting for."""
    while True:
        try:
            ns = d.night_start_ts()
            cnt = lambda q, a=(): d.db.one(q, a)["c"]
            sc = d.agents.get("scanner"); ex = d.agents.get("executor")
            src = "Helius" if sc and sc.helius_healthy() else "no source (Helius down, PumpPortal 403)"
            win = "night window open" if d.in_night() else f"day: no buys until {d.s('desk.night_start')}"
            lines = {
                "scanner": f"alive · source {src} · {len(sc.room) if sc else 0} coins in the waiting room · "
                           f"{cnt('SELECT COUNT(*) c FROM scans WHERE ts>=?', (ns,))} decided tonight "
                           f"({cnt('SELECT COUNT(*) c FROM scans WHERE ts>=? AND verdict=\'pass\'', (ns,))} passed)",
                "auditor": f"alive · {cnt('SELECT COUNT(DISTINCT mint) c FROM audits WHERE ts>=?', (ns,))} coins taken apart tonight · "
                           f"{cnt('SELECT COUNT(*) c FROM decisions WHERE agent=\'auditor\' AND verdict=\'reject\' AND ts>=?', (ns,))} red",
                "analyst": f"alive · {cnt('SELECT COUNT(*) c FROM verdicts WHERE ts>=?', (ns,))} scored tonight · pass at {d.s('analyst.min_score')} · social off",
                "brain": f"alive · free cash ${d.free_cash():.2f} · {d.trades_tonight()}/{d.s('brain.max_trades_night')} trades tonight · {win}",
                "executor": f"alive · {len(getattr(ex, 'waiting', {}) or {})} waiting for a dip -{d.s('executor.dip_pct'):g}% · autoclick {d.s('desk.autoclick')}",
                "risk": (f"guarding {len(d.open_positions())} positions · stop -{d.s('risk.stop_pct'):g}% · trail {d.s('executor.trail_pct'):g}%"
                         if d.open_positions() else f"alive · no open positions · stop -{d.s('risk.stop_pct'):g}% ready"),
            }
            for a, line in lines.items():
                d.heartbeat_status(a, line)
        except Exception as e:
            log.info("status loop %s", e)
        await asyncio.sleep(60)


def migrate_v2(d):
    if d.db.kv_get("v2.migrated") == "1":
        return
    d.settings.set("analyst.mode", "v2", who="v2 upgrade")
    d.settings.set("desk.autoclick", "off", who="v2 upgrade")
    d.settings.set("desk.mode", "PAPER", who="v2 upgrade")
    d.db.kv_set("v2.migrated", "1")
    d.event("v2_upgrade", "settings moved to v2 defaults")


async def start_night(d):
    d.db.kv_set("night.locked", "0")
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
    migrate_v2(d)
    d.agents = {"scanner": Scanner(d), "auditor": Auditor(d), "analyst": Analyst(d), "brain": Brain(d),
                "executor": Executor(d), "risk": Risk(d)}
    d.lane = Lane(d)
    d.telegram = tg
    if not d.night() and d.in_night():
        await start_night(d)
    for p in d.open_positions():
        d.bus.risk.put_nowait(p["id"])
    app = api.make_app(d)
    cfg = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning", access_log=False, lifespan="off")
    server = uvicorn.Server(cfg)
    tasks = [d.agents[a].run() for a in d.agents] + [server.serve(), balance_loop(d), night_loop(d), status_loop(d), d.lane.run(),
             api.price_writer(d, app), api.planb_writer(d, ROOT / "out" / "site"), fomo_account.loop(d)]
    if tg:
        tasks.append(tg.poll())
    wd = Watchdog(d)
    wd.start_thread()
    tasks.append(wd.loop())
    log.info("desk up v2: mode=%s autoclick=%s port=%s agents=%s", d.mode(), d.s("desk.autoclick"), PORT, list(d.agents))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
