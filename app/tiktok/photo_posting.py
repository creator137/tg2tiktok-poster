from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.tiktok.client import TikTokAPIError, TikTokClient

logger = logging.getLogger(__name__)

IMAGE_CONTENT_TYPE = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


async def try_publish_photo_or_carousel(
    *,
    access_token: str,
    image_paths: list[Path],
    caption: str,
    mode: str,
) -> dict[str, Any] | None:
    """
    Best-effort photo/carousel publishing.

    TikTok photo/carousel endpoints depend on product access and may be missing
    for many apps. If endpoint is unavailable or permission is missing, this
    function returns None so caller can fallback to ffmpeg slideshow -> video.
    """
    if not image_paths:
        return None

    try:
        async with TikTokClient() as client:
            init_data = await client.init_photo_upload(
                access_token=access_token,
                caption=caption,
                mode=mode,
                media_count=len(image_paths),
            )
            upload_urls = _extract_upload_urls(init_data)
            if not upload_urls:
                return None
            if len(upload_urls) < len(image_paths):
                return None

            for path, upload_url in zip(image_paths, upload_urls):
                content_type = IMAGE_CONTENT_TYPE.get(path.suffix.lower(), "application/octet-stream")
                await client.upload_binary(upload_url, path, content_type=content_type)

            publish_id = _extract_publish_id(init_data)
            finalize_data = await client.finalize_photo_upload(
                access_token=access_token,
                publish_id=publish_id,
                caption=caption,
                mode=mode,
            )
            return {
                "mode": mode,
                "publish_id": publish_id,
                "post_id": (
                    _to_string(finalize_data.get("post_id"))
                    or _to_string(finalize_data.get("item_id"))
                    or publish_id
                ),
            }
    except TikTokAPIError as exc:
        if exc.is_unsupported_or_permission():
            logger.info("photo_api_unavailable", extra={"event": "photo_api_unavailable"})
            return None
        raise


def _extract_upload_urls(data: dict[str, Any]) -> list[str]:
    values: list[str] = []
    direct = data.get("upload_urls")
    if isinstance(direct, list):
        values.extend([str(item).strip() for item in direct if str(item).strip()])
    single = _to_string(data.get("upload_url"))
    if single:
        values.append(single)

    source_info = data.get("source_info")
    if isinstance(source_info, dict):
        values.extend(_extract_upload_urls(source_info))
    return values


def _extract_publish_id(data: dict[str, Any]) -> str | None:
    return (
        _to_string(data.get("publish_id"))
        or _to_string(data.get("creation_id"))
        or _to_string(data.get("item_id"))
    )


def _to_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

