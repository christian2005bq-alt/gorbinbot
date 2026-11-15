"""STEP 13.1 test_links: every FOMO URL carries r=gorbindx (desk.ref_code); unknown chain -> SIGNUP_URL; no shortened/redirected links."""
import re, json, subprocess, asyncio
from pathlib import Path
import links
ROOT = Path(__file__).resolve().parents[1]
FOMO = re.compile(r"https?://(?:www\.)?fomo\.family[^\s\"'<>)\]]*")
SHORT = re.compile(r"(t\.co/|bit\.ly|tinyurl|goo\.gl|ow\.ly|is\.gd|buff\.ly|rebrand\.ly|cutt\.ly|lnkd\.in)", re.I)
def ok_url(u, ref=None):
    r = ref or links.ref_code()
    return f"r={r}" in u or u.rstrip("/").endswith(f"/r/{r}")


def test_builders():
    links.set_ref_code("gorbindx")
    u = links.coin_url("Mint111", "solana")
    assert u == "https://fomo.family/coin?address=Mint111&chainId=1399811149&r=gorbindx&source=share_link"
    assert links.coin_url("X", "dogechain") == links.SIGNUP_URL == "https://fomo.family/r/gorbindx"
    assert links.profile_url("@gorbindx") == "https://fomo.family/profile/gorbindx?source=share_link&r=gorbindx"
    for ch in links.CHAIN_ID:
        assert ok_url(links.coin_url("M", ch))


def test_ref_code_setting(desk):
    desk.settings.set("desk.ref_code", "gorbindx")
    assert "r=gorbindx" in links.coin_url("M", "solana")
    desk.settings.set("desk.ref_code", "otherref")
    assert links.coin_url("Mint111", "solana") == "https://fomo.family/coin?address=Mint111&chainId=1399811149&r=otherref&source=share_link"
    assert links.profile_url("gorbindx") == "https://fomo.family/profile/gorbindx?source=share_link&r=otherref"
    assert links.SIGNUP_URL == "https://fomo.family/r/otherref"
    try:
        desk.settings.set("desk.ref_code", "bad code!")
        assert False, "invalid ref_code should raise"
    except ValueError:
        pass
    desk.settings.set("desk.ref_code", "gorbindx")
    assert links.ref_code() == "gorbindx"


def test_repo_grep():
    """No FOMO URL is written anywhere in the code except links.py; no shorteners anywhere."""
    bad = []
    for p in list(ROOT.glob("*.py")) + list((ROOT / "agents").glob("*.py")) + list((ROOT / "web").rglob("*")):
        if p.is_file() and p.name != "links.py" and p.suffix in (".py", ".js", ".html", ".css", ".json"):
            t = p.read_text(errors="ignore")
            if "fomo.family" in t:
                bad.append(f"{p.name}: FOMO URL outside links.py")
            if SHORT.search(t):
                bad.append(f"{p.name}: shortener")
    assert not bad, bad


def test_rendered_everywhere(desk):
    """API responses, rendered pushes, Account tab and the Page."""
    import views, report
    from agents.executor import Executor
    from agents.risk import Risk
    from tests.conftest import pair
    m = "TestMint1111111111111111111111111111111pump"
    desk.db.exec("INSERT INTO coins(mint,name,symbol,migrated_at,first_seen) VALUES(?,?,?,?,?)", (m, "Test", "TST", 0, 1e12))
    desk.settings.set("desk.fomo_handle", "gorbindx")
    desk.settings.set("desk.ref_code", "gorbindx")
    ex, rk = Executor(desk), Risk(desk)
    desk.agents = {"executor": ex, "risk": rk}

    async def fake_tokens(mints):
        return {x: pair(x, 1.0) for x in mints}
    desk.dex.tokens = fake_tokens
    import time as _t
    sid = asyncio.run(ex.handle({"scan": {"mint": m, "liquidityUsd": 100000}, "verdict": {"score": 80, "price": 1.0}, "audit": {"_ctx": {}},
                                 "brain": {"sizeUsd": 3.6, "pctOfCash": 12, "capHit": "none"}}))["signal_id"]
    desk.db.exec("INSERT INTO prices(mint,ts,price) VALUES(?,?,?)", (m, _t.time() - 60, 1.0))
    asyncio.run(ex.on_poll({m: pair(m, 0.85, b5=20, s5=10)}))
    pos = desk.open_positions()[0]
    asyncio.run(rk.step(pos, 0.6, 100000))
    urls = []
    for push in desk.notifier.sent:
        for label, tgt in push["buttons"] or []:
            if tgt.startswith("http"):
                urls.append(tgt)
        urls += FOMO.findall(push["text"])
    assert len(desk.notifier.sent) == 2 and len(urls) == 2
    blobs = [json.dumps(views.state(desk)), json.dumps(views.activity(desk)), json.dumps(views.coin(desk, m)),
             json.dumps(views.audit(desk, m)), json.dumps(views.account(desk)), json.dumps(views.decisions(desk, "executor")),
             report.build(desk).read_text()]
    for b in blobs:
        urls += FOMO.findall(b)
    assert urls and all(ok_url(u) for u in urls), [u for u in urls if not ok_url(u)]
    assert not any(SHORT.search(u) for u in urls)
    acc = views.account(desk)
    assert acc["profile_url"] == links.profile_url("gorbindx") == "https://fomo.family/profile/gorbindx?source=share_link&r=gorbindx"
    assert acc["signup_url"] == links.SIGNUP_URL == "https://fomo.family/r/gorbindx"
    assert acc["fomo_handle"] == "gorbindx"
    print(f"\nchecked {len(urls)} FOMO URLs across pushes, API, Account, Page: all carry r=gorbindx")


def test_live_db_pushes():
    """Pushes already sent by the running desk (if any). Historical rows may still carry an older referral."""
    from db import DB
    p = ROOT / "desk.db"
    if not p.exists():
        return
    rows = DB(p).all("SELECT link, text FROM pushes")
    for r in rows:
        if r["link"]:
            assert "fomo.family" in r["link"] and ("r=" in r["link"] or "/r/" in r["link"]), r
