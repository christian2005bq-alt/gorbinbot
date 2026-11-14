"""STEP 13.7: secret values must appear nowhere: web/, logs/, the repo, API responses, plan B JSON files, Pages/reports.
APP_TOKEN too. /api/state 200 with token, 401 without. Plan B: DATA_PATH not in the repo."""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from common import SECRETS, ROOT

KEYS = ["TYPESAFE_API_KEY", "TG_TOKEN", "VAPID_PRIVATE_KEY", "APP_TOKEN"]


def scan_tree(base, vals, skip=(".venv", "__pycache__", ".pytest_cache")):
    hits = []
    for p in base.rglob("*"):
        if any(s in p.parts for s in skip) or not p.is_file():
            continue
        try:
            b = p.read_bytes()
        except Exception:
            continue
        for k, v in vals.items():
            if v.encode() in b or v in str(p):
                hits.append(f"{k} in {p.relative_to(base)}")
    return hits


if __name__ == "__main__":
    vals = {k: SECRETS[k] for k in KEYS if SECRETS.get(k)}
    fails = []
    trees = {"repo (desk/ incl. web/, logs/, reports/, status/, proofs/, db)": ROOT}
    for name, base in trees.items():
        h = [x for x in scan_tree(base, vals) if not x.startswith("x")]
        print(f"grep {name}: {'empty' if not h else h}")
        fails += h
    # repo must not contain DATA_PATH (the plan B publish dir out/site holds it only as the folder name)
    dp = SECRETS.get("DATA_PATH")
    h = [x for x in scan_tree(ROOT, {"DATA_PATH": dp}, skip=(".venv", "__pycache__", ".pytest_cache", "out"))]
    print(f"grep repo for DATA_PATH (excluding the out/ publish dir): {'empty' if not h else h}")
    fails += h
    h = [x for x in scan_tree(ROOT / "out", {k: v for k, v in vals.items()})]
    print(f"grep plan B JSON files (out/site): {'empty' if not h else h}")
    fails += h
    tok = SECRETS["APP_TOKEN"]
    base = "http://127.0.0.1:8787/api"
    H = {"Authorization": "Bearer " + tok}
    with httpx.Client(timeout=30) as c:
        for path in ["/state", "/chart?range=ALL", "/activity", "/account", "/settings", "/agents/scanner/decisions"]:
            r = c.get(base + path, headers=H)
            leak = [k for k, v in vals.items() if v in r.text]
            print(f"GET /api{path}: {r.status_code}, secrets in body: {leak or 'none'}")
            fails += leak
        r1, r2, r3 = c.get(base + "/state", headers=H), c.get(base + "/state"), c.get(base + "/state", headers={"Authorization": "Bearer wrong"})
        print(f"/api/state with token {r1.status_code} · without {r2.status_code} · wrong token {r3.status_code}")
        if (r1.status_code, r2.status_code, r3.status_code) != (200, 401, 401):
            fails.append("auth")
    env_mode = oct(os.stat("/home/box/secrets/fomo-desk/.env").st_mode & 0o777)
    print(f".env mode {env_mode}")
    print("test_secrets:", "PASS" if not fails else f"FAIL {fails}")
    sys.exit(1 if fails else 0)
