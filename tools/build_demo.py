#!/usr/bin/env python3
"""Build a public, read-only demo from a fresh synthetic PAPER database."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
AGENTS = ("scanner", "auditor", "analyst", "executor", "risk")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, default=str, indent=2) + "\n")


def build(output):
    if not WEB.is_dir():
        raise RuntimeError(f"Web assets not found: {WEB}")

    with tempfile.TemporaryDirectory(prefix="gorbinbot-demo-") as tmp:
        temp = Path(tmp)
        os.environ["DESK_ENV"] = str(temp / "no-secrets.env")
        os.environ["DESK_LOGS"] = str(temp / "logs")
        os.environ["DESK_STATUS"] = str(temp / "status")
        sys.path.insert(0, str(ROOT))

        from db import DB
        from desk import Desk
        import views

        desk = Desk(DB(temp / "demo.db"))
        try:
            if desk.mode() != "PAPER":
                raise RuntimeError("Refusing to build a demo unless the database is PAPER")
            desk.start_night()

            shutil.copytree(WEB, output, dirs_exist_ok=True)
            data = output / "d" / "demo"
            write_json(data / "state.json", views.state(desk))
            write_json(data / "chart.json", {r: views.chart(desk, r) for r in views.RANGES})
            write_json(data / "activity.json", views.activity(desk, limit=200))
            write_json(data / "account.json", views.account(desk, "B"))
            write_json(data / "settings.json", views.settings(desk))
            for agent in AGENTS:
                write_json(data / "agents" / f"{agent}.json", views.decisions(desk, agent))

            index = output / "index.html"
            html = index.read_text()
            if '<html lang="en">' not in html or '<main id="view">' not in html or "</head>" not in html:
                raise RuntimeError("Unexpected web/index.html structure")
            html = html.replace('<html lang="en">', '<html lang="en" data-demo="true">', 1)
            html = html.replace(
                "</head>",
                '  <link rel="stylesheet" href="demo.css">\n</head>',
                1,
            )
            html = html.replace(
                '<main id="view">',
                '<div class="demo-banner" role="note">PUBLIC DEMO | PAPER | SYNTHETIC DATA | READ-ONLY</div>\n'
                '<main id="view">',
                1,
            )
            index.write_text(html)

            app = output / "app.js"
            script = app.read_text()
            auth = "const TOKEN = localStorage.getItem('desk_t'), DP = localStorage.getItem('desk_d');"
            if auth not in script:
                raise RuntimeError("Unexpected web/app.js authentication structure")
            script = script.replace(
                auth,
                "const DEMO = document.documentElement.dataset.demo === 'true';\n"
                "  const TOKEN = DEMO ? null : localStorage.getItem('desk_t');\n"
                "  const DP = DEMO ? 'demo' : localStorage.getItem('desk_d');",
                1,
            )
            app.write_text(script)

            manifest = output / "manifest.json"
            manifest_data = json.loads(manifest.read_text())
            manifest_data["start_url"] = "./index.html"
            manifest.write_text(json.dumps(manifest_data, indent=2) + "\n")
        finally:
            desk.db.conn.close()
            import asyncio

            asyncio.run(desk.client.aclose())


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tools/build_demo.py OUTPUT_DIRECTORY")
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    build(output)
    print(f"Built public PAPER demo in {output}")


if __name__ == "__main__":
    main()
