from __future__ import annotations

from dataclasses import dataclass

from app.schema.news_analysis_pipeline import CandidateConcept


@dataclass(frozen=True)
class ConceptTaxonomy:
    concept: str
    industry: str
    aliases: tuple[str, ...]
    keywords: tuple[str, ...]


DEFAULT_EVENT_TYPES = [
    "政策监管",
    "产业进展",
    "公司经营",
    "业绩财报",
    "交易异动",
    "宏观流动性",
    "突发风险",
    "海外映射",
    "其他",
]


DEFAULT_TAXONOMY: list[ConceptTaxonomy] = [
    ConceptTaxonomy("人工智能", "软件开发", ("AI", "AIGC", "大模型"), ("算力", "模型", "推理", "训练")),
    ConceptTaxonomy("机器人", "自动化设备", ("人形机器人",), ("减速器", "伺服", "机器视觉")),
    ConceptTaxonomy("半导体", "半导体", ("芯片", "晶圆"), ("封测", "先进制程", "存储")),
    ConceptTaxonomy("低空经济", "通用设备", ("eVTOL",), ("无人机", "空管", "通航")),
    ConceptTaxonomy("新能源车", "汽车整车", ("电动车", "EV"), ("整车", "电池", "充电")),
    ConceptTaxonomy("光伏", "光伏设备", ("太阳能",), ("硅片", "组件", "逆变器")),
    ConceptTaxonomy("军工", "军工装备", ("国防",), ("导弹", "卫星", "装备")),
    ConceptTaxonomy("创新药", "化学制药", ("ADC", "GLP-1"), ("临床", "获批", "医保")),
]


class ConceptTaxonomyRepository:
    def __init__(self, taxonomy: list[ConceptTaxonomy] | None = None):
        self.taxonomy = taxonomy or DEFAULT_TAXONOMY

    def event_types(self) -> list[str]:
        return DEFAULT_EVENT_TYPES

    def recall_candidates(self, *, title: str, content: str, subjects: list[str]) -> list[CandidateConcept]:
        text = f"{title}\n{content}\n{' '.join(subjects)}".lower()
        candidates: list[CandidateConcept] = []

        for item in self.taxonomy:
            subject_hit = next((s for s in subjects if item.concept in s), None)
            alias_hit = next((a for a in item.aliases if a.lower() in text), None)
            keyword_hit = next((k for k in item.keywords if k.lower() in text), None)

            if subject_hit or alias_hit or keyword_hit:
                candidates.append(
                    CandidateConcept(
                        concept=item.concept,
                        subject=subject_hit,
                        board=item.industry,
                        alias_hit=alias_hit,
                        keyword_hit=keyword_hit,
                    )
                )

        return candidates[:12]
