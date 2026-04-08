from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ProcessingStage(str, Enum):
    FACT_EXTRACTION = "fact_extraction"
    STANDARD_CLASSIFICATION = "standard_classification"
    INVESTMENT_SCORING = "investment_scoring"


class LLMStageError(BaseModel):
    stage: ProcessingStage
    code: str = Field(..., description="稳定错误码，用于统计")
    message: str
    raw_text: str | None = None
    retriable: bool = True


class NewsInputPayload(BaseModel):
    event_id: str | None = None
    title: str = ""
    content: str = Field(..., min_length=1)
    publish_time: str | None = None
    source: str = "cls"
    subjects: list[str] = Field(default_factory=list)


class EntityItem(BaseModel):
    name: str
    entity_type: Literal["company", "industry", "concept", "organization", "person", "region", "product", "policy"]
    mention: str | None = None


class CoreFactItem(BaseModel):
    fact: str
    evidence: str


class ActionSignalItem(BaseModel):
    signal: str
    direction: Literal["positive", "negative", "neutral"]


class FactExtractionResult(BaseModel):
    summary: str = Field(..., min_length=1)
    event_type: str = Field(..., min_length=1)
    entities: list[EntityItem] = Field(default_factory=list)
    core_facts: list[CoreFactItem] = Field(default_factory=list)
    action_signals: list[ActionSignalItem] = Field(default_factory=list)
    novelty: Literal["high", "medium", "low"]
    time_sensitivity: Literal["intraday", "1_3_days", "medium_term", "low"]


class CandidateConcept(BaseModel):
    concept: str
    subject: str | None = None
    board: str | None = None
    alias_hit: str | None = None
    keyword_hit: str | None = None


class ClassificationResult(BaseModel):
    event_type: str
    primary_concept: str | None = None
    secondary_concepts: list[str] = Field(default_factory=list)
    primary_industry: str | None = None
    related_companies: list[str] = Field(default_factory=list)
    mapping_reason: str


class ScoredReason(BaseModel):
    score: int = Field(..., ge=0, le=100)
    reason: str


class InvestmentScoringResult(BaseModel):
    novelty_score: ScoredReason
    theme_strength_score: ScoredReason
    stock_mapping_score: ScoredReason
    sustainability_score: ScoredReason
    tradability_score: ScoredReason
    risk_score: ScoredReason
    final_score: float = Field(..., ge=0, le=100)
    confidence: float = Field(..., ge=0, le=1)
    is_actionable: bool
    reject_reason: str | None = None


class StageMeta(BaseModel):
    model: str
    started_at: datetime
    finished_at: datetime
    latency_ms: int


class NewsAnalysisPipelineResult(BaseModel):
    pipeline_version: str = "v2"
    input_payload: NewsInputPayload
    fact_extraction: FactExtractionResult | None = None
    standard_classification: ClassificationResult | None = None
    investment_scoring: InvestmentScoringResult | None = None
    stage_meta: dict[ProcessingStage, StageMeta] = Field(default_factory=dict)
    errors: list[LLMStageError] = Field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return not self.errors and self.investment_scoring is not None


class PipelineStorageProjection(BaseModel):
    score: int = Field(..., ge=-100, le=100)
    reason: str
    companies: list[str] | None = None
    sectors: list[str] | None = None
    confidence: float = Field(0.0, ge=0, le=1)
    is_actionable: bool = False
    reject_reason: str | None = None
    pipeline_version: str = "v2"
    fact_extraction: dict[str, Any] | None = None
    standard_classification: dict[str, Any] | None = None
    investment_scoring: dict[str, Any] | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_reason(self):
        if not self.reason:
            self.reason = "无有效分析结论"
        return self
