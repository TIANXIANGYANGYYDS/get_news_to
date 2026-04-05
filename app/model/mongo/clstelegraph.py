from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class CLSTelegraphLLMAnalysis(BaseModel):
    score: int = Field(..., ge=-100, le=100, description="利好利空分数，范围 -100~100")
    reason: str = Field(..., min_length=1, description="分析理由")
    companies: Optional[List[str]] = Field(default=None, description="涉及公司，没有则为None")
    sectors: Optional[List[str]] = Field(default=None, description="涉及板块，没有则为None")

class CLSTelegraph(BaseModel):
    __tablename__ = "cls_telegraphs"

    event_id: str = Field(..., description="电报唯一ID，用于去重")
    publish_ts: int = Field(..., description="发布时间戳")
    publish_time: Optional[str] = Field(default=None, description="发布时间 HH:MM:SS")
    subjects: List[str] = Field(default_factory=list, description="主题标签")
    title: str = Field(..., description="标题")
    content: str = Field(..., description="正文")
    source: Literal["cls", "jin10"] = Field(default="cls", description="资讯来源")

    llm_analysis: Optional[CLSTelegraphLLMAnalysis] = Field(
        default=None,
        description="LLM分析结果",
    )