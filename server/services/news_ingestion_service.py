from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from domain.models.database_models import NewsDocument
from domain.models.news_models import NewsEvent
from infrastructure.repositories.news_repository import NewsRepository
from server.services.news_analysis_service import NewsAnalysisService
from server.services.news_deduplication_service import NewsDeduplicationService


@dataclass
class NewsIngestionResult:
    inserted: int
    by_source: dict[str, int]

    def to_dict(self) -> dict:
        return {"inserted": self.inserted, "by_source": self.by_source}


class NewsIngestionService:
    def __init__(
        self,
        crawlers,
        repository: NewsRepository,
        dedup_service: NewsDeduplicationService,
        analysis_service: NewsAnalysisService,
    ):
        self.crawlers = crawlers
        self.repository = repository
        self.dedup_service = dedup_service
        self.analysis_service = analysis_service

    async def ingest(self, *, limit: int = 20) -> NewsIngestionResult:
        total_inserted = 0
        by_source: dict[str, int] = defaultdict(int)

        for crawler in self.crawlers:
            fetched: list[NewsEvent] = crawler.fetch(limit=limit)
            events = self.dedup_service.deduplicate(fetched)
            existing = await self.repository.get_existing_event_ids([event.event_id for event in events])
            for event in events:
                if event.event_id in existing:
                    continue
                analysis_result = self.analysis_service.analyze(event)
                document = NewsDocument.from_news_event(event)
                document.analysis = analysis_result
                await self.repository.upsert_news_document(document)
                total_inserted += 1
                by_source[event.source.value] += 1

        return NewsIngestionResult(inserted=total_inserted, by_source=dict(by_source))
