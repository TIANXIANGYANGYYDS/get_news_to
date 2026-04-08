from typing import Any, List, Optional, Literal
from pydantic import BaseModel, Field


class CLSTelegraphLLMAnalysis(BaseModel):
    score: int = Field(..., ge=-100, le=100, description="利好利空分数，范围 -100~100")
    reason: str = Field(..., min_length=1, description="分析理由")
    companies: Optional[List[str]] = Field(default=None, description="涉及公司，没有则为None")
    sectors: Optional[List[str]] = Field(default=None, description="涉及板块，没有则为None")

    confidence: float = Field(default=0.0, ge=0, le=1, description="评分置信度")
    is_actionable: bool = Field(default=False, description="是否可执行")
    reject_reason: Optional[str] = Field(default=None, description="不可执行的原因")
    pipeline_version: str = Field(default="v2", description="分析流水线版本")

    fact_extraction: Optional[dict[str, Any]] = Field(default=None, description="阶段一输出")
    standard_classification: Optional[dict[str, Any]] = Field(default=None, description="阶段二输出")
    investment_scoring: Optional[dict[str, Any]] = Field(default=None, description="阶段三输出")
    errors: List[dict[str, Any]] = Field(default_factory=list, description="结构化错误")


class CLSTelegraph(BaseModel):
    __tablename__ = "cls_telegraphs"

    event_id: str = Field(..., description="电报唯一ID，用于去重")
    publish_ts: int = Field(..., description="发布时间戳")
    publish_time: Optional[str] = Field(default=None, description="发布时间 HH:MM:SS")
    subjects: List[str] = Field(default_factory=list, description="主题标签")
    title: str = Field(..., description="标题")
    content: str = Field(..., description="正文")
    source: Literal["cls", "jin10", "10jqka"] = Field(default="cls", description="来源")

    llm_analysis: Optional[CLSTelegraphLLMAnalysis] = Field(
        default=None,
        description="LLM分析结果",
    )
