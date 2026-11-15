"""Health-probe a public base URL's /api/rev without sending APP_TOKEN.

Exit 0 if the origin is reachable (HTTP 200, 304, 401, 403). Those codes
mean the tunnel is up; 401 is the desk API refusing a request without the
private token, which is expected. Exit 1 on timeouts, TLS errors, or
edge-is-dead pages.

Uses curl. Sends ngrok-skip-browser-warning so a free-plan interstitial
is not mistaken for success or failure. Never prints secrets.
"""
import re, subprocess, sys

OK = {200, 304, 401, 403}


def main():
    if len(sys.argv) < 2:
        print("usage: probe_public.py https://host", file=sys.stderr)
        return 1
    base = sys.argv[1].strip().rstrip("/")
    if not re.fullmatch(r"https://[a-z0-9.-]+", base, re.I):
        print("refusing unexpected URL shape", file=sys.stderr)
        return 1
    r = subprocess.run(
        [
            "curl", "-sS", "-o", "/dev/null",
            "-w", "%{http_code}",
            "--max-time", "12",
            "-H", "ngrok-skip-browser-warning: 1",
            "-A", "desk-health/1",
            base + "/api/rev",
        ],
        capture_output=True, text=True,
    )
    try:
        code = int((r.stdout or "0").strip() or "0")
    except ValueError:
        code = 0
    if r.returncode == 0 and code in OK:
        print(f"ok {code}")
        return 0
    err = (r.stderr or "").strip().replace("\n", " ")[:160]
    print(f"fail http={code} curl_rc={r.returncode} {err}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
