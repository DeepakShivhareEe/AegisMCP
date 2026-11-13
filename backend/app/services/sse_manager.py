"""Async pub/sub broadcaster for SSE clients.

Subscribers are per-process queues. When ``REDIS_URL`` is configured the
manager also relays every event through Redis pub/sub, so an event published by
one worker reaches clients connected to any other worker. Without Redis (or if
the broker becomes unavailable) it degrades to the bounded in-process
implementation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_QUEUE_SIZE = 500
DEFAULT_CHANNEL = "aegis:events"


class SSEManager:
    """Manages SSE subscriber queues and broadcasts events to connected clients."""

    def __init__(
        self,
        max_queue_size: int = DEFAULT_QUEUE_SIZE,
        redis_url: str = "",
        channel: str = DEFAULT_CHANNEL,
    ) -> None:
        self._queues: list[asyncio.Queue[dict[str, Any]]] = []
        self._max_queue_size = max_queue_size
        self._redis_url = redis_url
        self._channel = channel
        self._redis: Any = None
        self._subscriber_task: asyncio.Task[None] | None = None

    @property
    def subscriber_count(self) -> int:
        return len(self._queues)

    @property
    def redis_enabled(self) -> bool:
        return self._redis is not None

    async def start(self) -> None:
        """Connect to Redis when configured; otherwise stay in-process."""
        if not self._redis_url or self._redis is not None:
            return
        try:
            import redis.asyncio as redis_asyncio  # type: ignore[import-not-found]
        except ImportError:
            logger.warning(
                "REDIS_URL is set but the 'redis' package is not installed; "
                "SSE fan-out stays in-process"
            )
            return

        client = redis_asyncio.from_url(self._redis_url, decode_responses=True)
        try:
            await client.ping()
        except Exception as exc:  # noqa: BLE001 - degrade instead of failing startup
            logger.warning("Redis unavailable (%s); SSE fan-out stays in-process", exc)
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass
            return

        self._redis = client
        self._subscriber_task = asyncio.create_task(self._subscribe_loop())
        logger.info("SSE fan-out enabled through Redis channel %s", self._channel)

    async def stop(self) -> None:
        """Close the Redis broker and its subscriber task."""
        if self._subscriber_task is not None:
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._subscriber_task = None
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._redis = None

    async def _subscribe_loop(self) -> None:
        assert self._redis is not None
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self._channel)
        try:
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if not message:
                    await asyncio.sleep(0.05)
                    continue
                raw = message.get("data")
                if not isinstance(raw, str):
                    continue
                try:
                    event = json.loads(raw)
                except ValueError:
                    logger.warning("Discarding malformed Redis SSE event")
                    continue
                if isinstance(event, dict):
                    self._deliver_local(event)
        finally:
            try:
                await pubsub.unsubscribe(self._channel)
                await pubsub.aclose()
            except Exception:  # noqa: BLE001
                pass

    def _deliver_local(self, event: dict[str, Any]) -> None:
        stale: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in list(self._queues):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            logger.warning(
                "Dropping saturated SSE subscriber (%d queued)", self._max_queue_size
            )
            try:
                self._queues.remove(queue)
            except ValueError:
                pass

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Register and return a bounded queue for a new SSE subscriber."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue_size)
        self._queues.append(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        try:
            self._queues.remove(queue)
        except ValueError:
            return

    async def publish(self, event: dict[str, Any]) -> None:
        """Broadcast an event to this worker and, when configured, all workers."""
        if self._redis is not None:
            try:
                await self._redis.publish(self._channel, json.dumps(event, default=str))
                return
            except Exception as exc:  # noqa: BLE001 - fall back to local delivery
                logger.warning("Redis publish failed (%s); delivering locally", exc)
        self._deliver_local(event)
