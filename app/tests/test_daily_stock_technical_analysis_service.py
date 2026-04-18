import sys
import types
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace


fake_llm_module = types.ModuleType("app.llm.k_line_analysis_llm")
fake_llm_module.analyze_buy_point = lambda *args, **kwargs: None
sys.modules.setdefault("app.llm.k_line_analysis_llm", fake_llm_module)

import app.services.daily_stock_technical_analysis_service as service_module
from app.services.daily_stock_technical_analysis_service import DailyStockTechnicalAnalysisService


class FakeDailyMarketAnalysisRepository:
    def __init__(self, doc_by_trade_date):
        self.doc_by_trade_date = doc_by_trade_date
        self.requested_trade_dates = []

    async def get_by_trade_date(self, trade_date: str):
        self.requested_trade_dates.append(trade_date)
        return self.doc_by_trade_date.get(trade_date)


class FakeDailyKLineSnapshotRepository:
    def __init__(self, bars_by_symbol):
        self.bars_by_symbol = bars_by_symbol
        self.calls = []

    async def get_recent_bars(self, symbol: str, end_trade_date: str, limit: int = 30):
        self.calls.append({"symbol": symbol, "end_trade_date": end_trade_date, "limit": limit})
        rows = self.bars_by_symbol.get(symbol, [])
        return [x for x in rows if x["trade_date"] <= end_trade_date][-limit:]


class FakeTechnicalResultRepository:
    def __init__(self):
        self.rows = {}

    async def get_batch_by_trade_date_stock_codes(self, trade_date: str, stock_codes: list[str]):
        out = {}
        for code in stock_codes:
            row = self.rows.get((trade_date, code))
            if row:
                out[code] = row
        return out

    async def try_claim_running(self, *, trade_date: str, stock: dict, now: datetime, running_timeout_minutes: int):
        key = (trade_date, stock["stock_code"])
        row = self.rows.get(key)
        stale_before = now - timedelta(minutes=running_timeout_minutes)

        if row is None:
            self.rows[key] = {
                "trade_date": trade_date,
                "stock_code": stock["stock_code"],
                "analysis_status": "running",
                "updated_at": now,
            }
            return SimpleNamespace(claimed=True, reason="claimed_insert")

        if row["analysis_status"] == "succeeded":
            return SimpleNamespace(claimed=False, reason="already_succeeded")

        if row["analysis_status"] in {"failed", "skipped_data_insufficient"}:
            row["analysis_status"] = "running"
            row["updated_at"] = now
            return SimpleNamespace(claimed=True, reason="claimed_retry")

        if row["analysis_status"] == "running":
            if row["updated_at"] <= stale_before:
                row["updated_at"] = now
                return SimpleNamespace(claimed=True, reason="claimed_takeover")
            return SimpleNamespace(claimed=False, reason="running_by_other")

        return SimpleNamespace(claimed=False, reason="not_claimed")

    async def mark_succeeded(self, *, trade_date: str, stock_code: str, now: datetime, context_fields: dict, llm_fields: dict):
        self.rows[(trade_date, stock_code)] = {
            "trade_date": trade_date,
            "stock_code": stock_code,
            "analysis_status": "succeeded",
            "updated_at": now,
            **context_fields,
            **llm_fields,
        }

    async def mark_failed(self, *, trade_date: str, stock_code: str, now: datetime, error_message: str, context_fields=None):
        self.rows[(trade_date, stock_code)] = {
            "trade_date": trade_date,
            "stock_code": stock_code,
            "analysis_status": "failed",
            "updated_at": now,
            "error_message": error_message,
            **(context_fields or {}),
        }

    async def mark_skipped_data_insufficient(self, *, trade_date: str, stock_code: str, now: datetime, error_message: str, context_fields: dict):
        self.rows[(trade_date, stock_code)] = {
            "trade_date": trade_date,
            "stock_code": stock_code,
            "analysis_status": "skipped_data_insufficient",
            "updated_at": now,
            "error_message": error_message,
            **context_fields,
        }


