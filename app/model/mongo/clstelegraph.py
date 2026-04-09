from typing import List, Optional, Literal
from pydantic import BaseModel, Field, model_validator


class SectorScore(BaseModel):
    sector: str = Field(..., min_length=1, description="板块名称")
    score: int = Field(..., ge=-100, le=100, description="该板块对应分数，范围 -100~100")


class CLSTelegraphLLMAnalysis(BaseModel):
    score: int = Field(..., ge=-100, le=100, description="整条电报的总分，范围 -100~100")
    reason: str = Field(..., min_length=1, description="分析理由")
    companies: Optional[List[str]] = Field(default=None, description="涉及公司，没有则为None")
    sectors: Optional[List[str]] = Field(default=None, description="涉及板块，没有则为None")
    sector_scores: Optional[List[SectorScore]] = Field(
        default=None,
        description="分板块打分列表，每个板块对应一个分数",
    )

    @model_validator(mode="after")
    def sync_sectors_with_sector_scores(self):
        normalized: list[SectorScore] = []
        seen = set()

        for item in self.sector_scores or []:
            sector = (item.sector or "").strip()
            if not sector or sector in seen:
                continue
            seen.add(sector)
            normalized.append(SectorScore(sector=sector, score=int(item.score)))

        if normalized:
            self.sector_scores = normalized
            self.sectors = [item.sector for item in normalized]
        elif self.sectors:
            normalized = []
            for sector in self.sectors:
                text = (sector or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                normalized.append(SectorScore(sector=text, score=int(self.score)))

            self.sector_scores = normalized or None
            self.sectors = [item.sector for item in normalized] if normalized else None
        else:
            self.sector_scores = None
            self.sectors = None

        return self


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
