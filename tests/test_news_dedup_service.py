from datetime import datetime

from domain.enums.news import NewsSource
from domain.models.news_models import NewsEvent
from server.services.news_deduplication_service import NewsDeduplicationService


def test_deduplicate_by_event_id():
    service = NewsDeduplicationService()
    dt = datetime.utcnow()
    events = [
        NewsEvent(event_id="1", source=NewsSource.CLS, title="a", content="x", published_at=dt, publish_ts=1),
        NewsEvent(event_id="1", source=NewsSource.CLS, title="b", content="y", published_at=dt, publish_ts=2),
        NewsEvent(event_id="2", source=NewsSource.JIN10, title="c", content="z", published_at=dt, publish_ts=3),
    ]

    deduplicated = service.deduplicate(events)
    assert [event.event_id for event in deduplicated] == ["1", "2"]