def build_stock_pool_doc(trade_date: str = "20260417", prev_trade_date: str = "20260416"):
    return {
        "trade_date": trade_date,
        "prev_trade_date": prev_trade_date,
        "sector_top_stocks": [
            {
                "rank": 1,
                "sector_name": "AI",
                "stocks": [
                    {"code": "000001", "name": "平安银行"},
                    {"code": "000002", "name": "万科A"},
                ],
            }
        ],
    }


def build_bars(n: int):
    base = datetime(2025, 12, 1)
    rows = []
    for i in range(n):
        day = base + timedelta(days=i)
        rows.append(
            {
                "trade_date": day.strftime("%Y-%m-%d"),
                "open_price": 10 + i * 0.01,
                "high_price": 10.3 + i * 0.01,
                "low_price": 9.8 + i * 0.01,
                "close_price": 10.1 + i * 0.01,
            }
        )
    return rows


class DailyStockTechnicalAnalysisServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_analyze = service_module.analyze_buy_point
        self.llm_call_count = 0
        self.llm_calls = []

        def fake_analyze(*args, **kwargs):
            self.llm_call_count += 1
            self.llm_calls.append({"args": args, "kwargs": kwargs})
            llm_analysis = SimpleNamespace(
                model_dump=lambda: {
                    "conclusion": "不买",
                    "current_channel": "震荡",
                    "channel_support_buy": "否",
                    "current_pattern": "区间",
                    "pattern_allowed_type": "否",
                    "key_candle": "无",
                    "has_follow_through": "否",
                    "can_trigger_buy": "否",
                    "expected_entry": "等待突破",
                    "trigger_condition": "放量突破",
                    "buy_price": None,
                    "stop_loss": None,
                    "take_profit": None,
                    "reason": "结构未完成",
                }
            )
            return SimpleNamespace(llm_analysis=llm_analysis)

        service_module.analyze_buy_point = fake_analyze

    def tearDown(self):
        service_module.analyze_buy_point = self.original_analyze

    def _build_service(self, result_repo, bars_by_symbol, resolver=None, doc_map=None):
        market_repo = FakeDailyMarketAnalysisRepository(
            doc_map or {"20260110": build_stock_pool_doc(trade_date="20260110", prev_trade_date="20260109")}
        )
        kline_repo = FakeDailyKLineSnapshotRepository(bars_by_symbol=bars_by_symbol)
        service = DailyStockTechnicalAnalysisService(
            daily_market_analysis_repository=market_repo,
            daily_kline_snapshot_repository=kline_repo,
            technical_result_repository=result_repo,
            resolve_target_trade_date=resolver or (lambda: "2026-01-10"),
            worker_concurrency=4,
            running_timeout_minutes=10,
        )
        return service, market_repo, kline_repo

    async def test_analysis_trade_date_and_kline_end_trade_date_are_distinct(self):
        repo = FakeTechnicalResultRepository()
        service, market_repo, kline_repo = self._build_service(
            repo,
            {"000001": build_bars(30), "000002": build_bars(30)},
            resolver=lambda: "2026-04-17",
            doc_map={"20260417": build_stock_pool_doc("20260417", "20260416")},
        )

        await service.run_once()

        self.assertEqual(market_repo.requested_trade_dates, ["20260417"])
        self.assertTrue(kline_repo.calls)
        for call in kline_repo.calls:
            self.assertEqual(call["end_trade_date"], "2026-04-16")

        self.assertIn(("2026-04-17", "000001"), repo.rows)
        self.assertIn(("2026-04-17", "000002"), repo.rows)

    async def test_non_trade_day_resolver_date_not_used_as_kline_end_date(self):
        repo = FakeTechnicalResultRepository()
        service, market_repo, kline_repo = self._build_service(
            repo,
            {"000001": build_bars(30), "000002": build_bars(30)},
            resolver=lambda: "2026-04-17",
            doc_map={"20260417": build_stock_pool_doc("20260417", "20260416")},
        )

        await service.run_once(analysis_trade_date="2026-04-17")

        self.assertEqual(market_repo.requested_trade_dates, ["20260417"])
        self.assertEqual([x["end_trade_date"] for x in kline_repo.calls], ["2026-04-16", "2026-04-16"])

    async def test_skip_succeeded_records_without_calling_llm(self):
        repo = FakeTechnicalResultRepository()
        repo.rows[("2026-01-10", "000001")] = {"analysis_status": "succeeded", "updated_at": datetime.utcnow()}
        repo.rows[("2026-01-10", "000002")] = {"analysis_status": "succeeded", "updated_at": datetime.utcnow()}
        service, _, _ = self._build_service(repo, {"000001": build_bars(30), "000002": build_bars(30)})

        stats = await service.run_once()
        self.assertEqual(stats.pre_skipped_succeeded, 2)
        self.assertEqual(stats.to_process, 0)
        self.assertEqual(self.llm_call_count, 0)

    async def test_no_record_then_running_and_succeeded(self):
        repo = FakeTechnicalResultRepository()
        service, _, _ = self._build_service(repo, {"000001": build_bars(30), "000002": build_bars(30)})

        stats = await service.run_once()
        self.assertEqual(stats.succeeded, 2)
        self.assertEqual(repo.rows[("2026-01-10", "000001")]["analysis_status"], "succeeded")

    async def test_kline_insufficient_then_skipped(self):
        repo = FakeTechnicalResultRepository()
        service, _, _ = self._build_service(repo, {"000001": build_bars(10), "000002": build_bars(30)})

        stats = await service.run_once()
        self.assertEqual(stats.skipped_data_insufficient, 1)
        self.assertEqual(repo.rows[("2026-01-10", "000001")]["analysis_status"], "skipped_data_insufficient")

    async def test_failed_can_retry(self):
        repo = FakeTechnicalResultRepository()
        repo.rows[("2026-01-10", "000001")] = {"analysis_status": "failed", "updated_at": datetime.utcnow()}
        service, _, _ = self._build_service(repo, {"000001": build_bars(30), "000002": build_bars(30)})

        await service.run_once()
        self.assertEqual(repo.rows[("2026-01-10", "000001")]["analysis_status"], "succeeded")

    async def test_running_not_expired_will_not_duplicate(self):
        repo = FakeTechnicalResultRepository()
        repo.rows[("2026-01-10", "000001")] = {
            "analysis_status": "running",
            "updated_at": datetime.utcnow(),
        }
        service, _, _ = self._build_service(repo, {"000001": build_bars(30), "000002": build_bars(30)})

        await service.run_once()
        self.assertEqual(self.llm_call_count, 1)

    async def test_running_expired_can_takeover(self):
        repo = FakeTechnicalResultRepository()
        repo.rows[("2026-01-10", "000001")] = {
            "analysis_status": "running",
            "updated_at": datetime.utcnow() - timedelta(minutes=11),
        }
        service, _, _ = self._build_service(repo, {"000001": build_bars(30), "000002": build_bars(30)})

        await service.run_once()
        self.assertEqual(repo.rows[("2026-01-10", "000001")]["analysis_status"], "succeeded")

    async def test_llm_call_without_explicit_recent_high_low(self):
        repo = FakeTechnicalResultRepository()
        service, _, _ = self._build_service(repo, {"000001": build_bars(30), "000002": build_bars(30)})

        await service.run_once()
        self.assertTrue(self.llm_calls)
        for call in self.llm_calls:
            self.assertEqual(set(call["kwargs"].keys()), {"symbol", "bars", "period"})
            self.assertEqual(call["kwargs"]["period"], "日线")

    async def test_partial_succeeded_only_backfill_rest(self):
        repo = FakeTechnicalResultRepository()
        repo.rows[("2026-01-10", "000001")] = {"analysis_status": "succeeded", "updated_at": datetime.utcnow()}
        service, _, _ = self._build_service(repo, {"000001": build_bars(30), "000002": build_bars(30)})

        stats = await service.run_once()
        self.assertEqual(stats.pre_skipped_succeeded, 1)
        self.assertEqual(stats.to_process, 1)
        self.assertEqual(self.llm_call_count, 1)


if __name__ == "__main__":
    unittest.main()
