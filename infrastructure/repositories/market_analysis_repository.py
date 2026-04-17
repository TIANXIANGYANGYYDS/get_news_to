from __future__ import annotations

from datetime import datetime

from domain.models.database_models import MarketAnalysisReportDocument
from shared.base.repository import BaseMongoRepository


class MarketAnalysisRepository(BaseMongoRepository):
    collection_name = "market_analysis_reports"

    async def ensure_indexes(self):
        await self.collection.create_index("report_id", unique=True, name="uk_report_id")
        await self.collection.create_index([("report_type", 1), ("analysis_date", -1)], name="idx_report_type_date")

    async def upsert_report(self, report: MarketAnalysisReportDocument):
        payload = report.to_dict()
        payload["updated_at"] = datetime.utcnow()
        return await self.upsert_one({"report_id": report.report_id}, payload)
