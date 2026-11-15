"""THE ONLY module that touches FOMO web (v2 STEP 9). The auto-click lane.

Plan A: Playwright connect_over_cdp to the dedicated Chrome (profile /workspace/desk/chrome, remote debugging
on 127.0.0.1:[9222] only, started by tools/start_chrome.sh). Christian logs in there himself, once.
Cursor rules are enforced HERE, in code, not in a prompt:
  * pages: FOMO coin pages built by links.coin_url, and the profile (read only). Nothing else.
  * clickable: Buy / Sell tabs, the amount field, presets, Max (Sell tab), "Buy {symbol}" / "Sell {symbol}".
  * never: Withdraw, Deposit, Deposit more, Buy with Apple Pay, Orders, Perps, Send, settings, export, keys,
    the Swap settings gear, /discover, a Thesis post, any box to tick. Withdraw is refused by code, always.
desk.autoclick: off (default, lane never starts) | dryrun (opens, types, reads the quote, screenshots, never
presses the primary button) | on (presses it; locked until a verified $2 test trade Christian approved)."""
import asyncio, json, re, time
from pathlib import Path
import links
from common import ROOT, now, get_logger, LOGS, mask_secret

log = get_logger("browser")
DATA = ROOT / "data"
FRAMES = DATA / "frames"
ORDERS = LOGS / "orders"
FAIL = LOGS / "fail"
BOT_COLORS = {"scanner": "#64d2ff", "analyst": "#ffd60a", "brain": "#bf5af2", "executor": "#00d35a", "risk": "#ff6b9a"}

FORBIDDEN = re.compile(
    r"withdraw|deposit|apple\s*pay|\bsend\b|\borders?\b|perps|setting|export|private\s*key|seed|recovery|"
    r"\bconfirm\b|review|discover|thesis|slippage|gear|2fa|password|passcode|log\s*out|sign\s*out|delete|"
    r"transfer|bridge|card|quick\s*buy", re.I)
ALLOWED_EXACT = {"Buy", "Sell", "Paste", "$10", "$100", "$500", "$1000", "10%", "25%", "50%", "100%", "Max"}
PRIMARY = re.compile(r"^(Buy|Sell) [^\s].{0,30}$")
QUOTE_RE = re.compile(r"([\d.,]+\s?[KMB]?)\s+(\S+)\s+\((-?[\d.]+)%\)")
FEE_RE = re.compile(r"\$([\d.,]+)\s+fee", re.I)


class Forbidden(Exception):
    pass


def guard_click(text: str, side_tab: str | None = None) -> str:
    """Raise Forbidden unless the visible text is on the click allowlist."""
    t = (text or "").strip()
    if not t or FORBIDDEN.search(t):
        raise Forbidden(f"click refused: {t!r}")
    if t in ALLOWED_EXACT:
        if t == "Max" and side_tab != "Sell":
            raise Forbidden("Max only on the Sell tab")
        return t
    if PRIMARY.match(t):
        return t
    raise Forbidden(f"click refused (not on the allowlist): {t!r}")


def guard_url(url: str) -> str:
    """Only coin pages exactly as links.py builds them, and a profile page (read only)."""
    if links.is_desk_page(url):
        return url
    raise Forbidden(f"page refused: {(url or '')[:80]}")


def withdraw(*_a, **_k):
    """v2 S7 is NOT implemented on purpose: the desk can never press Withdraw. Christian does it on FOMO himself."""
    raise Forbidden("Withdraw is forbidden in code")


deposit = withdraw

CURSOR_JS = """
(() => { if (window.__deskCursors) return; window.__deskCursors = {};
  window.__deskCursor = (bot, color, x, y, dip) => {
    let c = window.__deskCursors[bot];
    if (!c) { c = document.createElement('div'); c.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;transition:transform 300ms ease-out;left:0;top:0';
      c.innerHTML = '<svg width="18" height="22" viewBox="0 0 18 22"><path d="M1 1l15 9-7 1-3 7z" fill="'+color+'" stroke="#000" stroke-width="1"/></svg><div style="font:11px -apple-system;color:'+color+'">'+bot+'</div>';
      document.documentElement.appendChild(c); window.__deskCursors[bot] = c; }
    c.style.transform = 'translate('+x+'px,'+y+'px) scale('+(dip?0.85:1)+')'; };
})();
"""


