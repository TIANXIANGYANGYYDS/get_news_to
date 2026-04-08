from __future__ import annotations

from app.schema.news_analysis_pipeline import (
    NewsInputPayload,
    PipelineStorageProjection,
)
from app.services.news_pipeline_service import NewsAnalysisPipelineService


class NewsPipelineHandler:
    def __init__(self, service: NewsAnalysisPipelineService | None = None):
        self.service = service or NewsAnalysisPipelineService()

    def analyze(self, payload: NewsInputPayload) -> PipelineStorageProjection:
        result = self.service.run(payload)

        if result.errors:
            return PipelineStorageProjection(
                score=0,
                reason=f"多阶段分析失败: {result.errors[0].message}",
                companies=None,
                sectors=None,
                confidence=0,
                is_actionable=False,
                reject_reason="pipeline_error",
                pipeline_version=result.pipeline_version,
                fact_extraction=result.fact_extraction.model_dump() if result.fact_extraction else None,
                standard_classification=result.standard_classification.model_dump() if result.standard_classification else None,
                investment_scoring=result.investment_scoring.model_dump() if result.investment_scoring else None,
                errors=[e.model_dump() for e in result.errors],
            )

        scoring = result.investment_scoring
        classification = result.standard_classification
        assert scoring is not None
        assert classification is not None

        directional_score = int(round((scoring.final_score * 2) - 100))
        if not scoring.is_actionable:
            directional_score = 0

        return PipelineStorageProjection(
            score=directional_score,
            reason=scoring.reject_reason or "多维评分通过，可进入盘前主线聚合。",
            companies=classification.related_companies or None,
            sectors=[classification.primary_industry] if classification.primary_industry else None,
            confidence=scoring.confidence,
            is_actionable=scoring.is_actionable,
            reject_reason=scoring.reject_reason,
            pipeline_version=result.pipeline_version,
            fact_extraction=result.fact_extraction.model_dump(),
            standard_classification=classification.model_dump(),
            investment_scoring=scoring.model_dump(),
            errors=[],
        )
