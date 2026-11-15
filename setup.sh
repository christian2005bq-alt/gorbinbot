#!/usr/bin/env bash
# Reinstall the desk's Python packages (box updates can drop them). Playwright drives the system google-chrome over CDP,
# so no browser download is needed.
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt

# savipww's 5 repos (optional sidecars, localhost only). Re-run safely.
mkdir -p /workspace/ext && cd /workspace/ext
[ -d trade-journal ] || git clone --depth 1 https://github.com/LuxAlgo/trade-journal
(cd trade-journal && npx -y pnpm@11.0.8 install --frozen-lockfile && NEXT_TELEMETRY_DISABLED=1 npx -y pnpm@11.0.8 build)
[ -d tfm-venv ] || /workspace/desk/.venv/bin/python -m venv tfm-venv
tfm-venv/bin/pip -q install --index-url https://download.pytorch.org/whl/cpu torch && tfm-venv/bin/pip -q install "timesfm[torch]"
HF_HOME=/workspace/ext/hf tfm-venv/bin/python -c "import timesfm; timesfm.TimesFM_2p5_200M_torch.from_pretrained('google/timesfm-2.5-200m-pytorch')"
