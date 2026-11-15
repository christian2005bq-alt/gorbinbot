"""v2 STEP 15.5 (offline part) test_browser: the cursor rules live in code. Withdraw is refused, every forbidden
button is refused, only links.py coin pages open, and the lane never does a real click in PAPER or unarmed."""
import asyncio, pytest
import browser as B
import links


def test_withdraw_refused_in_code():
    with pytest.raises(B.Forbidden):
        B.withdraw(5)
    with pytest.raises(B.Forbidden):
        B.deposit()


@pytest.mark.parametrize("txt", ["Withdraw", "Deposit", "Deposit more", "Buy with Apple Pay", "Orders", "Perps", "Send",
                                 "Settings", "Export private key", "Review withdraw", "Confirm", "Quick buy", "Log out", ""])
def test_forbidden_buttons(txt):
    with pytest.raises(B.Forbidden):
        B.guard_click(txt)


def test_allowed_buttons():
    for t in ("Buy", "Sell", "$10", "50%", "100%", "Buy PAWS", "Sell PAWS"):
        assert B.guard_click(t) == t
    with pytest.raises(B.Forbidden):
        B.guard_click("Max", side_tab="Buy")
    assert B.guard_click("Max", side_tab="Sell") == "Max"


def test_only_links_py_pages():
    m = "4CxjZyMNoF1p6eXHXHv1TWpS2X47CuUmLwtGe18spump"
    links.set_ref_code("gorbindx")
    assert B.guard_url(links.coin_url(m)) == links.coin_url(m)
    assert B.guard_url(links.profile_url("gorbindx"))
    for bad in ("https://fomo.family/discover", "https://fomo.family/profile/gorbindx/withdraw", "https://evil.example/coin?address=" + m,
                links.coin_url(m).replace("&source=share_link", ""), "https://fomo.family/settings"):
        with pytest.raises(B.Forbidden):
            B.guard_url(bad)


def test_lane_off_and_unarmed(desk):
    lane = B.Lane(desk)
    res = asyncio.run(lane.order("buy", "M" * 44, 2.0, dry=False))
    assert res["status"] == "skipped" and res["error"] == "autoclick off"
    row = desk.db.one("SELECT dry_run FROM orders WHERE id=?", (res["order_id"],))
    assert row["dry_run"] == 1                     # PAPER -> forced dry run even when asked for a real click
    assert not lane.armed()
    with pytest.raises(ValueError):
        desk.settings.set("desk.autoclick", "on")   # locked until the approved $2 test
    desk.settings.set("desk.autoclick", "dryrun")
    assert desk.s("desk.autoclick") == "dryrun" and not lane.armed()
