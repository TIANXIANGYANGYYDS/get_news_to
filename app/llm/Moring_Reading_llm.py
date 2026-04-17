"""LEGACY wrapper (deprecated).

Use `infrastructure.llm.morning_market_analyzer.MorningMarketAnalyzer` instead.
"""

from domain.models.pipeline_models import MorningReadingPayload
from infrastructure.llm.morning_market_analyzer import MorningMarketAnalyzer
from infrastructure.llm.openai_client import OpenAILLMClient
from shared.config.settings import settings


def analyze_morning_data(morning_data: dict, prev_day_review: str = "", investment_preference_ranking=None, market_heat_ranking=None) -> str:
    payload = MorningReadingPayload.from_dict(morning_data)
    client = OpenAILLMClient(
        api_key=settings.llm.api_key,
        base_url=settings.llm.base_url,
        model_name=settings.llm.model_name,
        timeout_seconds=settings.llm.timeout_seconds,
        max_retries=settings.llm.max_retries,
    )
    analyzer = MorningMarketAnalyzer(client)
    return analyzer.analyze(payload).summary_text
