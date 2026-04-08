from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.llm.prompt_builder.news_pipeline_prompt_builder import (
    CLASSIFICATION_SYSTEM_PROMPT,
    FACT_EXTRACTION_SYSTEM_PROMPT,
    SCORING_SYSTEM_PROMPT,
    build_classification_user_prompt,
    build_fact_extraction_user_prompt,
    build_scoring_user_prompt,
)
from app.repo.concept_taxonomy_repository import ConceptTaxonomyRepository
from app.schema.news_analysis_pipeline import (
    ClassificationResult,
    FactExtractionResult,
    InvestmentScoringResult,
    LLMStageError,
    NewsAnalysisPipelineResult,
    NewsInputPayload,
    ProcessingStage,
    StageMeta,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


class NewsAnalysisPipelineService:
    def __init__(
        self,
        *,
        taxonomy_repository: ConceptTaxonomyRepository | None = None,
        model_name: str = "qwen-plus",
    ):
        self.taxonomy_repository = taxonomy_repository or ConceptTaxonomyRepository()
        self.model_name = model_name
        self.client = OpenAI(
            api_key=settings.api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            timeout=90.0,
        )

    def run(self, payload: NewsInputPayload) -> NewsAnalysisPipelineResult:
        result = NewsAnalysisPipelineResult(input_payload=payload)

        fact_data = self._run_stage(
            stage=ProcessingStage.FACT_EXTRACTION,
            result=result,
            schema=FactExtractionResult,
            system_prompt=FACT_EXTRACTION_SYSTEM_PROMPT,
            user_prompt=build_fact_extraction_user_prompt(payload),
        )
        if fact_data is None:
            return result

        recalled = self.taxonomy_repository.recall_candidates(
            title=payload.title,
            content=payload.content,
            subjects=payload.subjects,
        )
        concept_candidates = [x.concept for x in recalled]
        industry_candidates = sorted({x.board for x in recalled if x.board})

        classification_data = self._run_stage(
            stage=ProcessingStage.STANDARD_CLASSIFICATION,
            result=result,
            schema=ClassificationResult,
            system_prompt=CLASSIFICATION_SYSTEM_PROMPT,
            user_prompt=build_classification_user_prompt(
                payload=payload,
                fact_output=fact_data.model_dump(),
                event_type_candidates=self.taxonomy_repository.event_types(),
                concept_candidates=concept_candidates,
                industry_candidates=industry_candidates,
                concept_recall_context=[c.model_dump() for c in recalled],
            ),
        )
        if classification_data is None:
            return result

        scoring_data = self._run_stage(
            stage=ProcessingStage.INVESTMENT_SCORING,
            result=result,
            schema=InvestmentScoringResult,
            system_prompt=SCORING_SYSTEM_PROMPT,
            user_prompt=build_scoring_user_prompt(
                fact_output=fact_data.model_dump(),
                classification_output=classification_data.model_dump(),
            ),
        )

        result.fact_extraction = fact_data
        result.standard_classification = classification_data
        result.investment_scoring = scoring_data
        return result

    def _run_stage(
        self,
        *,
        stage: ProcessingStage,
        result: NewsAnalysisPipelineResult,
        schema: type[ModelT],
        system_prompt: str,
        user_prompt: str,
    ) -> ModelT | None:
        start = datetime.now(timezone.utc)
        raw_text = ""
        try:
            raw_text = self._chat(system_prompt=system_prompt, user_prompt=user_prompt)
            parsed = schema.model_validate(json.loads(raw_text))
            finish = datetime.now(timezone.utc)
            result.stage_meta[stage] = StageMeta(
                model=self.model_name,
                started_at=start,
                finished_at=finish,
                latency_ms=int((finish - start).total_seconds() * 1000),
            )
            return parsed
        except json.JSONDecodeError as exc:
            result.errors.append(
                LLMStageError(
                    stage=stage,
                    code="invalid_json",
                    message=f"JSON 解析失败: {exc}",
                    raw_text=raw_text,
                    retriable=True,
                )
            )
        except ValidationError as exc:
            result.errors.append(
                LLMStageError(
                    stage=stage,
                    code="schema_validation_failed",
                    message=str(exc),
                    raw_text=raw_text,
                    retriable=True,
                )
            )
        except Exception as exc:  # noqa: BLE001
            result.errors.append(
                LLMStageError(
                    stage=stage,
                    code="llm_call_failed",
                    message=str(exc),
                    raw_text=raw_text,
                    retriable=True,
                )
            )

        return None

    def _chat(self, *, system_prompt: str, user_prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model_name,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return (response.choices[0].message.content or "").strip()
