from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class BackgroundWorker:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self._consumer_task: asyncio.Task[None] | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._consumer_task and not self._consumer_task.done():
            return
        self._stopping = False
        self._consumer_task = asyncio.create_task(self._consume_loop(), name="content-consumer")
        self._flush_task = asyncio.create_task(self._flush_loop(), name="media-group-flush")

    async def stop(self) -> None:
        self._stopping = True
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None

        if self._consumer_task:
            await self.queue.put(-1)
            await self._consumer_task
            self._consumer_task = None

    async def enqueue(self, content_item_id: int) -> None:
        await self.queue.put(content_item_id)

    async def _consume_loop(self) -> None:
        from app.queue import tasks

        while True:
            content_item_id = await self.queue.get()
            try:
                if content_item_id == -1:
                    return
                await tasks.process_content_item(content_item_id)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "content_processing_failed",
                    extra={"event": "content_processing_failed", "content_item_id": content_item_id},
                )
            finally:
                self.queue.task_done()

    async def _flush_loop(self) -> None:
        from app.queue import tasks

        while not self._stopping:
            try:
                count = await tasks.flush_due_media_groups_once()
                if count:
                    logger.info(
                        "media_group_flush_completed",
                        extra={"event": "media_group_flush_completed", "count": count},
                    )
            except Exception:  # noqa: BLE001
                logger.exception("media_group_flush_failed", extra={"event": "media_group_flush_failed"})
            await asyncio.sleep(1)


_worker = BackgroundWorker()


def get_queue_worker() -> BackgroundWorker:
    return _worker

