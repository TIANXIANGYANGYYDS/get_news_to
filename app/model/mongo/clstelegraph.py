from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class CLSTelegraphSectorAnalysis(BaseModel):
    sector: str = Field(..., min_length=1, description="行业板块名称")
    score: int = Field(..., ge=-100, le=100, description="该行业板块的利好利空分数，范围 -100~100")
    reason: str = Field(..., min_length=1, description="该行业板块的分析理由")
    companies: Optional[List[str]] = Field(
        default=None,
        description="该行业板块下涉及的公司，没有则为None",
    )


class CLSTelegraphLLMAnalysis(BaseModel):
    sector_analyses: Optional[List[CLSTelegraphSectorAnalysis]] = Field(
        default=None,
        description="逐行业板块分析结果，没有则为None",
    )

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
