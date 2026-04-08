from __future__ import annotations

from typing import Optional

from app.handler.news_pipeline_handler import NewsPipelineHandler
from app.model import CLSTelegraphLLMAnalysis
from app.schema.news_analysis_pipeline import NewsInputPayload


def analyze_cls_telegraph_v2(
    content: str,
    subjects: Optional[list[str]] = None,
    *,
    title: str = "",
    publish_time: str | None = None,
    source: str = "cls",
    event_id: str | None = None,
) -> CLSTelegraphLLMAnalysis:
    payload = NewsInputPayload(
        event_id=event_id,
        title=title,
        content=content,
        publish_time=publish_time,
        source=source,
        subjects=subjects or [],
    )

    projection = NewsPipelineHandler().analyze(payload)

    return CLSTelegraphLLMAnalysis(
        score=projection.score,
        reason=projection.reason,
        companies=projection.companies,
        sectors=projection.sectors,
        confidence=projection.confidence,
        is_actionable=projection.is_actionable,
        reject_reason=projection.reject_reason,
        pipeline_version=projection.pipeline_version,
        fact_extraction=projection.fact_extraction,
        standard_classification=projection.standard_classification,
        investment_scoring=projection.investment_scoring,
        errors=projection.errors,
    )
