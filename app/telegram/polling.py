from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.db import init_db
from app.queue import tasks
from app.queue.worker import get_queue_worker
from app.telegram.client import TelegramClient
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)


async def run_polling() -> None:
    settings = get_settings()
    configure_logging()
    init_db()
    worker = get_queue_worker()
    await worker.start()

    offset: int | None = None
    logger.info("telegram_polling_started", extra={"event": "telegram_polling_started"})

    try:
        async with TelegramClient(bot_token=settings.tg_bot_token) as tg_client:
            while True:
                updates = await tg_client.get_updates(
                    offset=offset,
                    timeout=settings.tg_polling_timeout_seconds,
                )
                for update in updates:
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        offset = update_id + 1
                    await tasks.ingest_update(update)
                await asyncio.sleep(settings.tg_polling_interval_seconds)
    finally:
        await worker.stop()


def main() -> None:
    asyncio.run(run_polling())


if __name__ == "__main__":
    main()

