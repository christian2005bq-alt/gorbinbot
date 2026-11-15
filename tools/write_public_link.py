"""Write /home/box/secrets/fomo-desk/public_app_link.txt (mode 600) from a public
base URL plus APP_TOKEN. Never prints the token. Exits 0 if the link is new or
changed, 2 if unchanged, 1 on error."""
import os, re, sys
from pathlib import Path

ENV = Path("/home/box/secrets/fomo-desk/.env")
OUT = Path("/home/box/secrets/fomo-desk/public_app_link.txt")


def main():
    if len(sys.argv) < 2:
        print("usage: write_public_link.py https://....trycloudflare.com", file=sys.stderr)
        return 1
    base = sys.argv[1].strip().rstrip("/")
    if not re.fullmatch(r"https://[a-z0-9.-]+", base, re.I):
        print("refusing unexpected URL shape", file=sys.stderr)
        return 1
    token = re.search(r"^APP_TOKEN=(.*)$", ENV.read_text(), re.M)
    if not token:
        print("APP_TOKEN missing", file=sys.stderr)
        return 1
    tok = token.group(1).strip().strip('"').strip("'")
    link = f"{base}/#t={tok}"
    old = OUT.read_text() if OUT.exists() else ""
    OUT.write_text(link + "\n")
    os.chmod(OUT, 0o600)
    if old.strip() == link:
        print(f"unchanged {base}")
        return 2
    print(f"wrote {base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
