from typing import List, Optional, Dict, Any
from pydantic import Field,BaseModel


class CLSTelegraph(BaseModel):
    __tablename__ = "cls_telegraphs"

    event_id: str = Field(..., description="电报唯一ID，用于去重")
    publish_ts: int = Field(..., description="发布时间戳")
    publish_time: Optional[str] = Field(default=None, description="发布时间 HH:MM:SS")
    subjects: List[str] = Field(default_factory=list, description="主题标签")
    content: str = Field(..., description="标题+正文合并后的内容")

    llm_analysis: Optional[Dict[str, Any]] = Field(
        default=None,
        description="LLM分析结果对象，包含 score/reason/companies?/sectors",
    )