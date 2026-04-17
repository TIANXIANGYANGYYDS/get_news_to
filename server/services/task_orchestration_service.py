from domain.models.pipeline_models import NotificationPayload
from server.services.fupan_review_service import FupanReviewService
from server.services.kline_snapshot_service import KlineSnapshotService
from server.services.morning_analysis_service import MorningAnalysisService
from server.services.news_ingestion_service import NewsIngestionService
from server.services.notification_service import NotificationService
from server.services.sector_aggregation_service import SectorAggregationService


class TaskOrchestrationService:
    def __init__(
        self,
        ingestion_service: NewsIngestionService,
        aggregation_service: SectorAggregationService,
        notification_service: NotificationService,
        morning_analysis_service: MorningAnalysisService,
        fupan_review_service: FupanReviewService,
        kline_snapshot_service: KlineSnapshotService,
    ):
        self.ingestion_service = ingestion_service
        self.aggregation_service = aggregation_service
        self.notification_service = notification_service
        self.morning_analysis_service = morning_analysis_service
        self.fupan_review_service = fupan_review_service
        self.kline_snapshot_service = kline_snapshot_service

    async def run_news_ingestion(self, *, limit: int = 20):
        result = await self.ingestion_service.ingest(limit=limit)
        return result.to_dict()

    async def run_sector_aggregation(self):
        result = await self.aggregation_service.aggregate_latest(limit=200)
        return result.to_dict()

    async def run_notification(self, payload: NotificationPayload):
        await self.notification_service.send_message(payload)

    async def run_morning_analysis(self):
        report = await self.morning_analysis_service.run()
        return report.to_dict()

    async def run_fupan_review(self):
        report = await self.fupan_review_service.run()
        return report.to_dict()

    async def run_kline_snapshot(self):
        return await self.kline_snapshot_service.run()
