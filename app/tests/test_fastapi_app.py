import os
import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient


os.environ["FEISHU_APP_ID"] = "test-app-id"
os.environ["FEISHU_APP_SECRET"] = "test-app-secret"
os.environ["FEISHU_CHAT_ID"] = "test-chat-id"
os.environ["API_KEY"] = "test-api-key"
os.environ["MONGO_URI"] = "mongodb://localhost:27017"
os.environ["MONGO_DB_NAME"] = "test-db"

from app.main import create_app


class DummyApplication:
    def __init__(self):
        self.scheduler = SimpleNamespace(
            is_running=True,
            next_run_at_iso="2026-04-04T09:00:00+08:00",
        )
        self.cls_telegraph_polling_task = None
        self.db = object()
        self.startup_calls = 0
        self.shutdown_calls = 0
        self.test_card_calls = 0
        self.market_analysis_calls = 0
        self.sync_calls = []

    async def startup(self):
        self.startup_calls += 1

    async def shutdown(self):
        self.shutdown_calls += 1

    async def send_daily_test_card(self):
        self.test_card_calls += 1

    async def send_daily_market_analysis_card(self):
        self.market_analysis_calls += 1

    async def sync_cls_telegraphs_once(self, send_insert_card: bool = True):
        self.sync_calls.append(send_insert_card)


class FastAPIAppTests(unittest.TestCase):
    def test_lifespan_and_task_routes(self):
        dummy_application = DummyApplication()
        api = create_app(
            application_factory=lambda: dummy_application,
            run_on_startup=False,
        )

        with TestClient(api) as client:
            health_response = client.get("/api/v1/health")
            self.assertEqual(health_response.status_code, 200)
            self.assertEqual(
                health_response.json(),
                {
                    "status": "ok",
                    "scheduler_running": True,
                    "cls_telegraph_polling_running": False,
                    "next_daily_run_at": "2026-04-04T09:00:00+08:00",
                    "mongo_connected": True,
                },
            )

            test_card_response = client.post("/api/v1/tasks/test-card")
            self.assertEqual(test_card_response.status_code, 200)
            self.assertEqual(
                test_card_response.json(),
                {"ok": True, "message": "test card sent"},
            )

            analysis_response = client.post("/api/v1/tasks/daily-market-analysis")
            self.assertEqual(analysis_response.status_code, 200)
            self.assertEqual(
                analysis_response.json(),
                {"ok": True, "message": "daily market analysis completed"},
            )

            sync_response = client.post(
                "/api/v1/tasks/cls-telegraphs/sync",
                json={"send_insert_card": False},
            )
            self.assertEqual(sync_response.status_code, 200)
            self.assertEqual(
                sync_response.json(),
                {"ok": True, "message": "cls telegraphs sync completed"},
            )

        self.assertEqual(dummy_application.startup_calls, 1)
        self.assertEqual(dummy_application.shutdown_calls, 1)
        self.assertEqual(dummy_application.test_card_calls, 1)
        self.assertEqual(dummy_application.market_analysis_calls, 1)
        self.assertEqual(dummy_application.sync_calls, [False])
