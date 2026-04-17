from dataclasses import dataclass, field

from infrastructure.repositories.news_repository import NewsRepository


@dataclass
class SectorAggregationResult:
    sectors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"sectors": self.sectors}


class SectorAggregationService:
    def __init__(self, news_repository: NewsRepository):
        self.news_repository = news_repository

    async def aggregate_latest(self, *, limit: int = 200) -> SectorAggregationResult:
        documents = await self.news_repository.list_latest(limit=limit)
        counter: dict[str, int] = {}
        for document in documents:
            analysis = document.analysis
            if analysis is None:
                continue
            for sector_name in analysis.sector_names:
                counter[sector_name] = counter.get(sector_name, 0) + 1

        sectors = [{"sector_name": name, "heat_score": score} for name, score in sorted(counter.items(), key=lambda x: x[1], reverse=True)[:20]]
        return SectorAggregationResult(sectors=sectors)
