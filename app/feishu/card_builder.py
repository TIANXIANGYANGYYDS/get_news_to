from typing import Any, Iterable, Optional

from app.model import CLSTelegraph, CLSTelegraphLLMAnalysis


class CardBuilder:
    def build_daily_test_card(self):
        return {
            "config": {"wide_screen_mode": True},
            "elements": [
                {
                    "tag": "markdown",
                    "content": "这是测试卡片",
                }
            ],
        }

    def build_daily_market_analysis_card(
        self,
        date: str,
        analysis_text: str,
        morning_data: dict,
    ) -> dict:
        source = morning_data.get("source", "unknown")
        content = self._format_market_mainlines(analysis_text)

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"盘前主线梳理 {date or ''}",
                }
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"**数据源**：{source}\n**日期**：{date or '未知'}",
                },
                {
                    "tag": "hr",
                },
                {
                    "tag": "markdown",
                    "content": content,
                },
            ],
        }

    def _format_market_mainlines(self, analysis_text: str) -> str:
        if not analysis_text:
            return "暂无盘前主线分析结果"

        lines = [line.strip() for line in analysis_text.splitlines() if line.strip()]
        filtered_lines = []

        for line in lines:
            if line.startswith(("第一主线：", "第二主线：", "第三主线：", "第四主线：", "第五主线：")):
                filtered_lines.append(f"**{line}**")
            elif line.startswith("理由："):
                filtered_lines.append(f"> {line}")

        if not filtered_lines:
            return analysis_text[:2000]

        return "\n\n".join(filtered_lines)

    @staticmethod
    def _escape_lark_md(text: str) -> str:
        text = (text or "").strip()
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    @staticmethod
    def _join_list(items) -> str:
        if not items:
            return "None"
        return "、".join([str(x).strip() for x in items if str(x).strip()]) or "None"

    @staticmethod
    def _safe_get(obj: Any, key: str, default=None):
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    @staticmethod
    def _source_display_name(source: Optional[str]) -> str:
        mapping = {
            "cls": "财联社",
            "jin10": "金十",
            "10jqka": "同花顺",
        }
        return mapping.get((source or "").strip().lower(), source or "其他数据源")

    @staticmethod
    def _format_rank_value(value: Any) -> str:
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.2f}".rstrip("0").rstrip(".")
        return str(value)

    def _format_investment_top5_md(self, rows: Optional[Iterable[Any]]) -> str:
        rows = list(rows or [])[:5]
        if not rows:
            return "暂无数据"

        lines = []
        for idx, item in enumerate(rows, start=1):
            name = (
                self._safe_get(item, "sector")
                or self._safe_get(item, "sector_name")
                or self._safe_get(item, "name")
                or self._safe_get(item, "board_name")
                or f"未知板块{idx}"
            )

            score = (
                self._safe_get(item, "score")
                if self._safe_get(item, "score") is not None
                else self._safe_get(item, "total_score")
            )

            if score is None:
                score = (
                    self._safe_get(item, "tendency_score")
                    if self._safe_get(item, "tendency_score") is not None
                    else self._safe_get(item, "score_sum")
                )
                
            if score is None:
                score = self._safe_get(item, "final_score")

            name = self._escape_lark_md(str(name))
            score_text = self._escape_lark_md(self._format_rank_value(score))
            lines.append(f"{idx}. **{name}**：{score_text}")

        return "\n".join(lines)

    def _format_heat_top5_md(self, rows: Optional[Iterable[Any]]) -> str:
        rows = list(rows or [])[:5]
        if not rows:
            return "暂无数据"

        lines = []
        for idx, item in enumerate(rows, start=1):
            name = (
                self._safe_get(item, "sector")
                or self._safe_get(item, "sector_name")
                or self._safe_get(item, "name")
                or self._safe_get(item, "board_name")
                or f"未知板块{idx}"
            )

            heat_score = (
                self._safe_get(item, "hot_score")
                if self._safe_get(item, "hot_score") is not None
                else self._safe_get(item, "heat_score")
            )
            if heat_score is None:
                heat_score = self._safe_get(item, "score")
            if heat_score is None:
                heat_score = self._safe_get(item, "final_score")

            news_count = (
                self._safe_get(item, "news_count")
                if self._safe_get(item, "news_count") is not None
                else self._safe_get(item, "count")
            )

            name = self._escape_lark_md(str(name))

            parts = []
            if heat_score is not None:
                parts.append(f"热度 {self._escape_lark_md(self._format_rank_value(heat_score))}")
            if news_count is not None:
                parts.append(f"资讯 {self._escape_lark_md(self._format_rank_value(news_count))} 条")

            detail = "｜".join(parts) if parts else "-"
            lines.append(f"{idx}. **{name}**：{detail}")

        return "\n".join(lines)

    def build_telegraph_insert_card(
        self,
        row: CLSTelegraph,
        investment_top5: Optional[Iterable[Any]] = None,
        heat_top5: Optional[Iterable[Any]] = None,
    ) -> dict:
        llm_analysis = self._safe_get(row, "llm_analysis", None) or {}

        score = int(self._safe_get(llm_analysis, "score", 0) or 0)
        reason = self._escape_lark_md(self._safe_get(llm_analysis, "reason", "-") or "-")
        companies = self._escape_lark_md(
            self._join_list(self._safe_get(llm_analysis, "companies", None))
        )
        sectors = self._escape_lark_md(
            self._join_list(self._safe_get(llm_analysis, "sectors", None))
        )
        subjects = self._escape_lark_md(
            self._join_list(self._safe_get(row, "subjects", None))
        )

        source = self._safe_get(row, "source", "cls")
        source_name = self._escape_lark_md(self._source_display_name(source))

        title = self._safe_get(row, "title", "") or ""
        title = self._escape_lark_md(title.strip()) if title else "-"

        content = self._escape_lark_md((self._safe_get(row, "content", "") or "").strip())
        if len(content) > 800:
            content = content[:800] + "..."

        publish_time = self._escape_lark_md(self._safe_get(row, "publish_time", "-") or "-")
        event_id = self._escape_lark_md(self._safe_get(row, "event_id", "-") or "-")

        if score > 60:
            score_tag = "利好"
            template = "green"
        elif score < -60:
            score_tag = "利空"
            template = "red"
        else:
            score_tag = "中性"
            template = "blue"

        investment_md = self._format_investment_top5_md(investment_top5)
        heat_md = self._format_heat_top5_md(heat_top5)

        elements = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**数据源**：{source_name}\n"
                        f"**发布时间**：{publish_time}\n"
                        f"**主题标签**：{subjects}"
                    ),
                },
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**标题**：{title}\n"
                        f"**事件ID**：{event_id}"
                    ),
                },
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**LLM分数**：{score}\n"
                        f"**涉及公司**：{companies}\n"
                        f"**涉及板块**：{sectors}"
                    ),
                },
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**分析理由**：{reason}",
                },
            },
            # 如需展示原文，把下面打开
            # {"tag": "hr"},
            # {
            #     "tag": "div",
            #     "text": {
            #         "tag": "lark_md",
            #         "content": f"**资讯内容**\n{content}",
            #     },
            # },
            {"tag": "hr"},
            {
                "tag": "column_set",
                "flex_mode": "bisect",
                "columns": [
                    {
                        "tag": "column",
                        "elements": [
                            {
                                "tag": "div",
                                "text": {
                                    "tag": "lark_md",
                                    "content": f"**市场投资倾向榜 Top5**\n{investment_md}",
                                },
                            }
                        ],
                    },
                    {
                        "tag": "column",
                        "elements": [
                            {
                                "tag": "div",
                                "text": {
                                    "tag": "lark_md",
                                    "content": f"**市场热度榜 Top5**\n{heat_md}",
                                },
                            }
                        ],
                    },
                ],
            },
        ]

        return {
            "config": {
                "wide_screen_mode": True,
                "enable_forward": True,
            },
            "header": {
                "template": template,
                "title": {
                    "tag": "plain_text",
                    "content": f"{source_name}资讯入库成功｜{score_tag} {score}",
                },
            },
            "elements": elements,
        }

    def build_cls_telegraph_insert_card(
        self,
        row: CLSTelegraph,
        investment_top5: Optional[Iterable[Any]] = None,
        heat_top5: Optional[Iterable[Any]] = None,
    ) -> dict:
        return self.build_telegraph_insert_card(
            row=row,
            investment_top5=investment_top5,
            heat_top5=heat_top5,
        )