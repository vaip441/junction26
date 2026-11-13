"""In-process publish/subscribe feeding the server-sent-events stream."""
import asyncio


class Bus:
    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def alive(self, q: asyncio.Queue) -> bool:
        return q in self._subscribers

    def publish(self, event: str, data: dict) -> None:
        """Never blocks or raises. A subscriber that has stopped reading is dropped."""
        for q in list(self._subscribers):
            try:
                q.put_nowait((event, data))
            except asyncio.QueueFull:
                self._subscribers.discard(q)
