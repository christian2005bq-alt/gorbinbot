"""Create or update /home/box/secrets/fomo-desk/ngrok.yml (mode 600).

Reads NGROK_AUTHTOKEN from the process environment or the desk .env.
Never prints the token. Exits 0 on success, 1 if no token is available
and no usable config already exists.
"""
import os, re, sys
from pathlib import Path

CFG = Path("/home/box/secrets/fomo-desk/ngrok.yml")
ENV = Path("/home/box/secrets/fomo-desk/.env")


def token_from_envfile():
    if not ENV.exists():
        return None
    m = re.search(r"^NGROK_AUTHTOKEN=(.*)$", ENV.read_text(), re.M)
    if not m:
        return None
    return m.group(1).strip().strip('"').strip("'") or None


def main():
    token = os.environ.get("NGROK_AUTHTOKEN") or token_from_envfile()
    if not token:
        if CFG.exists() and CFG.stat().st_size > 0:
            print("using existing ngrok config (no token in env)")
            return 0
        print("NGROK_AUTHTOKEN missing", file=sys.stderr)
        return 1
    safe = "'" + token.replace("'", "''") + "'"
    CFG.parent.mkdir(parents=True, exist_ok=True)
    CFG.write_text(
        "version: \"3\"\n"
        "agent:\n"
        f"  authtoken: {safe}\n"
        "  web_addr: 127.0.0.1:4040\n"
        "  crl_noverify: true\n"
    )
    os.chmod(CFG, 0o600)
    print("ngrok config ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
