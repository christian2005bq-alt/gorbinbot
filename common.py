"""Secrets, logging (with redaction), small helpers."""
import logging, logging.handlers, os, re, time, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_PATH = Path(os.environ.get("DESK_ENV", "/home/box/secrets/fomo-desk/.env"))
LOGS = Path(os.environ.get("DESK_LOGS", ROOT / "logs"))
LOGS.mkdir(exist_ok=True)
(LOGS / "raw").mkdir(exist_ok=True)
SECRET_KEYS = ("TYPESAFE_API_KEY", "TG_TOKEN", "VAPID_PRIVATE_KEY", "APP_TOKEN", "DATA_PATH", "HELIUS_RPC_URL")


def load_secrets() -> dict:
    out = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    for k in list(out):
        if os.environ.get("DESK_TEST") and k in ("TG_TOKEN",):
            pass
    return out


SECRETS = load_secrets()


_APIKEY_RE = re.compile(r"(?i)(api-key=)([^&\s'\"]+)")
_BOTTOK_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]{20,}")


def mask_secret(s: str) -> str:
    """Strip secret values and api-key= query params so they never hit logs, proofs, or API views."""
    if not s:
        return s
    for v in getattr(_REDACT, "vals", []):
        if v and v in s:
            s = s.replace(v, "[REDACTED]")
    s = _APIKEY_RE.sub(r"\1[REDACTED]", s)
    s = _BOTTOK_RE.sub("bot[REDACTED]", s)
    return s


class Redact(logging.Filter):
    def __init__(self):
        super().__init__()
        self.vals = []
        for k, v in SECRETS.items():
            if not v or len(v) <= 8:
                continue
            if k in SECRET_KEYS:
                self.vals.append(v)
            # also redact just the api-key token if a secret is a URL
            m = _APIKEY_RE.search(v)
            if m and m.group(2) not in self.vals:
                self.vals.append(m.group(2))

    def filter(self, record):
        msg = mask_secret(record.getMessage())
        if msg != record.getMessage():
            record.msg, record.args = msg, ()
        return True


_REDACT = Redact()


def get_logger(name: str) -> logging.Logger:
    lg = logging.getLogger(name)
    if not lg.handlers:
        h = logging.handlers.TimedRotatingFileHandler(LOGS / f"{name}.log", when="midnight", backupCount=14)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        h.addFilter(_REDACT)
        lg.addHandler(h)
        lg.setLevel(logging.INFO)
        lg.propagate = False
    return lg


def quiet_libs():
    # httpx logs full request URLs at INFO (the Telegram URL carries the token): never let it.
    for n in ("httpx", "httpcore", "websockets", "uvicorn.access"):
        logging.getLogger(n).setLevel(logging.WARNING)
    root = logging.getLogger()
    for h in root.handlers:
        h.addFilter(_REDACT)


def now() -> float:
    return time.time()


def iso(ts: float | None = None) -> str:
    return dt.datetime.fromtimestamp(ts if ts is not None else time.time(), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_usd(x, d=2):
    if x is None:
        return "n/a"
    return f"${x:,.{d}f}"


def fmt_k(x):
    if x is None:
        return "n/a"
    if abs(x) >= 1e6:
        return f"${x/1e6:.1f}M"
    if abs(x) >= 1e3:
        return f"${x/1e3:.1f}K"
    return f"${x:.0f}"


def short(addr: str) -> str:
    return f"{addr[:4]}...{addr[-3:]}" if addr and len(addr) > 10 else (addr or "")
