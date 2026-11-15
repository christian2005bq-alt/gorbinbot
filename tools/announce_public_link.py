"""Telegram the owner the current HTTPS private app link as an inline
URL button. The token is read from the 0600 link file, never printed,
never passed on the command line. A plain-text URL loses the #t=
fragment on the owner's phone, so the URL lives only on the button.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import desk_cli  # noqa: E402

LINK = Path("/home/box/secrets/fomo-desk/public_app_link.txt")


def main():
    if not LINK.exists():
        print("no public_app_link.txt", file=sys.stderr)
        return 1
    url = LINK.read_text().strip().splitlines()[-1].strip()
    if not url.startswith("https://") or "#t=" not in url:
        print("public_app_link.txt is not a private https link", file=sys.stderr)
        return 1
    text = (
        "Ya está el panel en vivo. Ábrelo con el botón de abajo "
        "(así el teléfono no pierde la clave; si copias el link a mano, a veces se corta).\n\n"
        "La primera vez puede salir una página de aviso de ngrok: toca Visit Site y entra el panel. "
        "Después la clave se guarda en el teléfono.\n\n"
        "Si el link llegara a cambiar, te mando el nuevo aquí."
    )
    ok = desk_cli.send(text, buttons=[("Abrir el panel", url)])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
