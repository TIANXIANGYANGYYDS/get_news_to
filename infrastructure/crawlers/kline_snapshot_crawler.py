from __future__ import annotations

from datetime import datetime

from domain.models.pipeline_models import KlineSnapshotBatch, KlineSnapshotRow
from shared.base.crawler import BaseMarketDataCrawler


class KlineSnapshotCrawler(BaseMarketDataCrawler):
    source_name = "kline_snapshot"
    base_url = "https://82.push2.eastmoney.com/api/qt/clist/get"

    def fetch(self, limit: int = 200, trade_date: str | None = None) -> KlineSnapshotBatch:
        date_key = trade_date or datetime.now().strftime("%Y%m%d")
        params = {
            "pn": "1",
            "pz": str(limit),
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f12,f14,f2,f3",
        }
        response = self.request("GET", self.base_url, params=params, headers={"User-Agent": "Mozilla/5.0"})
        payload = response.json()
        items = payload.get("data", {}).get("diff", []) or []

        rows: list[KlineSnapshotRow] = []
        for item in items:
            symbol = str(item.get("f12") or "").strip()
            if not symbol:
                continue
            row = KlineSnapshotRow(
                symbol=symbol,
                name=str(item.get("f14") or "").strip(),
                close_price=float(item.get("f2") or 0.0),
                change_percent=float(item.get("f3") or 0.0),
                raw_payload=item,
            )
            rows.append(row)

        return KlineSnapshotBatch(trade_date=date_key, source_type=self.source_name, rows=rows)
