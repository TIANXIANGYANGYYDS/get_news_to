from domain.models.analysis_models import LLMAnalysisRequest, LLMAnalysisResult
from domain.models.news_models import NewsEvent
from infrastructure.llm.news_analyzer import NewsLLMAnalyzer


class NewsAnalysisService:
    def __init__(self, analyzer: NewsLLMAnalyzer):
        self.analyzer = analyzer

    def analyze(self, event: NewsEvent) -> LLMAnalysisResult:
        request = LLMAnalysisRequest(
            event_id=event.event_id,
            title=event.title,
            content=event.content,
            subject_names=event.subject_names,
        )
        return self.analyzer.analyze(request)
