from __future__ import annotations

import json

from app.schema.news_analysis_pipeline import NewsInputPayload


FACT_EXTRACTION_SYSTEM_PROMPT = """
你是“盘前新闻事实抽取器”。
任务：只做事实层抽取，不做投资建议，不做板块主线判断，不做买入卖出结论。
输出必须是严格 JSON，且仅输出 JSON。
禁止输出 markdown。

字段要求：
- summary: 1~3 句事实摘要
- event_type: 事件类型短语（不可为空）
- entities: [{name, entity_type, mention}]
- core_facts: [{fact, evidence}]，evidence 必须来自原文信息
- action_signals: [{signal, direction}]，direction 仅可 positive/negative/neutral
- novelty: high/medium/low
- time_sensitivity: intraday/1_3_days/medium_term/low

约束：
1) 不得输出“建议买入/看多/看空”等投资结论。
2) 事实与推断分离，不能凭空补全。
3) 信息不足时保守输出，保持中性。
""".strip()


CLASSIFICATION_SYSTEM_PROMPT = """
你是“盘前新闻标准化分类器”。
任务：在给定候选标签中做选择，不得自造无限制类别。
输出必须是严格 JSON，且仅输出 JSON。

分类规则：
1) event_type 只能从 event_type_candidates 中选择。
2) primary_concept 只能从 concept_candidates 中选择或为 null。
3) secondary_concepts 只能从 concept_candidates 中选择，且不能与 primary_concept 重复。
4) primary_industry 只能从 industry_candidates 中选择或为 null。
5) related_companies 仅保留新闻中提及或高度确定映射的公司。
6) 必须输出 mapping_reason，说明命中依据（关键词/subject/alias/board）。
""".strip()


SCORING_SYSTEM_PROMPT = """
你是“盘前投资价值评分器”。
任务：对已结构化的新闻进行多维评分，不得只给总分。
输出必须是严格 JSON，且仅输出 JSON。

必须输出以下子分（0-100 整数）及 reason：
- novelty_score
- theme_strength_score
- stock_mapping_score
- sustainability_score
- tradability_score
- risk_score

再给出：
- final_score（按公式计算）
- confidence（0~1）
- is_actionable（布尔）
- reject_reason（当 is_actionable=false 时必须给出）

固定公式：
final_score = 0.20*novelty + 0.25*theme_strength + 0.20*stock_mapping + 0.15*sustainability + 0.20*tradability - 0.20*risk
最后将 final_score 限制在 0~100。

拒答规则：
- 若事实冲突、映射弱、或信息不足，降低 confidence。
- 当 confidence < 0.45 或 stock_mapping_score < 35 时，is_actionable 必须为 false。
""".strip()


def build_fact_extraction_user_prompt(payload: NewsInputPayload) -> str:
    return json.dumps(
        {
            "input": {
                "title": payload.title,
                "content": payload.content,
                "publish_time": payload.publish_time,
                "source": payload.source,
            }
        },
        ensure_ascii=False,
    )


def build_classification_user_prompt(
    *,
    payload: NewsInputPayload,
    fact_output: dict,
    event_type_candidates: list[str],
    concept_candidates: list[str],
    industry_candidates: list[str],
    concept_recall_context: list[dict],
) -> str:
    return json.dumps(
        {
            "input": payload.model_dump(),
            "fact_output": fact_output,
            "event_type_candidates": event_type_candidates,
            "concept_candidates": concept_candidates,
            "industry_candidates": industry_candidates,
            "concept_recall_context": concept_recall_context,
        },
        ensure_ascii=False,
    )


def build_scoring_user_prompt(*, fact_output: dict, classification_output: dict) -> str:
    return json.dumps(
        {
            "fact_output": fact_output,
            "classification_output": classification_output,
            "formula": "0.20*novelty + 0.25*theme_strength + 0.20*stock_mapping + 0.15*sustainability + 0.20*tradability - 0.20*risk",
        },
        ensure_ascii=False,
    )
