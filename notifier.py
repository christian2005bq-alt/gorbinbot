"""Fan-out of every push: Telegram (owner only) + web push. Buttons/URLs come only from links.py."""
import asyncio, json
import links
import webpush
from common import now, get_logger

log = get_logger("notifier")


class Notifier:
    def __init__(self, desk, telegram=None):
        self.d = desk
        self.tg = telegram

    async def push(self, text, mint, kind="info", buttons=None):
        """buttons: list of (label, url_or_callback). URL buttons must be links.py strings. True if any channel delivered."""
        url = None
        if buttons:
            for label, target in buttons:
                if target.startswith("https://"):
                    url = target
        elif buttons is None and mint:
            url = links.coin_url(mint, "solana")
            buttons = [("Buy on FOMO", url)]
        ok_any = False
        if self.tg and self.d.s("desk.notifier") in ("telegram",):
            ok = False
            for i in range(3):
                ok = await self.tg.send(text, buttons or [])
                if ok:
                    break
                await asyncio.sleep(2)
            self.d.db.exec("INSERT INTO pushes(ts,mint,kind,text,link,channel,ok) VALUES(?,?,?,?,?,?,?)", (now(), mint, kind, text, url, "telegram", int(ok)))
            ok_any = ok_any or ok
        try:
            n_ok, n = await webpush.send_all(self.d.db, "Grok Bot · now", text, url or links.SIGNUP_URL)
            if n:
                self.d.db.exec("INSERT INTO pushes(ts,mint,kind,text,link,channel,ok) VALUES(?,?,?,?,?,?,?)", (now(), mint, kind, text, url, "webpush", int(n_ok > 0)))
                ok_any = ok_any or n_ok > 0
        except Exception as e:
            log.info("webpush error %s", type(e).__name__)
        self.d.bus.emit("push", {"text": text, "mint": mint, "link": url})
        log.info("push kind=%s ok=%s link=%s text=%r", kind, ok_any, url, text)
        return ok_any
