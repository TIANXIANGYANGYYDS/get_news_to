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