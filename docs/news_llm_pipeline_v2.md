# News LLM 三阶段改造方案（最小必要改动）

## 1. 整体架构

```text
news input(title/content/publish_time/source/subjects)
  -> Stage 1 事实抽取 (严格 JSON + schema)
  -> 候选召回(关键词/subject/board/alias)
  -> Stage 2 标准化分类(仅可在候选内选择)
  -> Stage 3 投资价值评分(多维子分 + 公式 + 置信度/拒答)
  -> projection: 兼容旧 llm_analysis.score/reason + 新结构化字段
```

核心原则：
- 不改主流程队列/抓取/入库路径，只替换单条分析函数。
- 保留旧字段 `score/reason/sectors/companies`，新增 `confidence/is_actionable/reject_reason` 与三阶段原始结构。
- 任一阶段失败都返回结构化错误，避免流程崩溃。

## 2. 模块划分

- `handler`: `NewsPipelineHandler`
  - 面向主流程/路由，负责 orchestrate 和最终投影。
- `service`: `NewsAnalysisPipelineService`
  - 三阶段串行执行、LLM 调用、schema 校验、阶段元信息记录。
- `schema`: `news_analysis_pipeline.py`
  - 定义每阶段输入输出、错误模型、落库投影模型。
- `prompt builder`: `news_pipeline_prompt_builder.py`
  - 维护三阶段系统 prompt + user prompt 组装。
- `repository`: `ConceptTaxonomyRepository`
  - 提供固定 event type / concept taxonomy，执行候选召回。

## 3. 阶段职责边界

### Stage 1 事实抽取
- 仅处理摘要/事件/实体/事实证据/行动信号/新颖度/时效。
- 严禁输出投资建议、板块主线、买卖结论。

### Stage 2 标准化分类
- 输入 stage1 结果 + 程序候选集。
- 仅允许从 `event_type_candidates`、`concept_candidates`、`industry_candidates` 选择。
- 输出 `mapping_reason` 用于追溯。

### Stage 3 投资价值评分
- 输出六维子分 + 原因。
- 固定公式产出 `final_score`。
- 输出 `confidence/is_actionable/reject_reason`。

## 4. 数据库存储建议（兼容旧表 cls_telegraphs）

继续写入 `llm_analysis`，新增字段：
- `llm_analysis.pipeline_version`
- `llm_analysis.confidence`
- `llm_analysis.is_actionable`
- `llm_analysis.reject_reason`
- `llm_analysis.fact_extraction`
- `llm_analysis.standard_classification`
- `llm_analysis.investment_scoring`
- `llm_analysis.errors`

可选新增索引：
- `llm_analysis.is_actionable`
- `llm_analysis.standard_classification.primary_industry`
- `llm_analysis.investment_scoring.final_score`

## 5. 与盘前主流程衔接

现有流程不变：
- crawler -> queue -> `analyze_single_telegraph` -> upsert -> card。

替换点：
- 将 `analyze_cls_telegraph` 改为 `analyze_cls_telegraph_v2`。

衔接规则：
- `score` 由 `final_score` 映射到 `[-100, 100]`。
- `is_actionable=false` 时强制 `score=0`，避免误交易。
- 聚合时优先使用 `standard_classification.primary_concept/primary_industry + investment_scoring`。

## 6. 盘前主线聚合输入建议

聚合输入字段：
- 主题：`primary_concept`、`secondary_concepts`、`primary_industry`
- 强度：`final_score`、`theme_strength_score.score`
- 可交易性：`tradability_score.score`、`is_actionable`
- 可信度：`confidence`
- 风险：`risk_score.score`
- 时间维：`time_sensitivity`

可做加权示例：
- theme_heat = Σ(final_score * confidence * actionable_factor)

## 7. 回测与评估预留字段

建议保留：
- `event_id/source/publish_time`
- `stage_meta.latency_ms`
- `pipeline_version/model_name`
- `confidence/is_actionable/reject_reason`
- 全部子分与 reason
- `mapping_reason`
- `errors.code`

用于评估：
- 命中率分层：`confidence` bucket
- 题材识别稳定性：`primary_concept` 漂移率
- 交易收益归因：`final_score` vs 次日/3日收益
- 拒答质量：`is_actionable=false` 的噪声过滤率
