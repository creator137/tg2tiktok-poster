from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.tiktok.client import TikTokAPIError, TikTokClient

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PublishResult:
    mode: str
    publish_id: str | None
    post_id: str | None


async def publish_video_file(
    *,
    access_token: str,
    video_path: Path,
    caption: str,
    requested_mode: str,
    fallback_to_draft: bool,
) -> PublishResult:
    try:
        return await _publish_with_mode(
            access_token=access_token,
            video_path=video_path,
            caption=caption,
            mode=requested_mode,
        )
    except TikTokAPIError as exc:
        if requested_mode == "direct" and fallback_to_draft and exc.is_unsupported_or_permission():
            logger.warning(
                "direct_publish_failed_fallback_to_draft",
                extra={
                    "event": "direct_publish_failed_fallback_to_draft",
                    "status": str(exc)[:180],
                },
            )
            return await _publish_with_mode(
                access_token=access_token,
                video_path=video_path,
                caption=caption,
                mode="draft",
            )
        raise


async def _publish_with_mode(
    *,
    access_token: str,
    video_path: Path,
    caption: str,
    mode: str,
) -> PublishResult:
    async with TikTokClient() as client:
        init_data = await client.init_video_upload(
            access_token=access_token,
            caption=caption,
            mode=mode,
            video_size_bytes=video_path.stat().st_size,
        )

        upload_url = _extract_upload_url(init_data)
        if not upload_url:
            raise TikTokAPIError("TikTok response does not contain upload_url", payload=init_data)

        publish_id = _extract_publish_id(init_data)
        await client.upload_binary(upload_url, video_path, content_type="video/mp4")

        finalize_data = await client.finalize_video(
            access_token=access_token,
            publish_id=publish_id,
            caption=caption,
            mode=mode,
        )

    post_id = (
        _string_or_none(finalize_data.get("post_id"))
        or _string_or_none(finalize_data.get("item_id"))
        or publish_id
    )
    return PublishResult(mode=mode, publish_id=publish_id, post_id=post_id)


def _extract_upload_url(data: dict[str, Any]) -> str | None:
    single = _string_or_none(data.get("upload_url"))
    if single:
        return single

    upload_urls = data.get("upload_urls")
    if isinstance(upload_urls, list):
        for item in upload_urls:
            value = _string_or_none(item)
            if value:
                return value

    source_info = data.get("source_info")
    if isinstance(source_info, dict):
        return _extract_upload_url(source_info)

    return None


def _extract_publish_id(data: dict[str, Any]) -> str | None:
    return (
        _string_or_none(data.get("publish_id"))
        or _string_or_none(data.get("video_id"))
        or _string_or_none(data.get("creation_id"))
    )


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    as_str = str(value).strip()
    return as_str or None
