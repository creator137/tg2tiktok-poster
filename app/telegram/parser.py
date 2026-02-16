from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal


@dataclass(slots=True)
class ParsedMessage:
    source_chat_id: int
    message_id: int
    media_group_id: str | None
    content_type: Literal["video", "photo"]
    telegram_file_id: str
    caption: str
    text: str
    created_at: datetime


def extract_message(update: dict[str, Any]) -> dict[str, Any] | None:
    if "channel_post" in update:
        return update["channel_post"]
    if "message" in update:
        return update["message"]
    return None


def parse_message(message: dict[str, Any]) -> ParsedMessage | None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    if not isinstance(chat_id, int) or not isinstance(message_id, int):
        return None

    caption = _safe_text(message.get("caption"))
    text = _safe_text(message.get("text"))
    media_group_id = _safe_text(message.get("media_group_id")) or None
    created_at = _parse_created_at(message.get("date"))

    if "video" in message and isinstance(message["video"], dict):
        file_id = _safe_text(message["video"].get("file_id"))
        if file_id:
            return ParsedMessage(
                source_chat_id=chat_id,
                message_id=message_id,
                media_group_id=media_group_id,
                content_type="video",
                telegram_file_id=file_id,
                caption=caption,
                text=text,
                created_at=created_at,
            )

    document = message.get("document")
    if isinstance(document, dict):
        mime = _safe_text(document.get("mime_type")).lower()
        file_id = _safe_text(document.get("file_id"))
        if file_id and mime.startswith("video/"):
            return ParsedMessage(
                source_chat_id=chat_id,
                message_id=message_id,
                media_group_id=media_group_id,
                content_type="video",
                telegram_file_id=file_id,
                caption=caption,
                text=text,
                created_at=created_at,
            )

    photo_sizes = message.get("photo")
    if isinstance(photo_sizes, list) and photo_sizes:
        best = _pick_largest_photo(photo_sizes)
        file_id = _safe_text(best.get("file_id"))
        if file_id:
            return ParsedMessage(
                source_chat_id=chat_id,
                message_id=message_id,
                media_group_id=media_group_id,
                content_type="photo",
                telegram_file_id=file_id,
                caption=caption,
                text=text,
                created_at=created_at,
            )

    return None


def _pick_largest_photo(photo_sizes: list[dict[str, Any]]) -> dict[str, Any]:
    def sort_key(item: dict[str, Any]) -> tuple[int, int]:
        size = int(item.get("file_size") or 0)
        area = int(item.get("width") or 0) * int(item.get("height") or 0)
        return (size, area)

    return max(photo_sizes, key=sort_key)


def _parse_created_at(raw_ts: Any) -> datetime:
    if isinstance(raw_ts, (int, float)):
        try:
            return datetime.fromtimestamp(raw_ts, tz=timezone.utc)
        except (ValueError, OSError):
            pass
    return datetime.now(timezone.utc)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()

