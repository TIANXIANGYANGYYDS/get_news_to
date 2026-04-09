import unittest
import sys
import types

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")

    class OpenAI:  # pragma: no cover - 仅用于测试导入桩
        pass

    openai_stub.OpenAI = OpenAI
    sys.modules["openai"] = openai_stub

from app.llm.cls_telegraph_llm import _coerce_payload_shape
from app.model import CLSTelegraphLLMAnalysis
from app.repo.sector_3d_daily_summary_repository import Sector3DDailySummaryRepository
from app.repo.sector_investment_preference_ranking_repository import (
    SectorInvestmentPreferenceRankingRepository,
)


class SectorAnalysisModelTests(unittest.TestCase):
    def test_model_accepts_multi_sector_analysis(self):
        model = CLSTelegraphLLMAnalysis.model_validate(
            {
                "sector_analyses": [
                    {
                        "sector": "半导体",
                        "score": 85,
                        "reason": "订单超预期，提升景气度。",
                        "companies": ["中芯国际"],
                    },
                    {
                        "sector": "消费电子",
                        "score": 40,
                        "reason": "新品拉货预期上修。",
                        "companies": None,
                    },
                ]
            }
        )

        self.assertEqual(len(model.sector_analyses or []), 2)
        self.assertEqual(model.sector_analyses[0].sector, "半导体")


class LLMParsingTests(unittest.TestCase):
    def test_parse_new_structure(self):
        payload = _coerce_payload_shape(
            {
                "sector_analyses": [
                    {
                        "sector": "半导体",
                        "score": "90",
                        "reason": "利好",
                        "companies": ["中芯国际", "中芯国际"],
                    }
                ]
            },
            content="芯片订单超预期",
            subjects=["半导体"],
        )
        self.assertEqual(payload.sector_analyses[0].score, 90)
        self.assertEqual(payload.sector_analyses[0].companies, ["中芯国际"])

    def test_parse_legacy_structure_backward_compatible(self):
        payload = _coerce_payload_shape(
            {
                "score": 70,
                "reason": "政策刺激",
                "sectors": ["半导体", "半导体"],
                "companies": ["中芯国际"],
            },
            content="政策刺激芯片产业",
            subjects=[],
        )
        self.assertEqual(len(payload.sector_analyses or []), 1)
        self.assertEqual(payload.sector_analyses[0].sector, "半导体")
        self.assertEqual(payload.sector_analyses[0].score, 70)


class RepositoryNormalizationTests(unittest.TestCase):
    def test_investment_repo_normalize_sector_scores(self):
        repo = SectorInvestmentPreferenceRankingRepository.__new__(SectorInvestmentPreferenceRankingRepository)
        normalized = repo._normalize_sector_scores(
            {
                "sector_analyses": [
                    {"sector": "半导体", "score": 80},
                    {"sector": "半导体", "score": 60},
                    {"sector": "消费电子", "score": -30},
                ]
            }
        )
        self.assertEqual(normalized, [{"sector": "半导体", "score": 80.0}, {"sector": "消费电子", "score": -30.0}])

    def test_sector_3d_repo_normalize_sector_items_legacy(self):
        normalized = Sector3DDailySummaryRepository._normalize_sector_items(
            {
                "score": 55,
                "sectors": ["半导体", "消费电子", "半导体"],
            }
        )
        self.assertEqual(
            normalized,
            [
                {"sector": "半导体", "score": 55.0},
                {"sector": "消费电子", "score": 55.0},
            ],
        )

if __name__ == "__main__":
    unittest.main()
