from __future__ import annotations

from domain.models.database_models import MarketAnalysisReportDocument
from infrastructure.crawlers.fupan_review_crawler import FupanReviewCrawler
from infrastructure.repositories.market_analysis_repository import MarketAnalysisRepository


class FupanReviewService:
    def __init__(self, crawler: FupanReviewCrawler, repository: MarketAnalysisRepository):
        self.crawler = crawler
        self.repository = repository

    async def run(self) -> MarketAnalysisReportDocument:
        payload = self.crawler.fetch()
        report = MarketAnalysisReportDocument(
            report_id=f"fupan::{payload.date}",
            report_type="fupan_review",
            analysis_date=payload.date,
            trade_date=payload.date,
            source_type=payload.source_type,
            content=payload.content,
            payload=payload.to_dict(),
        )
        await self.repository.upsert_report(report)
        return report
