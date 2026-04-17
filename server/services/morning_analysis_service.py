from __future__ import annotations

from datetime import datetime

from domain.models.database_models import MarketAnalysisReportDocument
from infrastructure.crawlers.morning_reading_crawler import MorningReadingCrawler
from infrastructure.llm.morning_market_analyzer import MorningMarketAnalyzer
from infrastructure.repositories.market_analysis_repository import MarketAnalysisRepository


class MorningAnalysisService:
    def __init__(
        self,
        crawler: MorningReadingCrawler,
        analyzer: MorningMarketAnalyzer,
        repository: MarketAnalysisRepository,
    ):
        self.crawler = crawler
        self.analyzer = analyzer
        self.repository = repository

    async def run(self) -> MarketAnalysisReportDocument:
        morning_payload = self.crawler.fetch()
        analysis_output = self.analyzer.analyze(morning_payload)
        analysis_date = datetime.now().strftime("%Y-%m-%d")

        report = MarketAnalysisReportDocument(
            report_id=f"morning::{analysis_date}",
            report_type="morning_analysis",
            analysis_date=analysis_date,
            trade_date=morning_payload.date,
            source_type=morning_payload.source_type,
            content=analysis_output.summary_text,
            payload={
                "morning_payload": morning_payload.to_dict(),
                "analysis_output": analysis_output.to_dict(),
            },
        )
        await self.repository.upsert_report(report)
        return report
