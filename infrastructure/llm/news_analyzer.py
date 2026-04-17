import json

from domain.models.analysis_models import LLMAnalysisRequest, LLMAnalysisResult
from shared.base.llm import BaseLLMAnalyzer
from shared.base.model import ModelBase


class NewsLLMAnalyzer(BaseLLMAnalyzer):
    output_model = LLMAnalysisResult

    def build_prompt(self, payload: ModelBase) -> str:
        request = LLMAnalysisRequest.from_dict(payload.to_dict())
        schema_hint = {
            "score": "int(-100..100)",
            "reason": "string",
            "sector_names": ["string"],
            "company_names": ["string"],
            "is_fallback": False,
            "error_message": None,
        }
        return (
            "你是A股新闻分析助手。只输出JSON。\n"
            f"输入: {json.dumps(request.to_dict(), ensure_ascii=False)}\n"
            f"输出schema: {json.dumps(schema_hint, ensure_ascii=False)}"
        )

    def fallback(self, payload: ModelBase, error: str) -> LLMAnalysisResult:
        return LLMAnalysisResult(
            score=0,
            reason="LLM fallback",
            sector_names=[],
            company_names=[],
            is_fallback=True,
            error_message=error,
        )
