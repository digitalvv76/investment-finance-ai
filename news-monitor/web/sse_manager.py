"""Server-Sent Events manager for real-time news push to browser clients.

Lightweight pub/sub: clients subscribe to receive a queue, broadcast
pushes events to every connected client.  Stale clients are auto-pruned.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, Set

logger = logging.getLogger(__name__)


class SSEManager:
    """Manages connected SSE clients and broadcasts events."""

    def __init__(self) -> None:
        self._queues: Dict[int, asyncio.Queue] = {}
        self._next_id = 0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def subscribe(self) -> tuple[int, asyncio.Queue]:
        """Register a new SSE client.

        Returns (client_id, queue).  The caller reads from the queue
        and writes to the SSE response stream.
        """
        async with self._lock:
            cid = self._next_id
            self._next_id += 1
            q: asyncio.Queue = asyncio.Queue(maxsize=200)
            self._queues[cid] = q
            logger.debug("SSE client %d subscribed (%d total)", cid, len(self._queues))
            return cid, q

    async def unsubscribe(self, client_id: int) -> None:
        """Remove a disconnected client."""
        async with self._lock:
            self._queues.pop(client_id, None)
            logger.debug("SSE client %d unsubscribed (%d remaining)", client_id, len(self._queues))

    async def broadcast(self, event_type: str, data: dict) -> None:
        """Push an event to all connected clients.

        Slow/dead clients (queue full) are silently dropped.
        """
        payload = f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"

        async with self._lock:
            dead: list[int] = []
            for cid, q in self._queues.items():
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    dead.append(cid)
            for cid in dead:
                self._queues.pop(cid, None)

        if dead:
            logger.debug("SSE pruned %d dead client(s)", len(dead))

    @property
    def client_count(self) -> int:
        return len(self._queues)
