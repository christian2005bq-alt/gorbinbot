"""TimesFM 2.5 (google-research/timesfm, 200M, PyTorch, CPU) forecast sidecar for Brain.

Runs in its own venv (/workspace/ext/tfm-venv: torch CPU + timesfm) so the desk process stays light.
Listens on 127.0.0.1:8795 ONLY. POST /forecast {"series": [closes...], "horizon": 15}
-> {"point": [...], "q10": [...], "q90": [...], "ms": n}. GET /health -> {"ok": true}.
Measured on this box: load+compile ~6 s, one forecast ~0.1-0.35 s on 4 threads, ~2.2 GB RAM."""
import json, time, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np, torch, timesfm

torch.set_num_threads(4)
MODEL = timesfm.TimesFM_2p5_200M_torch.from_pretrained("google/timesfm-2.5-200m-pytorch")
MODEL.compile(timesfm.ForecastConfig(max_context=256, max_horizon=64, normalize_inputs=True,
                                     use_continuous_quantile_head=True))
LOCK = threading.Lock()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        self._send(200, {"ok": True, "model": "timesfm-2.5-200m"}) if self.path == "/health" else self._send(404, {})

    def do_POST(self):
        if self.path != "/forecast":
            return self._send(404, {})
        try:
            j = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            s = [float(x) for x in j.get("series") or []][-256:]
            h = max(1, min(64, int(j.get("horizon") or 15)))
            if len(s) < 16:
                return self._send(400, {"error": "need >= 16 points"})
            t = time.time()
            with LOCK:
                pt, qt = MODEL.forecast(horizon=h, inputs=[np.array(s)])
            # quantile head: index 0 = mean, 1..9 = q10..q90
            self._send(200, {"point": pt[0].tolist(), "q10": qt[0, :, 1].tolist(), "q90": qt[0, :, 9].tolist(),
                             "ms": round(1000 * (time.time() - t))})
        except Exception as e:
            self._send(500, {"error": type(e).__name__})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8795), H).serve_forever()
