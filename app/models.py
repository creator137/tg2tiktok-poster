from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TikTokAccount(Base):
    __tablename__ = "tiktok_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_label: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)

    open_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    granted_scopes: Mapped[str | None] = mapped_column(Text, nullable=True)

    posting_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    needs_reauth: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class OAuthState(Base):
    __tablename__ = "oauth_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    account_label: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ContentItem(Base):
    __tablename__ = "content_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_type: Mapped[str] = mapped_column(String(16), nullable=False)  # video | photo | album

    source_chat_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    source_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    media_group_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)

    caption: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    telegram_file_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    local_files_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    raw_update_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    deliveries: Mapped[list["Delivery"]] = relationship(
        back_populates="content_item",
        cascade="all, delete-orphan",
    )

    def telegram_file_ids(self) -> list[str]:
        return _read_json_list(self.telegram_file_ids_json)

    def local_files(self) -> list[str]:
        return _read_json_list(self.local_files_json)

    def source_key(self) -> str:
        if self.media_group_id:
            return f"group:{self.source_chat_id}:{self.media_group_id}"
        if self.source_message_id is not None:
            return f"msg:{self.source_chat_id}:{self.source_message_id}"
        return f"content:{self.id}"


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint("source_key", "account_label", name="uq_delivery_source_account"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_item_id: Mapped[int] = mapped_column(ForeignKey("content_items.id"), nullable=False, index=True)

    source_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    account_label: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    tiktok_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    content_item: Mapped[ContentItem] = relationship(back_populates="deliveries")


class MediaGroupBuffer(Base):
    __tablename__ = "media_group_buffer"
    __table_args__ = (
        UniqueConstraint(
            "media_group_id",
            "source_message_id",
            "telegram_file_id",
            name="uq_media_group_buffer_item",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_group_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    source_chat_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_message_id: Mapped[int] = mapped_column(Integer, nullable=False)

    content_type: Mapped[str] = mapped_column(String(16), nullable=False)
    telegram_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    caption: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    raw_message_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


def _read_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if str(item).strip()]

