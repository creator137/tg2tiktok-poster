from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import MediaGroupBuffer
from app.telegram.parser import ParsedMessage


@dataclass(slots=True)
class MediaGroupBundle:
    media_group_id: str
    source_chat_id: int
    source_message_ids: list[int]
    file_ids: list[str]
    caption: str
    source_text: str
    created_at: datetime


class MediaGroupAggregator:
    def __init__(self, flush_seconds: int) -> None:
        self.flush_seconds = max(1, flush_seconds)

    def add(self, db: Session, parsed: ParsedMessage, raw_message: dict[str, Any]) -> None:
        if not parsed.media_group_id:
            return
        row = MediaGroupBuffer(
            media_group_id=parsed.media_group_id,
            source_chat_id=parsed.source_chat_id,
            source_message_id=parsed.message_id,
            content_type=parsed.content_type,
            telegram_file_id=parsed.telegram_file_id,
            caption=parsed.caption,
            source_text=parsed.text,
            raw_message_json=json.dumps(raw_message, ensure_ascii=False),
            created_at=parsed.created_at,
        )
        db.add(row)
        db.commit()

    def flush_due_groups(
        self,
        db: Session,
        now: datetime | None = None,
    ) -> list[MediaGroupBundle]:
        now = now or datetime.now(timezone.utc)
        threshold = now - timedelta(seconds=self.flush_seconds)

        due_group_ids = list(
            db.scalars(
                select(MediaGroupBuffer.media_group_id)
                .group_by(MediaGroupBuffer.media_group_id)
                .having(func.min(MediaGroupBuffer.created_at) <= threshold)
            )
        )
        if not due_group_ids:
            return []

        result: list[MediaGroupBundle] = []
        for group_id in due_group_ids:
            rows = list(
                db.scalars(
                    select(MediaGroupBuffer)
                    .where(MediaGroupBuffer.media_group_id == group_id)
                    .order_by(MediaGroupBuffer.source_message_id.asc())
                )
            )
            if not rows:
                continue

            caption = next((row.caption for row in rows if row.caption.strip()), "")
            source_text = next((row.source_text for row in rows if row.source_text.strip()), "")
            bundle = MediaGroupBundle(
                media_group_id=group_id,
                source_chat_id=rows[0].source_chat_id,
                source_message_ids=[row.source_message_id for row in rows],
                file_ids=[row.telegram_file_id for row in rows],
                caption=caption,
                source_text=source_text,
                created_at=min(row.created_at for row in rows),
            )
            result.append(bundle)

        db.execute(delete(MediaGroupBuffer).where(MediaGroupBuffer.media_group_id.in_(due_group_ids)))
        db.commit()
        return result

