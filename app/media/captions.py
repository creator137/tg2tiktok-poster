from __future__ import annotations

import logging

from app.config import Settings

logger = logging.getLogger(__name__)


def build_caption(
    *,
    source_caption: str,
    source_text: str,
    settings: Settings,
) -> str:
    caption = source_caption.strip()
    if not caption:
        caption = settings.caption_template.format(text=source_text.strip())
    hashtags = settings.append_hashtags.strip()
    if hashtags:
        caption = f"{caption}\n\n{hashtags}" if caption else hashtags

    if len(caption) > settings.caption_max_length:
        logger.warning(
            "caption_truncated",
            extra={
                "event": "caption_truncated",
            },
        )
        caption = caption[: settings.caption_max_length].rstrip()
    return caption

