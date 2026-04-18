import sys
import types
import importlib.util
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

# 轻量 stub：避免测试环境缺少 pymongo/pydantic 导致导入失败
pymongo_stub = types.ModuleType("pymongo")
pymongo_stub.ASCENDING = 1
errors_stub = types.ModuleType("pymongo.errors")


class _DuplicateKeyError(Exception):
    pass


errors_stub.DuplicateKeyError = _DuplicateKeyError
sys.modules.setdefault("pymongo", pymongo_stub)
sys.modules.setdefault("pymongo.errors", errors_stub)

model_stub = types.ModuleType("app.model")


class _DailyStockTechnicalAnalysisResult:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def to_mongo_dict(self):
        data = dict(self.kwargs)
        data.setdefault("id", "generated-id")
        data.setdefault("created_at", self.kwargs.get("created_at"))
        return data


model_stub.DailyStockTechnicalAnalysisResult = _DailyStockTechnicalAnalysisResult
sys.modules.setdefault("app.model", model_stub)

spec = importlib.util.spec_from_file_location(
    "daily_stock_technical_analysis_result_repository",
    str(Path("app/repo/daily_stock_technical_analysis_result_repository.py")),
)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)
DailyStockTechnicalAnalysisResultRepository = module.DailyStockTechnicalAnalysisResultRepository


class FakeCollection:
    def __init__(self):
        self.docs = {}

    async def create_index(self, *args, **kwargs):
        return None

    @staticmethod
    def _key(filter_dict):
        trade_date = filter_dict.get("trade_date")
        stock_code = filter_dict.get("stock_code")
        if trade_date and stock_code:
            return trade_date, stock_code
        return None

    @staticmethod
    def _match_condition(value, cond):
        if isinstance(cond, dict):
            if "$in" in cond:
                return value in cond["$in"]
            if "$lte" in cond:
                return value <= cond["$lte"]
            return False
        return value == cond

    def _match(self, doc, filter_dict):
        for k, cond in filter_dict.items():
            if k not in doc:
                return False
            if not self._match_condition(doc[k], cond):
                return False
        return True

    async def update_one(self, filter_dict, update, upsert=False):
        key = self._key(filter_dict)
        target_doc = self.docs.get(key) if key else None

        if target_doc is not None and self._match(target_doc, filter_dict):
            if "$set" in update:
                target_doc.update(update["$set"])
                return SimpleNamespace(modified_count=1, upserted_id=None)
            return SimpleNamespace(modified_count=0, upserted_id=None)

        if upsert and key and target_doc is None:
            doc = {
                "trade_date": key[0],
                "stock_code": key[1],
            }
            if "$setOnInsert" in update:
                doc.update(update["$setOnInsert"])
            if "$set" in update:
                doc.update(update["$set"])
            self.docs[key] = doc
            return SimpleNamespace(modified_count=0, upserted_id=f"upserted-{key[1]}")

        return SimpleNamespace(modified_count=0, upserted_id=None)

    async def find_one(self, filter_dict, projection=None):
        key = self._key(filter_dict)
        doc = self.docs.get(key) if key else None
        if not doc or not self._match(doc, filter_dict):
            return None
        if not projection:
            return dict(doc)
        picked = {}
        for k, enabled in projection.items():
            if enabled and k in doc:
                picked[k] = doc[k]
        return picked


class FakeDB(dict):
    def __getitem__(self, item):
        if item not in self:
            self[item] = FakeCollection()
        return dict.__getitem__(self, item)


class DailyStockTechnicalAnalysisResultRepositoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = FakeDB()
        self.repo = DailyStockTechnicalAnalysisResultRepository(self.db)

    async def test_claim_insert_contains_id_and_created_at(self):
        now = datetime.utcnow()
        claim = await self.repo.try_claim_running(
            trade_date="2026-01-10",
            stock={
                "stock_code": "000001",
                "stock_name": "平安银行",
                "sector_name": "AI",
                "sector_rank": 1,
                "stock_rank_in_sector": 1,
            },
            now=now,
            running_timeout_minutes=10,
        )
        self.assertTrue(claim.claimed)

        doc = self.db[self.repo.collection_name].docs[("2026-01-10", "000001")]
        self.assertIn("id", doc)
        self.assertIn("created_at", doc)
        self.assertEqual(doc["analysis_status"], "running")

    async def test_status_update_keeps_initial_id_and_created_at(self):
        now = datetime.utcnow()
        stock = {
            "stock_code": "000001",
            "stock_name": "平安银行",
            "sector_name": "AI",
            "sector_rank": 1,
            "stock_rank_in_sector": 1,
        }
        await self.repo.try_claim_running(
            trade_date="2026-01-10",
            stock=stock,
            now=now,
            running_timeout_minutes=10,
        )

        key = ("2026-01-10", "000001")
        created_at = self.db[self.repo.collection_name].docs[key]["created_at"]
        row_id = self.db[self.repo.collection_name].docs[key]["id"]

        await self.repo.mark_succeeded(
            trade_date="2026-01-10",
            stock_code="000001",
            now=now + timedelta(minutes=1),
            context_fields={"bars_count": 30},
            llm_fields={"conclusion": "买"},
        )
        self.assertEqual(self.db[self.repo.collection_name].docs[key]["created_at"], created_at)
        self.assertEqual(self.db[self.repo.collection_name].docs[key]["id"], row_id)

        await self.repo.mark_failed(
            trade_date="2026-01-10",
            stock_code="000001",
            now=now + timedelta(minutes=2),
            error_message="fail",
        )
        self.assertEqual(self.db[self.repo.collection_name].docs[key]["created_at"], created_at)
        self.assertEqual(self.db[self.repo.collection_name].docs[key]["id"], row_id)

        await self.repo.mark_skipped_data_insufficient(
            trade_date="2026-01-10",
            stock_code="000001",
            now=now + timedelta(minutes=3),
            error_message="insufficient",
            context_fields={"bars_count": 10},
        )
        self.assertEqual(self.db[self.repo.collection_name].docs[key]["created_at"], created_at)
        self.assertEqual(self.db[self.repo.collection_name].docs[key]["id"], row_id)


if __name__ == "__main__":
    unittest.main()