class Lane:
    def __init__(self, desk):
        self.d = desk
        self.lock = asyncio.Lock()
        self.priority_waiting = 0
        self.pw = None
        self.browser = None
        self.page = None
        self.logged_in = None
        self.holder = None            # (bot, side) holding the lane right now
        self.last_frame_ts = 0.0
        self.private = False
        self.api = None               # verify.FomoAPI, fed by the page's own requests
        self.status = "off"

    # ---------- state
    def mode(self):
        return self.d.s("desk.autoclick")

    def armed(self):
        return (self.mode() == "on" and self.d.db.kv_get("autoclick.test_ok") == "1" and bool(self.logged_in))

    def card(self):
        return {"mode": self.mode(), "status": self.status, "logged_in": self.logged_in, "armed": self.armed(),
                "holder": self.holder, "last_frame_ts": self.last_frame_ts or None, "private": self.private}

    # ---------- connection
    async def connect(self):
        if self.page is not None and not self.page.is_closed():
            return True
        try:
            from playwright.async_api import async_playwright
            if self.pw is None:
                self.pw = await async_playwright().start()
            port = int(self.d.s("desk.cdp_port"))
            self.browser = await self.pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=10000)
            ctx = self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context()
            page = None
            for pg in ctx.pages:
                try:
                    if await pg.evaluate("document.title") == "desk" or links.on_coin_or_profile(pg.url):
                        page = pg; break
                except Exception:
                    pass
            self.page = page or (ctx.pages[0] if ctx.pages else await ctx.new_page())
            await self.page.add_init_script(CURSOR_JS)
            from verify import FomoAPI
            self.api = self.api or FomoAPI(self.d)
            self.page.on("request", self.api.on_request)
            self.status = "connected"
            log.info("lane connected to Chrome on 127.0.0.1:%s", port)
            return True
        except Exception as e:
            self.page = None
            self.status = f"no Chrome on 127.0.0.1:{self.d.s('desk.cdp_port')}"
            log.info("lane connect failed: %s", type(e).__name__)
            return False

    async def goto(self, url):
        guard_url(url)
        await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await self.page.wait_for_timeout(1500)

    async def body_text(self):
        try:
            return await self.page.inner_text("body", timeout=5000)
        except Exception:
            return ""

    async def check_session(self, text=None):
        """S0: logged in = the header shows the cash + "Deposit more" (read, never clicked); no signup page."""
        t = text if text is not None else await self.body_text()
        if "only available on desktop" in t:
            return "narrow window"
        logged = ("Deposit more" in t) and not re.search(r"\b(Sign up|Log in|Create account)\b", t)
        self.logged_in = logged
        return None if logged else "logged out"

    # ---------- clicks (the only way anything gets clicked)
    async def click(self, locator, bot, side_tab=None):
        txt = (await locator.inner_text(timeout=3000)).strip()
        guard_click(txt, side_tab)
        box = await locator.bounding_box()
        if not box:
            raise RuntimeError(f"no box for {txt!r}")
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        try:
            await self.page.evaluate("([b,c,x,y,d]) => window.__deskCursor && window.__deskCursor(b,c,x,y,d)",
                                     [bot, BOT_COLORS.get(bot, "#fff"), x, y, False])
            await self.page.wait_for_timeout(320)
            await self.page.evaluate("([b,c,x,y,d]) => window.__deskCursor && window.__deskCursor(b,c,x,y,d)",
                                     [bot, BOT_COLORS.get(bot, "#fff"), x, y, True])
        except Exception:
            pass
        await self.page.mouse.click(x, y)
        return txt

    async def shot(self, oid, name):
        d = ORDERS / str(oid); d.mkdir(parents=True, exist_ok=True)
        p = d / f"{name}.jpg"
        try:
            await self.page.screenshot(path=str(p), type="jpeg", quality=60)
        except Exception:
            return None
        return str(p)

    # ---------- the order lane
    async def order(self, side, mint, usd, pct=None, bot="executor", reason="", dry=True, priority=False, symbol=None,
                    approved_test=False):
        """1 order at a time. Risk sells (priority) jump the queue. Returns the order dict.
        approved_test: ONLY tools/desk_cli.py test-trade (Christian's approved $2 test) may click for real
        before the lane is armed, and only a buy of at most $2.00 or the sell of that test position."""
        mode = self.d.mode()
        test_ok = approved_test and ((side == "buy" and usd is not None and usd <= 2.0) or side == "sell")
        if not dry and not test_ok and (mode != "LIVE" or not self.armed()):
            dry = True                  # never a real click unless LIVE + armed (or the approved $2 test)
        oid = self.d.db.exec("INSERT INTO orders(ts,mint,side,usd,pct,bot,reason,status,mode,dry_run) VALUES(?,?,?,?,?,?,?,?,?,?)",
                             (now(), mint, side, usd, pct, bot, reason, "queued", mode, int(dry)))
        res = {"order_id": oid, "status": "queued", "screen_ok": None, "api_ok": None, "chain_ok": None}
        if self.mode() == "off":
            return self._finish(oid, res, "skipped", error="autoclick off")
        if priority:
            self.priority_waiting += 1
        try:
            while not priority and self.priority_waiting > 0:
                await asyncio.sleep(0.2)
            async with self.lock:
                if priority:
                    self.priority_waiting -= 1; priority = False
                self.holder = (bot, side)
                try:
                    return await asyncio.wait_for(self._run(oid, side, mint, usd, pct, bot, dry, symbol, res), timeout=120)
                except Forbidden as e:
                    return self._finish(oid, res, "failed", error=str(e))
                except asyncio.TimeoutError:
                    return self._finish(oid, res, "failed", error="lane timeout")
                except Exception as e:
                    return self._finish(oid, res, "failed", error=f"{type(e).__name__}: {mask_secret(str(e))[:200]}")
                finally:
                    self.holder = None
        finally:
            if priority:
                self.priority_waiting -= 1

    def _finish(self, oid, res, status, error=None, **kw):
        res.update(kw); res["status"] = status; res["error"] = error
        self.d.db.exec("UPDATE orders SET status=?, error=?, quote_text=?, fee_text=?, screen_ok=?, api_ok=?, chain_ok=?, fill_usd=?, shot_path=? WHERE id=?",
                       (status, error, res.get("quote_text"), res.get("fee_text"), res.get("screen_ok"), res.get("api_ok"),
                        res.get("chain_ok"), res.get("fill_usd"), res.get("shot_path"), oid))
        log.info("order %s %s -> %s %s", oid, json.dumps({k: res.get(k) for k in ("quote_text", "fee_text", "screen_ok", "api_ok", "chain_ok")}), status, error or "")
        self.d.bus.emit("order", {"id": oid, **{k: v for k, v in res.items() if k != "order_id"}})
        return res

    async def _run(self, oid, side, mint, usd, pct, bot, dry, symbol, res):
        self.d.db.exec("UPDATE orders SET status='clicking' WHERE id=?", (oid,))
        if not await self.connect():
            return self._finish(oid, res, "failed", error=self.status)
        await self.goto(links.coin_url(mint, "solana"))                         # S1
        text = await self.body_text()
        bad = await self.check_session(text)                                    # S0
        if bad:
            res["shot_path"] = await self.shot(oid, "before")
            if bad == "logged out" and self.d.notifier:
                await self.d.notifier.push("FOMO logged out. Take control and log in", None, kind="alert", buttons=False)
            return self._finish(oid, res, "failed", error=bad)
        if not (mint[:6] in text and mint[-6:] in text):
            res["shot_path"] = await self.shot(oid, "before")
            return self._finish(oid, res, "failed", error="contract address mismatch")
        res["shot_path"] = await self.shot(oid, "before")
        tab = "Buy" if side == "buy" else "Sell"
        await self.click(self.page.get_by_text(tab, exact=True).first, bot)
        if side == "sell" and dry and self.d.mode() == "PAPER":
            res["shot_path"] = await self.shot(oid, "sell_tab")               # PAPER holds nothing on FOMO
            return self._finish(oid, res, "dry-run", error=None)
        if side == "buy":
            fld = self.page.get_by_placeholder("Enter amount").first
            want = f"{usd:.2f}"
            for attempt in range(2):
                await fld.click(); await self.page.keyboard.press("Control+A"); await self.page.keyboard.type(want, delay=40)
                await self.page.wait_for_timeout(300)
                got = (await fld.input_value()).replace("$", "").replace(",", "").strip()
                try:
                    if abs(float(got) - float(want)) < 0.005:
                        break
                except ValueError:
                    pass
            else:
                return self._finish(oid, res, "failed", error="amount mismatch")
        else:
            label = f"{int(pct)}%" if pct in (10, 25, 50, 100) else "100%"
            await self.click(self.page.get_by_text(label, exact=True).first, bot, side_tab="Sell")
        q = await self.wait_quote()
        if not q:
            return self._finish(oid, res, "failed", error="no quote")
        res["quote_text"], res["fee_text"] = q
        res["shot_path"] = await self.shot(oid, "quote")
        t = await self.body_text()
        if re.search(r"price impact too high", t, re.I):
            return self._finish(oid, res, "failed", error="price impact too high")
        if side == "sell" and "Minimum amount $2" in t:
            return self._finish(oid, res, "failed", error="dust under $2")
        if await self.page.locator("input[type=checkbox]:visible").count():
            return self._finish(oid, res, "failed", error="box to tick: skip")
        btn = self.page.get_by_role("button", name=re.compile(rf"^{tab} ")).first
        btxt = (await btn.inner_text(timeout=3000)).strip()
        if "Apple Pay" in btxt:
            return self._finish(oid, res, "failed", error="no cash")
        guard_click(btxt)
        if await btn.is_disabled():
            return self._finish(oid, res, "failed", error="button disabled")
        if dry:
            return self._finish(oid, res, "dry-run")                           # stops before the primary button
        from verify import verify_after
        before = await self.api.chain_balance(mint) if self.api else None
        await self.click(btn, bot)
        self.d.db.exec("UPDATE orders SET status='verifying' WHERE id=?", (oid,))
        done_word = "Bought" if side == "buy" else "Sold"
        screen = await self.wait_text(done_word, self.d.s("executor.verify_timeout_s"))
        res["screen_ok"] = screen
        res["shot_path"] = await self.shot(oid, "after")
        v = await verify_after(self, side, mint, usd, before, self.d.s("executor.verify_timeout_s"))
        res.update(v)
        await self.shot(oid, "positions")
        ok = bool(screen) and v.get("api_ok") is True and (v.get("chain_ok") is True or bool(v.get("chain_na")))
        if ok:
            return self._finish(oid, res, "done")
        if screen:
            p = FAIL / f"order_{oid}.jpg"
            try:
                await self.page.screenshot(path=str(p), type="jpeg", quality=60)
            except Exception:
                pass
            return self._finish(oid, res, "unverified", error="screen done, api/chain not")
        return self._finish(oid, res, "unverified", error=f"no '{done_word}' in time")

    async def wait_quote(self):
        t_end = time.time() + self.d.s("executor.quote_timeout_s")
        reloaded = False
        while True:
            t = await self.body_text()
            q, f = QUOTE_RE.search(t), FEE_RE.search(t)
            if q:
                return q.group(0), (f.group(0) if f else None)
            if time.time() > t_end:
                if reloaded:
                    return None
                reloaded = True
                await self.page.reload(); await self.page.wait_for_timeout(1500)
                t_end = time.time() + self.d.s("executor.quote_timeout_s")
            await asyncio.sleep(0.5)

    async def wait_text(self, word, timeout):
        t_end = time.time() + timeout
        while time.time() < t_end:
            if re.search(rf"\b{word}\b", await self.body_text()):
                return True
            await asyncio.sleep(0.5)
        return False

    # ---------- Live screen frames
    async def frames_loop(self):
        FRAMES.mkdir(parents=True, exist_ok=True)
        n = 0
        while True:
            await asyncio.sleep(1)
            if self.mode() == "off":
                self.status = "off"
                continue
            if self.page is None or self.page.is_closed():
                if n % 30 == 0:
                    await self.connect()
                n += 1
                continue
            try:
                url = self.page.url
                self.private = not links.on_coin_or_profile(url)
                if self.private:
                    continue                 # login / anything else: "Paused · private", no frames
                img = await self.page.screenshot(type="jpeg", quality=60, timeout=5000)
                tmp = DATA / "screen.tmp"; tmp.write_bytes(img); tmp.replace(DATA / "screen.jpg")
                self.last_frame_ts = now()
                n += 1
                if n % 5 == 0:               # keep ~300 frames (1 every 5s) for the morning Page
                    (FRAMES / f"{int(now())}.jpg").write_bytes(img)
                    old = sorted(FRAMES.glob("*.jpg"))[:-300]
                    for o in old:
                        o.unlink(missing_ok=True)
            except Exception:
                await asyncio.sleep(4)

    async def run(self):
        await self.frames_loop()
