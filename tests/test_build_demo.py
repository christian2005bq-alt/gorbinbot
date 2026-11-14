import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_build_demo_is_public_read_only_paper(tmp_path):
    site = tmp_path / "site"
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "build_demo.py"), str(site)],
        check=True,
        capture_output=True,
        text=True,
    )

    data = site / "d" / "demo"
    state = json.loads((data / "state.json").read_text())
    account = json.loads((data / "account.json").read_text())
    activity = json.loads((data / "activity.json").read_text())
    manifest = json.loads((site / "manifest.json").read_text())
    page = (site / "index.html").read_text()
    app = (site / "app.js").read_text()

    assert state["mode"] == "PAPER"
    assert state["balance"] == state["start_balance"] == 200
    assert activity["rows"] == []
    assert account["plan"] == "B"
    assert account["telegram"] == "not connected"
    assert account["webpush"] is False
    assert manifest["start_url"] == "./index.html"
    assert '<html lang="en" data-demo="true">' in page
    assert "const DEMO = document.documentElement.dataset.demo === 'true';" in app
    assert "const DP = DEMO ? 'demo' : localStorage.getItem('desk_d');" in app
    assert "PUBLIC DEMO | PAPER | SYNTHETIC DATA | READ-ONLY" in page
