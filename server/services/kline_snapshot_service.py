from __future__ import annotations

from datetime import datetime

from domain.models.database_models import KlineSnapshotDocument
from domain.models.pipeline_models import KlineSnapshotBatch
from infrastructure.crawlers.kline_snapshot_crawler import KlineSnapshotCrawler
from infrastructure.repositories.kline_snapshot_repository import KlineSnapshotRepository


class KlineSnapshotService:
    def __init__(self, crawler: KlineSnapshotCrawler, repository: KlineSnapshotRepository):
        self.crawler = crawler
        self.repository = repository

    async def run(self, trade_date: str | None = None) -> dict:
        date_key = trade_date or datetime.now().strftime("%Y%m%d")
        batch: KlineSnapshotBatch = self.crawler.fetch(trade_date=date_key)

        inserted = 0
        for row in batch.rows:
            document = KlineSnapshotDocument(
                snapshot_id=f"{batch.trade_date}::{row.symbol}",
                trade_date=batch.trade_date,
                symbol=row.symbol,
                name=row.name,
                close_price=row.close_price,
                change_percent=row.change_percent,
                payload=row.raw_payload,
            )
            await self.repository.upsert_snapshot(document)
            inserted += 1

        return {"trade_date": batch.trade_date, "inserted": inserted}
