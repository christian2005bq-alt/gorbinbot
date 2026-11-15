"""copy-picks STEP 6 (1, 2, 4), weekly-review data, social Plan C/A."""
import asyncio, json, time
import links, picks, weekly, social


def board(rows):
    return picks.norm_board(rows, set())


def test_picks_list_links_and_one_coin_wonder(desk):
    now = time.time()
    b30 = board([{"id": "1", "handle": "alpha", "pnl": 9000, "trades": 80}, {"id": "2", "handle": "wonder", "pnl": 8000, "trades": 50},
                 {"id": "3", "handle": "priv", "pnl": 7000, "trades": 90, "private": True}, {"id": "4", "handle": "few", "pnl": 6000, "trades": 5},
                 {"id": "5", "handle": "only30", "pnl": 5000, "trades": 40}, {"id": "6", "handle": "stale", "pnl": 4000, "trades": 40}])
    b7 = board([{"id": "1", "handle": "alpha", "pnl": 900}, {"id": "2", "handle": "wonder", "pnl": 800}, {"id": "3", "pnl": 1},
                {"id": "4", "pnl": 1}, {"id": "6", "handle": "stale", "pnl": 10}])
    sw = lambda mint, usd, ts, side="buy", sym="AAA": {"side": side, "mint": mint, "symbol": sym, "usd": usd, "ts": ts, "mcap": 250000, "chain": "solana", "sig": f"{mint}{ts}{side}"}
    swaps = {"1": [sw("MintA1111111111111111111111111111111111pump", 50, now - 600)] + [sw(f"Mint{i}" + "1" * 36 + "pump", 50, now - 900 - i, "sell" if i % 2 else "buy", f"C{i}") for i in range(10)],
             "2": [sw("MintW1111111111111111111111111111111111pump", 900, now - 60, sym="WON"), sw("MintX1111111111111111111111111111111111pump", 100, now - 70)],
             "6": [sw("MintS1111111111111111111111111111111111pump", 10, now - 3 * 86400)]}
    out, dropped = picks.make_list({"30d": b30, "7d": b7, "24h": {}}, swaps, desk.s, now)
    assert [t["handle"] for t in out] == ["alpha"]
    why = {d["handle"]: d["why"] for d in dropped}
    assert why["wonder"].startswith("1 coin wonder: 90% ") and "WON" in why["wonder"]
    assert why["priv"] == "private/restricted" and why["few"] == "under 20 trades"
    assert why["only30"] == "not on both 7d and 30d" and why["stale"].startswith("last trade older")
    text, buttons = picks.message(out, now)
    assert text.startswith("Grok Bot · 1 traders worth copying today")
    assert links.profile_url("alpha") in text and links.coin_url("MintA1111111111111111111111111111111111pump", "solana") in text
    assert text.rstrip().endswith("New to FOMO? " + links.signup_url())
    assert buttons[0][1] == links.profile_url("alpha")


def test_one_coin_no_usd_key():
    assert picks.one_coin([{"mint": "a", "usd": None}], 60) is None
    assert "1 coin check: no data" in picks.why({"one_coin": None})


def test_blocked_run_is_stored_and_no_token_leaks(desk):
    class NoToken:
        token = ""; calls = 0
    row = picks.run(desk, NoToken())
    assert row["status"] == "blocked" and "431" in row["error"]
    assert picks.recent(desk)[0]["status"] == "blocked"


def test_api_guard_only_reads():
    api = picks.FomoAPI(token="x")
    try:
        api.get("/v2/users/1/balances"); assert False
    except ValueError:
        pass


def test_new_swaps_marks_old_as_seen():
    seen = set()
    assert len(picks.new_swaps(seen, [{"sig": "a"}, {"sig": "b"}])) == 2   # first pass = mark only (caller copies nothing)
    assert [s["sig"] for s in picks.new_swaps(seen, [{"sig": "a"}, {"sig": "c"}])] == ["c"]


def test_copy_defaults_off(desk):
    assert desk.s("copy.enabled") is False and desk.s("copy_picks.every") == "24h" and desk.s("copy_picks.time") == "21:30"


def test_weekly_medians(desk):
    t = time.time()
    for i, (pnl, sc) in enumerate([(5, 80), (3, 90), (-2, 71)]):
        m = f"W{i}" + "1" * 38 + "pump"
        desk.db.exec("INSERT INTO positions(mint,opened_at,entry_price,size_usd,closed_at,pnl_usd,status,mode) VALUES(?,?,?,?,?,?,?,?)", (m, t - 100, 1, 5, t - 50, pnl, "closed", "PAPER"))
        desk.db.exec("INSERT INTO verdicts(mint,ts,score,pass,social_pts,fresh_pct) VALUES(?,?,?,?,?,?)", (m, t - 120, sc, 1, 0, 10))
    r = "R" + "1" * 39 + "pump"
    desk.decision("scanner", r, "kill", "liq $3K")
    desk.db.exec("INSERT INTO prices(mint,ts,price) VALUES(?,?,?)", (r, time.time() + 1, 1.0))
    desk.db.exec("INSERT INTO prices(mint,ts,price) VALUES(?,?,?)", (r, time.time() + 2, 2.5))
    w = weekly.build(desk)
    assert w["counts"]["green"] == 2 and w["counts"]["red"] == 1 and w["counts"]["skipped_2x"] == 1
    assert w["medians"]["score"]["green"] == 85 and w["medians"]["score"]["red"] == 71
    assert "| score | 85 | 71 |" in weekly.markdown(w)


def test_social_off_and_plan_a(desk, tmp_path, monkeypatch):
    monkeypatch.setattr(social, "DIR", tmp_path / "social"); monkeypatch.setattr(social, "REQ", tmp_path / "social" / "requests")
    assert asyncio.run(social.ask("M", {}, desk.s)) == (None, 0.0, "C")
    desk.settings.set("social.enabled", True); desk.settings.set("social.timeout_s", 5)
    (tmp_path / "social").mkdir()
    (tmp_path / "social" / "M.json").write_text(json.dumps({"u15": 20, "u60": 40, "big": 3, "smart": 2}))
    v, sh, plan = asyncio.run(social.ask("M", {}, desk.s))
    assert plan == "A" and v == round(0.30 + 0.15 + 0.30, 4)
    v, sh, plan = asyncio.run(social.ask("N", {"baseToken": {"symbol": "N"}}, desk.s))
    assert v is None and (tmp_path / "social" / "requests" / "N.json").exists()
