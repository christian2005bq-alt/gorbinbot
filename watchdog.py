"""In-process event-loop watchdog.

A coroutine ticks a monotonic clock every 2s. A daemon thread restarts the desk
if that tick goes stale (the loop is blocked). Wall-clock jumps (VM pause/resume)
refresh heartbeats so the hourly health check does not kill a healthy process.
"""
import asyncio, os, sys, time, threading, traceback, subprocess
from common import ROOT, get_logger, mask_secret

log = get_logger("watchdog")
STALE_S = 60
CLOCK_JUMP_S = 15
AGENTS = ("main", "scanner", "auditor", "analyst", "brain", "executor", "risk", "telegram")


class Watchdog:
    def __init__(self, desk, stale_s=STALE_S):
        self.d = desk
        self.stale_s = stale_s
        self._mono = time.monotonic()
        self._wall = time.time()
        self._stop = threading.Event()
        self._restarting = False

    def tick(self):
        self._mono = time.monotonic()

    async def loop(self):
        while True:
            self.tick()
            wall = time.time()
            jumped = wall - self._wall
            self._wall = wall
            if jumped > CLOCK_JUMP_S:
                log.info("wall clock jumped %.0fs; refreshing heartbeats and websocket", jumped)
                try:   # the box was frozen by its host: record it so the app and the morning report show it
                    self.d.db.exec("INSERT INTO events(ts,kind,detail) VALUES(?,?,?)", (wall, "box_sleep", f"{jumped:.0f}"))
                except Exception:
                    pass
                for a in AGENTS:
                    try:
                        self.d.heartbeat(a)
                    except Exception:
                        pass
                sc = self.d.agents.get("scanner")
                if sc and hasattr(sc, "kick_ws"):
                    try:
                        await sc.kick_ws()
                    except Exception as e:
                        log.info("kick_ws failed: %s", type(e).__name__)
            await asyncio.sleep(2)

    def start_thread(self):
        threading.Thread(target=self._thread, name="desk-watchdog", daemon=True).start()

    def _thread(self):
        while not self._stop.wait(5):
            lag = time.monotonic() - self._mono
            if lag > self.stale_s and not self._restarting:
                self._restarting = True
                self._dump_and_restart(lag)
                return

    def _dump_and_restart(self, lag):
        log.error("event loop stalled for %.0fs; dumping stacks and restarting", lag)
        try:
            path = ROOT / "logs" / "watchdog.log"
            with open(path, "a") as f:
                f.write(f"\n--- stall {time.strftime('%Y-%m-%d %H:%M:%S')} lag={lag:.0f}s ---\n")
                for tid, fr in sys._current_frames().items():
                    text = f"\n# thread {tid}\n" + "".join(traceback.format_stack(fr))
                    f.write(mask_secret(text))
        except Exception:
            pass
        try:
            logf = open(ROOT / "logs" / "process.log", "ab")
            subprocess.Popen(
                ["bash", "-c", "sleep 1; exec ./run.sh"],
                cwd=str(ROOT),
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=logf,
                stderr=subprocess.STDOUT,
            )
        except Exception:
            pass
        os._exit(2)
