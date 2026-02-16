from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.media import ffmpeg
from app.models import ContentItem, TikTokAccount
from app.tiktok import oauth, photo_posting, video_posting

settings = get_settings()
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".webm", ".mkv"}


async def publish(
    *,
    db: Session,
    content_item: ContentItem,
    account: TikTokAccount,
    local_files: list[Path],
    caption: str,
) -> dict[str, Any]:
    access_token = await oauth.ensure_valid_access_token(db=db, account=account)
    requested_mode = account.posting_mode or settings.posting_mode

    if content_item.content_type == "video":
        result = await video_posting.publish_video_file(
            access_token=access_token,
            video_path=local_files[0],
            caption=caption,
            requested_mode=requested_mode,
            fallback_to_draft=settings.fallback_to_draft,
        )
        return {"mode": result.mode, "publish_id": result.publish_id, "post_id": result.post_id}

    image_paths = [path for path in local_files if path.suffix.lower() in IMAGE_EXTENSIONS]

    if settings.enable_photo_api and image_paths:
        photo_result = await photo_posting.try_publish_photo_or_carousel(
            access_token=access_token,
            image_paths=image_paths,
            caption=caption,
            mode=requested_mode,
        )
        if photo_result is not None:
            return photo_result

    fallback_video = await _convert_to_video(content_item=content_item, local_files=local_files)
    result = await video_posting.publish_video_file(
        access_token=access_token,
        video_path=fallback_video,
        caption=caption,
        requested_mode=requested_mode,
        fallback_to_draft=settings.fallback_to_draft,
    )
    return {"mode": result.mode, "publish_id": result.publish_id, "post_id": result.post_id}


async def _convert_to_video(content_item: ContentItem, local_files: list[Path]) -> Path:
    media_dir = Path(settings.media_storage_path) / str(content_item.id)
    media_dir.mkdir(parents=True, exist_ok=True)
    target_path = media_dir / f"{content_item.id}_slideshow.mp4"

    if content_item.content_type == "photo":
        source = local_files[0]
        ffmpeg.photo_to_video(
            image_path=source,
            output_path=target_path,
            seconds=settings.slide_seconds,
            fps=settings.slideshow_fps,
        )
        return target_path

    image_paths = [path for path in local_files if path.suffix.lower() in IMAGE_EXTENSIONS]
    if image_paths:
        ffmpeg.album_to_video(
            image_paths=image_paths,
            output_path=target_path,
            slide_seconds=settings.slide_seconds,
            fps=settings.slideshow_fps,
        )
        return target_path

    for path in local_files:
        if path.suffix.lower() in VIDEO_EXTENSIONS:
            return path
    return local_files[0]

