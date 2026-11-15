"""API for the app (STEP 7, plan A shape) + the plan B JSON writer. Every /api call needs APP_TOKEN, else 401."""
import asyncio, hashlib, json, os, secrets, shutil, time
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
import views, links
import fields as F
from common import SECRETS, ROOT, now, get_logger

log = get_logger("api")
WEB = ROOT / "web"
PLAN = os.environ.get("DESK_PLAN", "B")


def make_app(desk):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    token = SECRETS.get("APP_TOKEN", "")
    viewed: dict[str, float] = {}

    def auth(req: Request):
        h = req.headers.get("authorization", "")
        if not token or not h.startswith("Bearer ") or not secrets.compare_digest(h[7:], token):
            raise HTTPException(401, "unauthorized")

    @app.middleware("http")
    async def guard(req: Request, call_next):
        if req.url.path.startswith("/api"):
            try:
                auth(req)
            except HTTPException:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(req)

    @app.get("/api/rev")
    async def rev(req: Request):
        tag = '"' + hashlib.sha1(views.revision(desk).encode()).hexdigest()[:16] + '"'
        headers = {
            "ETag": tag,
            "Cache-Control": "no-store, no-cache, must-revalidate, no-transform",
            "X-Accel-Buffering": "no",
        }
        inm = req.headers.get("if-none-match") or ""
        if tag in {t.strip() for t in inm.split(",") if t.strip()}:
            return Response(status_code=304, headers=headers)
        return JSONResponse({"rev": tag.strip('"')}, headers=headers)

    @app.get("/api/state")
    async def state():
        return views.state(desk)

    @app.get("/api/chart")
    async def chart(range: str = "LIVE"):
        return views.chart(desk, range)

    @app.get("/api/activity")
    async def activity(before: int | None = None):
        return views.activity(desk, before)

    @app.get("/api/live")
    async def live(before: float | None = None):
        return views.live(desk, before)

    @app.get("/api/fomo_account")
    async def fomo_acct():
        import fomo_account
        return fomo_account.view(desk)

    @app.get("/api/picks")
    async def get_picks():
        import picks
        sw = {r["id"]: bool(r["on_desk"]) for r in desk.db.all("SELECT id, on_desk FROM copy_traders")}
        return {"runs": picks.recent(desk, 7), "every": desk.s("copy_picks.every"), "time": desk.s("copy_picks.time"),
                "copy_enabled": desk.s("copy.enabled"), "switches": sw, "signup_url": links.signup_url()}

    @app.post("/api/copy/{uid}")
    async def copy_switch(uid: str, req: Request):
        b = await req.json()
        if b.get("on") and not desk.s("copy.enabled"):
            return JSONResponse({"error": "Copy on desk is off (STEP 5 stays off for now)"}, status_code=409)
        on_now = desk.db.one("SELECT COUNT(*) c FROM copy_traders WHERE on_desk=1 AND id<>?", (uid,))["c"]
        if b.get("on") and on_now >= desk.s("copy.max_traders"):
            return JSONResponse({"error": f"max {desk.s('copy.max_traders')} traders on copy"}, status_code=409)
        desk.db.exec("INSERT INTO copy_traders(id,handle,on_desk,updated_at) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET on_desk=excluded.on_desk, updated_at=excluded.updated_at",
                     (uid, b.get("handle"), 1 if b.get("on") else 0, now()))
        return {"id": uid, "on": bool(b.get("on"))}

    @app.get("/api/coin/{mint}")
    async def coin(mint: str):
        viewed[mint] = now()
        return views.coin(desk, mint)

    @app.get("/api/audit/{mint}")
    async def audit(mint: str):
        viewed[mint] = now()
        return views.audit(desk, mint)

    @app.get("/api/agents/{name}/decisions")
    async def decisions(name: str):
        return views.decisions(desk, name)

    @app.get("/api/account")
    async def account():
        return views.account(desk, PLAN)

    @app.get("/api/settings")
    async def get_settings():
        return views.settings(desk)

    @app.post("/api/settings")
    async def post_settings(req: Request):
        body = await req.json()
        res, errs = {}, {}
        for k, v in body.items():
            if k == "desk.mode":   # PAPER/LIVE only through /api/mode (type LIVE + 1 full PAPER night)
                errs[k] = "use the PAPER/LIVE switch (/api/mode)"
                continue
            try:
                old, new = desk.settings.set(k, v, who="app")
                res[k] = {"old": old, "new": new}
            except ValueError as e:
                errs[k] = str(e)
        tc = desk.settings.ticket_check()
        return JSONResponse({"changed": res, "errors": errs, "ticket_warning": tc[1] if tc else None}, status_code=400 if errs and not res else 200)

    @app.post("/api/agents/{name}/pause")
    async def pause(name: str):
        try:
            desk.set_paused(name, True)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        return {"agent": name, "paused": True}

    @app.post("/api/agents/{name}/resume")
    async def resume(name: str):
        desk.set_paused(name, False)
        return {"agent": name, "paused": False}

    @app.post("/api/mode")
    async def mode(req: Request):
        body = await req.json()
        m = str(body.get("mode", "")).upper()
        if m == "LIVE":
            if body.get("confirm") != "LIVE":
                return JSONResponse({"error": "type LIVE to confirm"}, status_code=400)
            if desk.full_paper_nights() < 1:
                return JSONResponse({"error": "LIVE is locked until 1 full PAPER night is in the db"}, status_code=409)
        if m not in ("PAPER", "LIVE"):
            return JSONResponse({"error": "PAPER or LIVE"}, status_code=400)
        old, new = desk.settings.set("desk.mode", m, who="app")
        tc = desk.settings.ticket_check()
        return {"mode": new, "ticket_warning": tc[1] if tc else None}

    @app.get("/api/screen.jpg")
    async def screen():
        f = ROOT / "data" / "screen.jpg"
        if not f.exists() or desk.s("desk.autoclick") == "off":
            return JSONResponse({"error": "no frame", "lane": desk.lane.card() if desk.lane else None}, status_code=404,
                                headers={"Cache-Control": "no-store"})
        return FileResponse(str(f), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/api/lane")
    async def lane():
        return desk.lane.card() if desk.lane else {"mode": "off"}

    @app.get("/api/orders")
    async def orders(before: int | None = None):
        q = "SELECT * FROM orders" + (" WHERE id<?" if before else "") + " ORDER BY id DESC LIMIT 30"
        rows = desk.db.all(q, (before,) if before else ())
        for r in rows:
            r["coin_url"] = links.coin_url(r["mint"], "solana") if r.get("mint") else None
            r.pop("shot_path", None)
        return rows

    @app.post("/api/sell/{mint}")
    async def sell_now(mint: str, req: Request):
        """Coin screen "Sell now": {"pct": 25|50|100, "confirm": true} -> Risk/Executor sells it (PAPER fills at the
        last price; LIVE clicks only when the lane is armed, else a Sell on FOMO push)."""
        b = await req.json()
        if b.get("confirm") is not True:
            return JSONResponse({"error": "confirm required"}, status_code=400)
        pct = float(b.get("pct", 100))
        if pct not in (25, 50, 100):
            return JSONResponse({"error": "pct must be 25, 50 or 100"}, status_code=400)
        pos = [p for p in desk.open_positions() if p["mint"] == mint and p["status"] == "open"]
        if not pos:
            return JSONResponse({"error": "no open position"}, status_code=404)
        p = pos[0]
        price = desk.last_price(mint) or p["last_price"] or p["entry_price"]
        rk = desk.agents.get("risk")
        out = await rk.sell(p, pct, "my sell", price)
        return {"ok": True, "pct": pct, "result": out}

    @app.post("/api/push")
    async def push_sub(req: Request):
        b = await req.json()
        desk.db.exec("INSERT OR REPLACE INTO push_subs(endpoint,p256dh,auth,created_at) VALUES(?,?,?,?)",
                     (b["endpoint"], b["keys"]["p256dh"], b["keys"]["auth"], now()))
        return {"ok": True}

    @app.post("/api/test_push")
    async def test_push():
        ok = await send_test_push(desk)
        return {"ok": ok}

    @app.post("/api/pushes/read")
    async def read_pushes():
        desk.db.exec("UPDATE pushes SET read=1 WHERE read=0")
        return {"ok": True}

    @app.get("/api/stream")
    async def stream(req: Request):
        q = desk.bus.subscribe()

        async def gen():
            try:
                # 4KiB comment so Cloudflare's proxy flushes the first SSE frame
                pad = " " * 2048
                yield "retry: 2000\n:" + (" " * 4096) + "\n\n"
                while True:
                    if await req.is_disconnected():
                        break
                    try:
                        ev, data = await asyncio.wait_for(q.get(), timeout=3)
                        yield f"event: {ev}\ndata: {data}\n:{pad}\n\n"
                    except asyncio.TimeoutError:
                        yield f": ping{pad}\n\n"
            finally:
                desk.bus.unsubscribe(q)
        return StreamingResponse(gen(), media_type="text/event-stream", headers={
            "Cache-Control": "no-store, no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "Pragma": "no-cache",
        })

    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
    app.state.viewed = viewed
    return app


async def send_test_push(desk):
    if not desk.notifier:
        return False
    pre = "PAPER · " if desk.mode() == "PAPER" else ""
    r = desk.db.one("SELECT mint FROM coins WHERE symbol IS NOT NULL ORDER BY first_seen DESC LIMIT 1")
    mint = r["mint"] if r else "4CxjZyMNoF1p6eXHXHv1TWpS2X47CuUmLwtGe18spump"
    name = desk.coin_name(mint) if r else "mihao"
    return await desk.notifier.push(f"{pre}Test push · {name} · this is how every push looks. Tap to open it on FOMO.", mint,
                                    kind="test", buttons=[("Buy on FOMO", links.coin_url(mint, "solana"))])


async def price_writer(desk, app):
    """Every 60s, 1 DexScreener batch for coins pushed/audited/opened tonight that Scanner and Risk don't cover."""
    while True:
        await asyncio.sleep(60)
        try:
            ns = desk.night_start_ts()
            sc = desk.agents.get("scanner")
            covered = set(sc.room) if sc else set()
            covered |= {p["mint"] for p in desk.open_positions()}
            want = {r["mint"] for r in desk.db.all("SELECT DISTINCT mint FROM pushes WHERE ts>=? AND mint IS NOT NULL", (ns,))}
            want |= {r["mint"] for r in desk.db.all("SELECT DISTINCT mint FROM audits WHERE ts>=?", (ns,))}
            want |= {m for m, t in app.state.viewed.items() if t >= ns}
            want -= covered
            if want:
                pairs = await desk.dex.tokens(sorted(want)[:90])
                for m, p in pairs.items():
                    desk.write_price(m, p, "api")
        except Exception as e:
            log.info("price writer error %s", e)


async def planb_writer(desk, out_dir: Path):
    """Plan B: every 15s write state/chart/activity/coin JSON under /d/{DATA_PATH}/ of the publish dir.
    The work is sync (sqlite + files) so it runs in a worker thread and cannot freeze the desk loop."""
    dp = SECRETS.get("DATA_PATH")
    site = out_dir
    data = site / "d" / dp

    def write_once():
        for f in WEB.rglob("*"):
            if f.is_file():
                dst = site / f.relative_to(WEB); dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(f, dst)
        (data / "coin").mkdir(parents=True, exist_ok=True)
        (data / "audit").mkdir(parents=True, exist_ok=True)
        (data / "agents").mkdir(parents=True, exist_ok=True)

        def w(rel, obj):
            p = data / rel; tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(obj, default=str)); tmp.replace(p)
        w("state.json", views.state(desk))
        w("chart.json", {r: views.chart(desk, r) for r in views.RANGES})
        w("activity.json", views.activity(desk, limit=200))
        w("account.json", views.account(desk, "B"))
        w("settings.json", views.settings(desk))
        ns = desk.night_start_ts()
        mints = {r["mint"] for r in desk.db.all("SELECT DISTINCT mint FROM audits WHERE ts>=?", (ns,))}
        mints |= {r["mint"] for r in desk.db.all("SELECT DISTINCT mint FROM positions WHERE opened_at>=? OR status IN ('open','exiting')", (ns,))}
        for m in mints:
            w(f"coin/{m}.json", views.coin(desk, m)); w(f"audit/{m}.json", views.audit(desk, m))
        for a in ("scanner", "auditor", "analyst", "executor", "risk"):
            w(f"agents/{a}.json", views.decisions(desk, a))

    while True:
        try:
            await asyncio.to_thread(write_once)
        except Exception as e:
            log.info("plan B writer error %s", e)
        await asyncio.sleep(15)
