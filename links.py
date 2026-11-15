"""THE ONLY place FOMO URLs are built (STEP 6). Never drop the referral code, never shorten or wrap."""
import logging
import re

log = logging.getLogger("links")

CHAIN_ID = {"solana": 1399811149, "robinhood": 4663, "base": 8453, "bnb": 56}
DEFAULT_REF = "gorbindx"
_REF_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")
_ref = DEFAULT_REF


def set_ref_code(code):
    """Set the referral code used by every FOMO URL. Invalid values fall back to DEFAULT_REF."""
    global _ref
    c = str(code or "").strip().lstrip("@")
    _ref = c if _REF_RE.fullmatch(c) else DEFAULT_REF
    return _ref


def ref_code():
    return _ref


def signup_url(ref=None):
    return f"https://fomo.family/r/{ref or _ref}"


def coin_url(address, chain="solana", ref=None):
    r = ref or _ref
    if chain not in CHAIN_ID:
        log.warning("coin_url: unknown chain %r for %s -> SIGNUP_URL", chain, address)
        return signup_url(r)
    return f"https://fomo.family/coin?address={address}&chainId={CHAIN_ID[chain]}&r={r}&source=share_link"


def profile_url(handle, ref=None):
    h = handle.lstrip("@")
    return f"https://fomo.family/profile/{h}?source=share_link&r={ref or _ref}"


def __getattr__(name):
    if name == "SIGNUP_URL":
        return signup_url()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---- read-only helpers for browser.py / verify.py (so no FOMO host is written outside this file)
API_BASE = "https://prod-api.fomo.family"
_COIN_PAGE = re.compile(r"https://fomo\.family/coin\?address=([1-9A-HJ-NP-Za-km-z]{32,44})&chainId=\d+&r=[A-Za-z0-9_]{1,32}&source=share_link")
_PROFILE_PAGE = re.compile(r"https://fomo\.family/profile/[A-Za-z0-9_]{1,32}\?source=share_link&r=[A-Za-z0-9_]{1,32}")


def is_desk_page(url):
    """True only for a coin page exactly as coin_url() builds it, or a profile page as profile_url() builds it."""
    u = url or ""
    m = _COIN_PAGE.fullmatch(u)
    if m:
        return u == coin_url(m.group(1), "solana")
    return bool(_PROFILE_PAGE.fullmatch(u))


def on_coin_or_profile(url):
    """Loose check for the Live frames: the tab is on a FOMO coin or profile page (any query)."""
    u = url or ""
    return u.startswith("https://fomo.family/coin") or u.startswith("https://fomo.family/profile")


def is_api(url):
    return (url or "").startswith(API_BASE)
