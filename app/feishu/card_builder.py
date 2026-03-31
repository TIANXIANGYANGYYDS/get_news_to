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

    def build_daily_market_analysis_card(self, date: str, analysis_text: str, morning_data: dict) -> dict:
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

    def build_cls_telegraph_insert_card(self, row: dict) -> dict:
        llm_analysis = row.get("llm_analysis") or {}

        score = int(llm_analysis.get("score") or 0)
        reason = self._escape_lark_md(llm_analysis.get("reason") or "-")
        companies = self._escape_lark_md(self._join_list(llm_analysis.get("companies")))
        sectors = self._escape_lark_md(self._join_list(llm_analysis.get("sectors")))
        subjects = self._escape_lark_md(self._join_list(row.get("subjects")))

        content = self._escape_lark_md((row.get("content") or "").strip())
        if len(content) > 800:
            content = content[:800] + "..."

        publish_time = self._escape_lark_md(row.get("publish_time") or "-")
        event_id = self._escape_lark_md(row.get("event_id") or "-")

        if score > 60:
            score_tag = "利好"
            template = "green"
        elif score < -60:
            score_tag = "利空"
            template = "red"
        else:
            score_tag = "中性"
            template = "blue"

        return {
            "config": {
                "wide_screen_mode": True,
                "enable_forward": True,
            },
            "header": {
                "template": template,
                "title": {
                    "tag": "plain_text",
                    "content": f"财联社电报入库成功｜{score_tag} {score}",
                },
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
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
                # 需要展示原文的话，把下面打开
                # {"tag": "hr"},
                # {
                #     "tag": "div",
                #     "text": {
                #         "tag": "lark_md",
                #         "content": f"**电报内容**\n{content}",
                #     },
                # },
            ],
        }