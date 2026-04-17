from __future__ import annotations

from domain.models.pipeline_models import MorningAnalysisOutput, MorningReadingPayload
from shared.base.llm import BaseLLMClient


class MorningMarketAnalyzer:
    def __init__(self, llm_client: BaseLLMClient):
        self.llm_client = llm_client

    def analyze(self, payload: MorningReadingPayload) -> MorningAnalysisOutput:
        # keep deterministic fallback for reliability
        head = payload.sections.get("head", "")
        major = payload.sections.get("major_news", "")
        preview = "\n".join([x for x in [head, major] if x])[:1500]
        if not self.llm_client.model_name:
            return MorningAnalysisOutput(summary_text=preview or payload.raw_content[:500], key_sectors=[])

        prompt = (
            "你是A股盘前分析助手。请基于输入内容输出JSON，格式: "
            '{"summary_text":"...","key_sectors":["..."]}。\n'
            f"输入内容:\n{preview}"
        )
        try:
            result = self.llm_client.complete_json(prompt)
            return MorningAnalysisOutput.from_dict(result)
        except Exception:
            return MorningAnalysisOutput(summary_text=preview or payload.raw_content[:500], key_sectors=[])
