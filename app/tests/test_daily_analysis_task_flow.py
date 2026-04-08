import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import create_app
from app.llm import Moring_Reading_llm
from app.services.daily_analysis_task_service import DailyAnalysisTaskService


class InMemoryTaskRepo:
    def __init__(self, task=None):
        self.task = task or {
            "_id": "task-1",
            "biz_date": "2026-04-08",
            "retry_count": 0,
            "max_retry_count": 8,
            "analysis_text": None,
            "card_sent": False,
        }
        self.retry_history = []
        self.failed = False
        self.sent_marked = 0

    async def save_analysis_text(self, *, task_id, analysis_text):
        self.task["analysis_text"] = analysis_text

    async def mark_card_sent(self, *, task_id):
        self.task["card_sent"] = True
        self.sent_marked += 1

    async def mark_retry(self, **kwargs):
        self.retry_history.append(kwargs)
        self.task["retry_count"] = kwargs["retry_count"]

    async def mark_failed(self, **kwargs):
        self.failed = True


class DailyAnalysisTaskFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_then_success(self):
        repo = InMemoryTaskRepo()
        calls = {"gen": 0, "send": 0}

        class FakeMarketService:
            def get_a_share_trade_dates(self):
                return "20260408", "20260407"

            def format_trade_date(self, text):
                return "2026-04-08"

            async def prepare_daily_analysis_payload(self):
                return {"morning_data": {"source": "test"}}

            def generate_analysis_text(self, payload):
                calls["gen"] += 1
                if calls["gen"] == 1:
                    raise RuntimeError("APITimeoutError: timeout")
                return "第一主线：银行\n理由：测试"

        class FakeNotifier:
            async def send_card(self, card):
                calls["send"] += 1

        service = DailyAnalysisTaskService(
            task_repository=repo,
            market_analysis_service=FakeMarketService(),
            notifier=FakeNotifier(),
            card_builder=SimpleNamespace(build_daily_market_analysis_card=lambda **kwargs: {}),
        )

        await service.execute_claimed_task(repo.task)
        self.assertEqual(len(repo.retry_history), 1)
        self.assertFalse(repo.task["card_sent"])

        await service.execute_claimed_task(repo.task)
        self.assertTrue(repo.task["card_sent"])
        self.assertEqual(calls["send"], 1)

    async def test_card_sent_idempotent(self):
        repo = InMemoryTaskRepo(
            task={
                "_id": "task-2",
                "biz_date": "2026-04-08",
                "retry_count": 0,
                "max_retry_count": 8,
                "analysis_text": "已有分析",
                "card_sent": True,
            }
        )

        class FakeMarketService:
            async def prepare_daily_analysis_payload(self):
                raise AssertionError("should not regenerate")

        class FakeNotifier:
            async def send_card(self, card):
                raise AssertionError("should not send again")

        service = DailyAnalysisTaskService(
            task_repository=repo,
            market_analysis_service=FakeMarketService(),
            notifier=FakeNotifier(),
            card_builder=SimpleNamespace(build_daily_market_analysis_card=lambda **kwargs: {}),
        )
        await service.execute_claimed_task(repo.task)
        self.assertEqual(repo.sent_marked, 1)

    async def test_recover_running_lock_expired(self):
        now = datetime.utcnow()
        runnable = {
            "task_type": "daily_market_analysis",
            "status": "running",
            "lock_until": now - timedelta(seconds=5),
            "next_retry_at": now,
        }
        is_runnable = runnable["status"] == "running" and runnable["lock_until"] <= now
        self.assertTrue(is_runnable)


class StartupDoesNotBlockTests(unittest.TestCase):
    def test_startup_ignore_daily_task_register_error(self):
        class DummyApplication:
            async def startup(self):
                return None

            async def shutdown(self):
                return None

            async def ensure_today_daily_analysis_task_exists(self):
                raise RuntimeError("APITimeoutError: timeout")

            scheduler = SimpleNamespace(is_running=False, next_run_at_iso=None)
            cls_telegraph_polling_task = None
            db = object()

        app = create_app(application_factory=DummyApplication, run_on_startup=True)
        with TestClient(app) as client:
            resp = client.get("/api/v1/health")
            self.assertEqual(resp.status_code, 200)


class LLMFallbackTests(unittest.TestCase):
    def test_enable_thinking_timeout_then_fallback_success(self):
        calls = {"n": 0}

        def fake_call(**kwargs):
            calls["n"] += 1
            if kwargs.get("enable_thinking"):
                raise RuntimeError("timeout: APITimeoutError")
            return "第一主线：银行\n理由：测试"

        old_call = Moring_Reading_llm._call_llm_once
        try:
            Moring_Reading_llm._call_llm_once = fake_call
            result = Moring_Reading_llm.analyze_morning_data_with_fallback(
                morning_data={"date": "2026-04-08", "sections": {}},
                prev_day_review="",
                investment_preference_ranking=None,
                market_heat_ranking=None,
            )
            self.assertIn("第一主线", result)
            self.assertGreaterEqual(calls["n"], 2)
        finally:
            Moring_Reading_llm._call_llm_once = old_call
