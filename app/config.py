from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_base_url: str = "http://localhost:8000"

    tg_bot_token: str = ""
    tg_webhook_secret: str = ""
    use_tg_webhook: bool = True
    tg_allowed_chat_ids: str = ""

    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_redirect_uri: str = "http://localhost:8000/tiktok/auth/callback"

    posting_mode: Literal["draft", "direct"] = "draft"
    fallback_to_draft: bool = True

    append_hashtags: str = ""
    caption_template: str = "From TG: {text}"
    caption_max_length: int = 2200

    storage_db_path: str = "./data/app.db"
    media_storage_path: str = "./data/media"

    media_group_flush_seconds: int = 3
    slide_seconds: int = 2
    slideshow_fps: int = 30
    enable_photo_api: bool = False

    rate_limit_per_minute: int = 6

    tg_polling_timeout_seconds: int = 30
    tg_polling_interval_seconds: float = 1.0

    tg_to_tiktok_mapping_json: str = Field(
        default="",
        description='JSON mapping: {"-1001234567890":["acc1","acc2"]}',
    )

    def allowed_chat_ids(self) -> set[int]:
        if not self.tg_allowed_chat_ids.strip():
            return set()
        result: set[int] = set()
        for raw in self.tg_allowed_chat_ids.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                result.add(int(raw))
            except ValueError:
                continue
        return result

    def chat_account_mapping(self) -> dict[int, list[str]]:
        if not self.tg_to_tiktok_mapping_json.strip():
            return {}
        try:
            payload = json.loads(self.tg_to_tiktok_mapping_json)
        except json.JSONDecodeError:
            return {}

        if not isinstance(payload, dict):
            return {}

        mapping: dict[int, list[str]] = {}
        for key, value in payload.items():
            try:
                chat_id = int(key)
            except (TypeError, ValueError):
                continue
            if not isinstance(value, list):
                continue
            labels = [str(item).strip() for item in value if str(item).strip()]
            if labels:
                mapping[chat_id] = labels
        return mapping


@lru_cache
def get_settings() -> Settings:
    return Settings()

