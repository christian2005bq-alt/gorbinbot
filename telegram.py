"""Telegram: long polling, owner lock, pushes with FOMO buttons, commands (STEP 9)."""
import asyncio, json, re, datetime as dt
import links
from common import SECRETS, now, get_logger, fmt_usd, mask_secret
from config import NEG_PCT, DEFAULTS

log = get_logger("telegram")
HELP = ("Commands:\n"
        "buy X · sell X · why X · pause Scanner · resume Scanner · set stop to -8% · stack 1240 · "
        "status · paper | live · invite · report\nX = name, symbol or mint.")


class Telegram:
    def __init__(self, desk):
        self.d = desk
        self.token = SECRETS.get("TG_TOKEN")
        self.base = f"https://api.telegram.org/bot{self.token}"
        self.awaiting_live = False

    @property
    def owner(self):
        v = self.d.db.kv_get("owner_chat_id")
        return int(v) if v else None

    async def api(self, method, **payload):
        try:
            r = await self.d.client.post(f"{self.base}/{method}", json=payload, timeout=payload.get("timeout", 0) + 20)
            j = r.json()
            if not j.get("ok"):
                log.info("%s failed: %s", method, j.get("description"))
            return j
        except Exception as e:
            log.info("%s error %s", method, type(e).__name__)
            return {"ok": False}

    def keyboard(self, buttons):
        row = []
        for label, target in buttons:
            if target.startswith("https://"):
                row.append({"text": label, "url": target})       # exact links.py string, never wrapped
            else:
                row.append({"text": label, "callback_data": target})
        return {"inline_keyboard": [row]} if row else None

    async def send(self, text, buttons=(), chat_id=None):
        chat = chat_id or self.owner
        if not chat or not self.token:
            return False
        p = {"chat_id": chat, "text": text, "disable_web_page_preview": True}
        kb = self.keyboard(buttons)
        if kb:
            p["reply_markup"] = kb
        j = await self.api("sendMessage", **p)
        return bool(j.get("ok"))

    async def poll(self):
        offset = None
        while True:
            self.d.heartbeat("telegram")
            params = {"timeout": 25, "allowed_updates": ["message", "callback_query"]}
            if offset is not None:
                params["offset"] = offset
            j = await self.api("getUpdates", **params)
            if not j.get("ok"):
                await asyncio.sleep(5); continue
            for u in j.get("result", []):
                offset = u["update_id"] + 1
                try:
                    await self.handle(u)
                except Exception as e:
                    log.exception("handle error %s", e)

    async def handle(self, u):
        if "callback_query" in u:
            cq = u["callback_query"]
            chat = cq.get("message", {}).get("chat", {}).get("id")
            if chat != self.owner:
                return
            await self.api("answerCallbackQuery", callback_query_id=cq["id"])
            return await self.callback(cq.get("data", ""))
        m = u.get("message") or {}
        chat = m.get("chat", {}).get("id")
        text = (m.get("text") or "").strip()
        if self.owner is None:
            if text.startswith("/start") and m.get("chat", {}).get("type") == "private":
                self.d.db.kv_set("owner_chat_id", chat)
                log.info("owner locked to chat %s", chat)
                self._last_help = now()
                await self.send("Grok Bot desk connected. You are the owner of this bot.\n" + HELP)
            return
        if chat != self.owner:
            return                                  # ignore everyone else
        reply = await self.command(text)
        if reply:
            msg, buttons = reply if isinstance(reply, tuple) else (reply, [])
            await self.send(msg, buttons)

    async def callback(self, data):
        kind, _, arg = data.partition(":")
        ex, rk = self.d.agents.get("executor"), self.d.agents.get("risk")
        if kind == "bought" and ex:
            sig = self.d.db.one("SELECT * FROM signals WHERE id=?", (int(arg),))
            if sig and sig["mode"] == "LIVE":
                ex.fill(int(arg))
                await self.send(f"Bought {self.d.coin_name(sig['mint'])} logged. Risk is guarding it.", [("Sell on FOMO", links.coin_url(sig["mint"], "solana"))])
        elif kind == "skip" and ex:
            ex.skip(int(arg))
            await self.send("Skipped for tonight.")
        elif kind == "sold" and rk:
            rk.sold(int(arg))
            await self.send("Sold logged, position closed.")

    # ---- commands (also used by the Grok Bot app path through the API)
    async def command(self, text):
        t = text.strip().lstrip("/")
        low = t.lower()
        if low in ("start", "help", ""):
            if low == "start" and now() - getattr(self, "_last_help", 0) < 120:
                return None
            self._last_help = now()
            return HELP
        if t == "LIVE" and self.awaiting_live:
            self.awaiting_live = False
            return self.switch_mode("LIVE", confirm="LIVE")
        m = re.match(r"^(buy|sell|why)\s+(.+)$", t, re.I)
        if m:
            return await getattr(self, "cmd_" + m.group(1).lower())(m.group(2).strip())
        m = re.match(r"^(pause|resume)\s+(\w+)$", t, re.I)
        if m:
            ag = m.group(2).lower()
            if ag not in ("scanner", "auditor", "analyst", "brain", "executor", "risk"):
                return "Agents: Scanner, Auditor, Analyst, Executor, Risk."
            try:
                self.d.set_paused(ag, m.group(1).lower() == "pause")
            except ValueError as e:
                return str(e)
            return f"{ag.capitalize()} {'paused' if m.group(1).lower() == 'pause' else 'running'}."
        m = re.match(r"^set\s+(.+?)\s+(?:to|=)\s+(.+)$", t, re.I)
        if m:
            return self.cmd_set(m.group(1), m.group(2))
        m = re.match(r"^stack\s+\$?([\d,.]+)$", t, re.I)
        if m:
            return self.cmd_set("desk.stack", m.group(1))
        if low == "status":
            return self.cmd_status()
        if low == "paper":
            return self.switch_mode("PAPER")
        if low == "live":
            self.awaiting_live = True
            return "Type LIVE to confirm. Money only moves when you tap Buy on FOMO and buy inside FOMO."
        if low == "invite":
            return f"New to FOMO? {links.SIGNUP_URL}", [("Sign up on FOMO", links.SIGNUP_URL)]
        if low == "report":
            u = self.d.db.kv_get("last_report_url")
            return f"Last morning Page: {u}" if u else "No morning Page yet. The first one lands at " + self.d.s("desk.report_time") + "."
        return HELP

    def switch_mode(self, mode, confirm=None):
        if mode == "LIVE":
            if confirm != "LIVE":
                return "LIVE needs you to type LIVE."
            if self.d.full_paper_nights() < 1:
                return "LIVE is locked until 1 full PAPER night is in the db."
        old, new = self.d.settings.set("desk.mode", mode, who="telegram")
        msg = f"mode {old} -> {new}"
        tc = self.d.settings.ticket_check()
        if tc:
            msg += "\n" + tc[1]
        return msg

    def cmd_set(self, name, value):
        key = self.d.settings.resolve(name)
        if not key:
            return f"Unknown setting '{name}'."
        try:
            old, new = self.d.settings.set(key, value, who="telegram")
        except ValueError as e:
            return f"Refused: {e}"
        label = key.split(".")[-1].replace("_pct", "").replace("_", " ")
        if key in NEG_PCT:
            msg = f"{label} -{old:g}% -> -{new:g}%"
        else:
            msg = f"{label} {mask_secret(str(old))} -> {mask_secret(str(new))}"
        if key in ("desk.stack", "executor.stack_pct", "executor.below_min"):
            tc = self.d.settings.ticket_check()
            if tc:
                msg += "\n" + tc[1]
        return msg

    def resolve_coin(self, x):
        rows = self.d.db.find_coins(x)
        if not rows:
            if re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", x):
                return [{"mint": x, "name": None, "symbol": None}], None
            return None, f"I don't know {x}. Send me the mint."
        if len(rows) > 1:
            lines = [f"{r['symbol'] or r['name']} · {r['mint']}\n{links.coin_url(r['mint'], 'solana')}" for r in rows]
            return None, "Which one?\n" + "\n".join(lines)
        return rows, None

    async def cmd_buy(self, x):
        rows, err = self.resolve_coin(x)
        if err:
            return err
        mint = rows[0]["mint"]; url = links.coin_url(mint, "solana")
        push = self.d.db.one("SELECT * FROM pushes WHERE mint=? AND kind='buy' AND ts>=? ORDER BY ts DESC LIMIT 1", (mint, self.d.night_start_ts()))
        if push:
            sig = self.d.db.one("SELECT id FROM signals WHERE mint=? ORDER BY ts DESC LIMIT 1", (mint,))
            return push["text"], [("Buy on FOMO", url), ("Bought", f"bought:{sig['id']}"), ("Skip", f"skip:{sig['id']}")]
        aud = self.d.agents.get("auditor")
        coin = self.d.db.coin(mint) or {}
        out = await aud.audit({"mint": mint, "pool": coin.get("pool")}, forward=False)
        lines = [f"{l['n']} {l['name']}: {'✓' if l['pass'] else ('✗' if l['pass'] is False else '·')} {l['value']}" for l in out["layers"]]
        head = f"{self.d.coin_name(mint)} · {'Cleared 8/8' if out['passed'] else 'Rejected · ' + str(out['reason'])}"
        return head + "\n" + "\n".join(lines) + "\nnot sized, not on the desk\n" + url, [("Buy on FOMO", url)]

    async def cmd_sell(self, x):
        rows, err = self.resolve_coin(x)
        if err:
            return err
        mint = rows[0]["mint"]; url = links.coin_url(mint, "solana")
        p = self.d.db.one("SELECT * FROM positions WHERE mint=? AND status IN ('open','exiting')", (mint,))
        if not p:
            return f"No open {self.d.coin_name(mint)} position.\n{url}", [("Open on FOMO", url)]
        return f"Sell {self.d.coin_name(mint)} · ${p['size_usd']:.2f} in", [("Sell on FOMO", url), ("Sold", f"sold:{p['id']}")]

    async def cmd_why(self, x):
        rows, err = self.resolve_coin(x)
        if err:
            return err
        mint = rows[0]["mint"]; url = links.coin_url(mint, "solana")
        d = self.d.db.one("SELECT * FROM decisions WHERE mint=? AND verdict NOT IN ('pass','bought') ORDER BY ts DESC LIMIT 1", (mint,))
        if not d:
            d = self.d.db.one("SELECT * FROM decisions WHERE mint=? ORDER BY ts DESC LIMIT 1", (mint,))
        if not d:
            return f"{self.d.coin_name(mint)} hasn't reached the desk tonight.\n{url}", [("Open on FOMO", url)]
        t = dt.datetime.fromtimestamp(d["ts"]).strftime("%H:%M")
        return f"{self.d.coin_name(mint)}: {d['agent'].capitalize()} · {d['verdict']} · {d['reason']} · {t}\n{url}", [("Open on FOMO", url)]

    def cmd_status(self):
        mode = self.d.mode()
        lines = [f"{mode} · balance {fmt_usd(self.d.balance())}"]
        btns = []
        for p in self.d.open_positions():
            url = links.coin_url(p["mint"], "solana")
            lp = p["last_price"] or p["entry_price"]
            lines.append(f"{self.d.coin_name(p['mint'])} · ${p['size_usd']:.2f} in · {100*(lp/p['entry_price']-1):+.1f}% · stop -{p['stop_pct']:g}%\n{url}")
            btns.append((f"Sell {self.d.coin_name(p['mint'])} on FOMO", url))
        if len(lines) == 1:
            lines.append("No open positions.")
        return "\n".join(lines), btns[:3]
