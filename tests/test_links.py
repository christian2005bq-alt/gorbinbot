"""STEP 13.1 test_links: every FOMO URL carries r=savipww; unknown chain -> SIGNUP_URL; no shortened/redirected links."""
import re, json, subprocess, asyncio
from pathlib import Path
import links
ROOT = Path(__file__).resolve().parents[1]
FOMO = re.compile(r"https?://(?:www\.)?fomo\.family[^\s\"'<>)\]]*")
SHORT = re.compile(r"(t\.co/|bit\.ly|tinyurl|goo\.gl|ow\.ly|is\.gd|buff\.ly|rebrand\.ly|cutt\.ly|lnkd\.in)", re.I)


def ok_url(u):
    return "r=savipww" in u or u.rstrip("/").endswith("/r/savipww")


def test_builders():
    u = links.coin_url("Mint111", "solana")
    assert u == "https://fomo.family/coin?address=Mint111&chainId=1399811149&r=savipww&source=share_link"
    assert links.coin_url("X", "dogechain") == links.SIGNUP_URL == "https://fomo.family/r/savipww"
    assert links.profile_url("@gorbindx") == "https://fomo.family/profile/gorbindx?source=share_link&r=savipww"
    for ch in links.CHAIN_ID:
        assert ok_url(links.coin_url("M", ch))


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
    ex, rk = Executor(desk), Risk(desk)
    desk.agents = {"executor": ex, "risk": rk}

    async def fake_tokens(mints):
        return {x: pair(x, 1.0) for x in mints}
    desk.dex.tokens = fake_tokens
    asyncio.run(ex.handle({"scan": {"mint": m, "liquidityUsd": 100000}, "verdict": {"score": 80, "price": 1.0}}))
    pos = desk.open_positions()[0]
    asyncio.run(rk.step(pos, 0.9, 100000))
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
    assert acc["profile_url"] == links.profile_url("gorbindx") and acc["signup_url"] == links.SIGNUP_URL
    print(f"\nchecked {len(urls)} FOMO URLs across pushes, API, Account, Page: all carry r=savipww")


def test_live_db_pushes():
    """Pushes already sent by the running desk (if any)."""
    from db import DB
    p = ROOT / "desk.db"
    if not p.exists():
        return
    rows = DB(p).all("SELECT link, text FROM pushes")
    for r in rows:
        if r["link"]:
            assert ok_url(r["link"]), r
