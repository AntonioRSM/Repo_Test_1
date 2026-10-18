"""Fan-out of progress events to Server-Sent Events subscribers."""

from __future__ import annotations

import asyncio
import json


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, event: dict) -> None:
        """Safe to call from any thread."""
        payload = json.dumps(event, default=str)
        if self._loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._deliver(payload)
        else:
            self._loop.call_soon_threadsafe(self._deliver, payload)

    def _deliver(self, payload: str) -> None:
        for queue in list(self._subscribers):
            if queue.qsize() > 1000:
                continue  # slow client: drop rather than grow without bound
            queue.put_nowait(payload)

    def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._subscribers.discard(queue)
