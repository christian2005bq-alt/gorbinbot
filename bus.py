"""Queues between agents (scanner -> auditor -> analyst -> executor -> risk) + SSE fan-out."""
import asyncio, json


class Bus:
    def __init__(self):
        self.auditor = asyncio.Queue()
        self.analyst = asyncio.Queue()
        self.executor = asyncio.Queue()
        self.risk = asyncio.Queue()
        self._subs: set[asyncio.Queue] = set()

    def subscribe(self):
        q = asyncio.Queue(maxsize=500)
        self._subs.add(q)
        return q

    def unsubscribe(self, q):
        self._subs.discard(q)

    def emit(self, event: str, data: dict):
        msg = (event, json.dumps(data, default=str))
        for q in list(self._subs):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass
