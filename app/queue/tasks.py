from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import SessionLocal
from app.media.captions import build_caption
from app.models import ContentItem, Delivery, TikTokAccount, utcnow
from app.telegram.aggregator import MediaGroupAggregator
from app.telegram.client import TelegramClient
from app.telegram.parser import extract_message, parse_message
from app.tiktok.publisher import publish
from app.utils.rate_limit import AsyncPerAccountRateLimiter

logger = logging.getLogger(__name__)
settings = get_settings()

aggregator = MediaGroupAggregator(settings.media_group_flush_seconds)
rate_limiter = AsyncPerAccountRateLimiter(settings.rate_limit_per_minute)


async def ingest_update(update: dict[str, Any]) -> None:
    message = extract_message(update)
    if not message:
        return
    parsed = parse_message(message)
    if parsed is None:
        return

    allowed_chat_ids = settings.allowed_chat_ids()
    if allowed_chat_ids and parsed.source_chat_id not in allowed_chat_ids:
        logger.info(
            "chat_not_allowed_skip",
            extra={"event": "chat_not_allowed_skip", "chat_id": parsed.source_chat_id},
        )
        return

    if parsed.media_group_id:
        with SessionLocal() as db:
            aggregator.add(db=db, parsed=parsed, raw_message=message)
        return

    with SessionLocal() as db:
        item = _create_content_item(
            db=db,
            content_type=parsed.content_type,
            source_chat_id=parsed.source_chat_id,
            source_message_id=parsed.message_id,
            media_group_id=None,
            caption=parsed.caption,
            source_text=parsed.text,
            telegram_file_ids=[parsed.telegram_file_id],
            raw_update=update,
        )
        content_item_id = item.id

    from app.queue.worker import get_queue_worker

    await get_queue_worker().enqueue(content_item_id)


async def flush_due_media_groups_once() -> int:
    pending_ids: list[int] = []
    with SessionLocal() as db:
        bundles = aggregator.flush_due_groups(db=db)
        for bundle in bundles:
            item = _create_content_item(
                db=db,
                content_type="album",
                source_chat_id=bundle.source_chat_id,
                source_message_id=min(bundle.source_message_ids),
                media_group_id=bundle.media_group_id,
                caption=bundle.caption,
                source_text=bundle.source_text,
                telegram_file_ids=bundle.file_ids,
                raw_update={
                    "media_group_id": bundle.media_group_id,
                    "source_message_ids": bundle.source_message_ids,
                },
            )
            pending_ids.append(item.id)

    if not pending_ids:
        return 0

    from app.queue.worker import get_queue_worker

    worker = get_queue_worker()
    for item_id in pending_ids:
        await worker.enqueue(item_id)
    return len(pending_ids)


async def process_content_item(content_item_id: int) -> None:
    with SessionLocal() as db:
        item = db.scalar(select(ContentItem).where(ContentItem.id == content_item_id))
        if item is None:
            return

        try:
            local_files = await _ensure_local_files(db=db, content_item=item)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "telegram_download_failed",
                extra={
                    "event": "telegram_download_failed",
                    "content_item_id": content_item_id,
                },
            )
            _mark_all_deliveries_failed(
                db=db,
                content_item=item,
                error_text=f"Telegram download failed: {exc}",
            )
            return

        caption = build_caption(
            source_caption=item.caption,
            source_text=item.source_text,
            settings=settings,
        )

        accounts = _resolve_target_accounts(db=db, source_chat_id=item.source_chat_id)
        if not accounts:
            logger.warning(
                "no_target_accounts",
                extra={"event": "no_target_accounts", "content_item_id": item.id},
            )
            return

        source_key = item.source_key()
        for account in accounts:
            await _deliver_to_account(
                db=db,
                content_item=item,
                account=account,
                source_key=source_key,
                caption=caption,
                local_files=local_files,
            )

        item.processed_at = utcnow()
        db.commit()


