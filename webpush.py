"""Web Push with VAPID: the same pushes to subscribed devices (STEP 8 PUSH). 410 Gone deletes the sub."""
import asyncio, json
from common import SECRETS, now, get_logger

log = get_logger("webpush")


def public_key():
    return SECRETS.get("VAPID_PUBLIC_KEY", "")


def _send(sub, payload):
    from pywebpush import webpush, WebPushException
    try:
        webpush(subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                data=json.dumps(payload), vapid_private_key=SECRETS.get("VAPID_PRIVATE_KEY"),
                vapid_claims={"sub": "mailto:desk@localhost"}, timeout=10)
        return 201
    except WebPushException as e:
        return getattr(e.response, "status_code", 0) or 0
    except Exception:
        return 0


async def send_all(db, title, body, url):
    subs = db.all("SELECT * FROM push_subs")
    ok = 0
    for s in subs:
        code = await asyncio.to_thread(_send, s, {"title": title, "body": body, "url": url})
        if code in (404, 410):
            db.exec("DELETE FROM push_subs WHERE endpoint=?", (s["endpoint"],))
        elif 200 <= code < 300:
            ok += 1
        else:
            log.info("webpush status %s", code)
    return ok, len(subs)
