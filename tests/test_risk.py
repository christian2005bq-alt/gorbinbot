"""STEP 13.3 test_risk."""
import asyncio, time
from agents.risk import evaluate, Risk, exit_line
import views


def mkpos(desk, mint, entry=1.0, stop_pct=None, opened=None):
    stop_pct = stop_pct if stop_pct is not None else desk.s("risk.stop_pct")
    desk.db.exec("INSERT OR IGNORE INTO coins(mint,name,symbol,migrated_at) VALUES(?,?,?,?)", (mint, mint[:4], mint[:4], 0))
    pid = desk.db.exec("INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,trail_active,mode,stop_pct,status,last_price) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (mint, opened or time.time(), entry, 47.5, entry, entry * (1 - stop_pct / 100), 0, "PAPER", stop_pct, "open", entry))
    desk.db.kv_set("paper_cash", float(desk.db.kv_get("paper_cash")) - 47.5)
    return pid


def pos(desk, pid):
    return dict(desk.db.one("SELECT * FROM positions WHERE id=?", (pid,)))


def run(desk, rk, pid, price):
    asyncio.run(rk.step(pos(desk, pid), price, 100000))
    return pos(desk, pid)


def test_trail_stop_timeout(desk):
    rk = Risk(desk)
    a = mkpos(desk, "AAAA1")
    run(desk, rk, a, 1.25)                       # +25% -> trail on
    p = run(desk, rk, a, 1.25 * 0.87)            # 13% off the top
    assert p["exit_reason"] == "trail" and p["status"] == "closed"
    b = mkpos(desk, "BBBB1")
    p = run(desk, rk, b, 0.939)                  # -6.1%
    assert p["exit_reason"] == "stop"
    c = mkpos(desk, "CCCC1", opened=time.time() - 3 * 3600 - 1)
    p = run(desk, rk, c, 1.04)                   # 3h at +4%
    assert p["exit_reason"] == "timeout"
    print("\n+25% then 13% off top = trail · -6.1% = stop · 3h at +4% = timeout")


def test_stop_never_moves_down(desk):
    rk = Risk(desk)
    old = mkpos(desk, "OLD11")                    # opened at -6%
    desk.settings.set("risk.stop_pct", 8)         # loosen
    p = run(desk, rk, old, 0.99)
    assert p["stop_pct"] == 6 and abs(p["stop_price"] - 0.94) < 1e-9
    desk.settings.set("risk.stop_pct", 4)         # tighten -> applies to open
    p = run(desk, rk, old, 0.99)
    assert p["stop_pct"] == 4
    desk.settings.set("risk.stop_pct", 8)
    p = run(desk, rk, old, 0.99)
    assert p["stop_pct"] == 4                      # never loosens back


def test_set_stop_minus_8_flow(desk):
    from telegram import Telegram
    tg = Telegram(desk)
    reply = asyncio.run(tg.command("set stop to -8%"))
    assert reply == "stop -6% -> -8%", reply
    rk = Risk(desk)
    desk.settings.set("risk.stop_pct", 6, who="test")
    six = mkpos(desk, "SIX11")                    # opened while stop was -6%
    desk.settings.set("risk.stop_pct", 8, who="test")
    eight = mkpos(desk, "EIGHT")                  # new PAPER position at -8%
    p = run(desk, rk, eight, 0.919)               # drop 8.1%
    assert p["exit_reason"] == "stop" and p["stop_pct"] == 8
    push = desk.notifier.sent[-1]["text"]
    assert push.startswith("PAPER · ") and "hit the -8% stop" in push, push
    act = desk.db.one("SELECT * FROM activity ORDER BY id DESC LIMIT 1")
    assert act["subtitle"] == "Risk · -8% stop" and act["title"] == "Stopped EIGH"
    marks = views.chart(desk, "1H")["marks"]
    assert marks and marks[-1]["text"].startswith("-8% · -$"), marks
    risk_card = [a for a in views.state(desk)["agents"] if a["name"] == "risk"][0]
    assert risk_card["stop_pct"] == 8                 # pill "stop -8%"
    p6 = run(desk, rk, six, 0.95)
    assert p6["stop_pct"] == 6 and p6["status"] == "open"
    assert views.coin(desk, "SIX11")["exit"]["stop_pct"] == 6
    print(f"\npush: {push}\nactivity: {act['title']} / {act['subtitle']} / {act['value']}\nmark: {marks[-1]['text']}\npill: stop -{risk_card['stop_pct']:g}% · old position still -6%")