def _create_content_item(
    *,
    db,
    content_type: str,
    source_chat_id: int,
    source_message_id: int | None,
    media_group_id: str | None,
    caption: str,
    source_text: str,
    telegram_file_ids: list[str],
    raw_update: dict[str, Any],
) -> ContentItem:
    item = ContentItem(
        content_type=content_type,
        source_chat_id=source_chat_id,
        source_message_id=source_message_id,
        media_group_id=media_group_id,
        caption=caption or "",
        source_text=source_text or "",
        telegram_file_ids_json=json.dumps(telegram_file_ids, ensure_ascii=False),
        local_files_json="[]",
        raw_update_json=json.dumps(raw_update, ensure_ascii=False),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


async def _ensure_local_files(*, db, content_item: ContentItem) -> list[Path]:
    existing = [Path(path) for path in content_item.local_files() if Path(path).exists()]
    file_ids = content_item.telegram_file_ids()
    if existing and len(existing) == len(file_ids):
        return existing

    if not settings.tg_bot_token:
        raise RuntimeError("TG_BOT_TOKEN is empty")

    media_dir = Path(settings.media_storage_path) / str(content_item.id)
    media_dir.mkdir(parents=True, exist_ok=True)

    downloaded: list[Path] = []
    async with TelegramClient(settings.tg_bot_token) as tg_client:
        for index, file_id in enumerate(file_ids, start=1):
            try:
                file_info = await tg_client.get_file(file_id)
                file_path = str(file_info.get("file_path") or "")
                if not file_path:
                    logger.warning(
                        "telegram_file_missing_path",
                        extra={"event": "telegram_file_missing_path", "content_item_id": content_item.id},
                    )
                    continue
                extension = Path(file_path).suffix or _default_extension(content_item.content_type)
                target_path = media_dir / f"{index}{extension}"
                payload = await tg_client.download_file(file_path)
                target_path.write_bytes(payload)
                downloaded.append(target_path)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "telegram_file_download_item_failed",
                    extra={"event": "telegram_file_download_item_failed", "content_item_id": content_item.id},
                )

    if not downloaded:
        raise RuntimeError("No files could be downloaded from Telegram")

    content_item.local_files_json = json.dumps([str(path) for path in downloaded], ensure_ascii=False)
    db.commit()
    return downloaded


def _default_extension(content_type: str) -> str:
    if content_type == "video":
        return ".mp4"
    return ".jpg"


def _resolve_target_accounts(*, db, source_chat_id: int) -> list[TikTokAccount]:
    mapping = settings.chat_account_mapping()
    labels = mapping.get(source_chat_id)
    stmt = select(TikTokAccount).order_by(TikTokAccount.account_label.asc())
    if labels:
        stmt = stmt.where(TikTokAccount.account_label.in_(labels))
    return list(db.scalars(stmt))


async def _deliver_to_account(
    *,
    db,
    content_item: ContentItem,
    account: TikTokAccount,
    source_key: str,
    caption: str,
    local_files: list[Path],
) -> None:
    delivery = db.scalar(
        select(Delivery).where(
            Delivery.source_key == source_key,
            Delivery.account_label == account.account_label,
        )
    )
    if delivery and delivery.status == "sent":
        return

    if delivery is None:
        delivery = Delivery(
            content_item_id=content_item.id,
            source_key=source_key,
            account_label=account.account_label,
            status="pending",
        )
        db.add(delivery)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            delivery = db.scalar(
                select(Delivery).where(
                    Delivery.source_key == source_key,
                    Delivery.account_label == account.account_label,
                )
            )
            if delivery and delivery.status == "sent":
                return
        else:
            db.refresh(delivery)

    await rate_limiter.wait(account.account_label)
    try:
        result = await publish(
            db=db,
            content_item=content_item,
            account=account,
            local_files=local_files,
            caption=caption,
        )
        delivery.status = "sent"
        delivery.error_text = None
        delivery.tiktok_post_id = _pick_result_post_id(result)
    except Exception as exc:  # noqa: BLE001
        delivery.status = "failed"
        delivery.error_text = str(exc)[:2000]
        logger.exception(
            "delivery_failed",
            extra={
                "event": "delivery_failed",
                "content_item_id": content_item.id,
                "account_label": account.account_label,
            },
        )
    finally:
        db.commit()


def _pick_result_post_id(result: dict[str, Any]) -> str | None:
    for key in ("post_id", "item_id", "publish_id"):
        value = result.get(key)
        if value:
            return str(value)
    return None


def _mark_all_deliveries_failed(*, db, content_item: ContentItem, error_text: str) -> None:
    accounts = _resolve_target_accounts(db=db, source_chat_id=content_item.source_chat_id)
    source_key = content_item.source_key()
    for account in accounts:
        delivery = db.scalar(
            select(Delivery).where(
                Delivery.source_key == source_key,
                Delivery.account_label == account.account_label,
            )
        )
        if delivery is None:
            delivery = Delivery(
                content_item_id=content_item.id,
                source_key=source_key,
                account_label=account.account_label,
            )
            db.add(delivery)
        delivery.status = "failed"
        delivery.error_text = error_text[:2000]
    db.commit()

