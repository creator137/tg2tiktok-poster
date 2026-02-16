from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.telegram.aggregator import MediaGroupAggregator
from app.telegram.parser import ParsedMessage


def _make_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return factory()


def test_media_group_flush_collects_multiple_items() -> None:
    db = _make_session()
    aggregator = MediaGroupAggregator(flush_seconds=3)
    now = datetime.now(timezone.utc)

    msg1 = ParsedMessage(
        source_chat_id=-100111,
        message_id=1,
        media_group_id="group-1",
        content_type="photo",
        telegram_file_id="file-1",
        caption="album caption",
        text="",
        created_at=now - timedelta(seconds=10),
    )
    msg2 = ParsedMessage(
        source_chat_id=-100111,
        message_id=2,
        media_group_id="group-1",
        content_type="photo",
        telegram_file_id="file-2",
        caption="",
        text="",
        created_at=now - timedelta(seconds=9),
    )
    aggregator.add(db, msg1, {"message_id": 1})
    aggregator.add(db, msg2, {"message_id": 2})

    bundles = aggregator.flush_due_groups(db, now=now)
    assert len(bundles) == 1
    assert bundles[0].media_group_id == "group-1"
    assert bundles[0].file_ids == ["file-1", "file-2"]
    assert bundles[0].caption == "album caption"


def test_media_group_not_flushed_before_timeout() -> None:
    db = _make_session()
    aggregator = MediaGroupAggregator(flush_seconds=5)
    now = datetime.now(timezone.utc)
    msg = ParsedMessage(
        source_chat_id=-100111,
        message_id=3,
        media_group_id="group-2",
        content_type="photo",
        telegram_file_id="file-3",
        caption="",
        text="",
        created_at=now - timedelta(seconds=1),
    )
    aggregator.add(db, msg, {"message_id": 3})

    bundles = aggregator.flush_due_groups(db, now=now)
    assert bundles == []

