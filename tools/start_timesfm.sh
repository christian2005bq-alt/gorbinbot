#!/usr/bin/env bash
# Brain's TimesFM sidecar on 127.0.0.1:8795 (own venv, CPU). Weights cache: /workspace/ext/hf
if curl -s -m 2 http://127.0.0.1:8795/health | grep -q timesfm; then echo "timesfm already up"; exit 0; fi
export HF_HOME=/workspace/ext/hf HF_HUB_OFFLINE=1
setsid nohup /workspace/ext/tfm-venv/bin/python /workspace/desk/sidecars/timesfm_server.py >> /workspace/desk/logs/timesfm.log 2>&1 < /dev/null &
echo $! > /workspace/desk/sidecars/timesfm.pid
