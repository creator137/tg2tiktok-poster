from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

EXTRA_KEYS = {
    "event",
    "chat_id",
    "message_id",
    "media_group_id",
    "content_item_id",
    "account_label",
    "source_key",
    "status",
    "count",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in EXTRA_KEYS:
            if key in record.__dict__:
                payload[key] = record.__dict__[key]
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    stream = logging.StreamHandler()
    stream.setFormatter(JsonFormatter())
    root.addHandler(stream)
    root.setLevel(level)

