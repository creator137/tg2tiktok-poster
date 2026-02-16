from app.telegram.parser import parse_message


def test_parse_video_message() -> None:
    message = {
        "message_id": 101,
        "date": 1700000000,
        "chat": {"id": -100123, "type": "channel"},
        "caption": "video caption",
        "video": {"file_id": "video_file_id_1"},
    }
    parsed = parse_message(message)
    assert parsed is not None
    assert parsed.content_type == "video"
    assert parsed.telegram_file_id == "video_file_id_1"
    assert parsed.caption == "video caption"


def test_parse_document_video_message() -> None:
    message = {
        "message_id": 102,
        "date": 1700000000,
        "chat": {"id": -100123, "type": "channel"},
        "document": {
            "file_id": "doc_video_id",
            "mime_type": "video/mp4",
        },
    }
    parsed = parse_message(message)
    assert parsed is not None
    assert parsed.content_type == "video"
    assert parsed.telegram_file_id == "doc_video_id"


def test_parse_photo_message_uses_largest_size() -> None:
    message = {
        "message_id": 103,
        "date": 1700000000,
        "chat": {"id": -100123, "type": "channel"},
        "photo": [
            {"file_id": "small", "file_size": 100, "width": 100, "height": 100},
            {"file_id": "large", "file_size": 1000, "width": 1000, "height": 1000},
        ],
    }
    parsed = parse_message(message)
    assert parsed is not None
    assert parsed.content_type == "photo"
    assert parsed.telegram_file_id == "large"

