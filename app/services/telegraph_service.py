import re

from app.model import CLSTelegraph


class TelegraphService:
    """市场资讯相关的去重与批次处理服务。"""

    @staticmethod
    def normalize_dedup_text(text: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""

        text = re.sub(r"财联社\d{1,2}月\d{1,2}日电[，,:：]?", "", text)
        text = re.sub(r"金十数据\d{1,2}月\d{1,2}日讯[，,:：]?", "", text)
        text = re.sub(r"^\[?金十数据\]?[，,:：]?", "", text)
        text = re.sub(r"^\[?财联社\]?[，,:：]?", "", text)

        text = re.sub(r"\s*[-—]\s*金十数据\s*$", "", text)
        text = re.sub(r"\s*[-—]\s*财联社\s*$", "", text)
        text = re.sub(r"\s*金十数据\s*$", "", text)
        text = re.sub(r"\s*财联社\s*$", "", text)

        text = re.sub(r"同花顺\d{1,2}月\d{1,2}日讯[，,:：]?", "", text)
        text = re.sub(r"^\[?同花顺\]?[，,:：]?", "", text)
        text = re.sub(r"\s*[-—]\s*同花顺\s*$", "", text)
        text = re.sub(r"\s*同花顺\s*$", "", text)
        text = re.sub(r"[（(]同花顺[）)]\s*$", "", text)

        text = re.sub(r"[“”\"'`‘’]", "", text)
        text = re.sub(r"[，。；：！？、】【（）()、,.;:!?·\-—\[\]]", "", text)
        text = re.sub(r"\s+", "", text)

        return text.lower()

    @staticmethod
    def is_valid_dedup_title(title: str) -> bool:
        title = (title or "").strip()
        if not title or len(title) < 6:
            return False

        bad_patterns = [
            r"^金十图示",
            r"^新闻联播今日要点",
            r"^今日要点$",
            r"^金十数据$",
            r"^财联社$",
            r"^快讯$",
        ]
        return not any(re.search(pattern, title) for pattern in bad_patterns)

    @staticmethod
    def strip_title_from_content(content: str, title: str) -> str:
        content = (content or "").strip()
        title = (title or "").strip()
        if not content or not title:
            return content

        pattern = rf"^\s*[【\[]?{re.escape(title)}[】\]]?\s*[-—:：，,\s]*"
        stripped = re.sub(pattern, "", content, count=1)
        return stripped.strip() or content

    def build_cross_source_dedup_keys(self, row: CLSTelegraph) -> set[str]:
        keys = set()
        title = (row.title or "").strip()
        content = (row.content or "").strip()

        if self.is_valid_dedup_title(title):
            norm_title = self.normalize_dedup_text(title)
            if norm_title:
                keys.add(f"title::{norm_title}")

        norm_content = self.normalize_dedup_text(content)
        if len(norm_content) >= 12:
            keys.add(f"content::{norm_content}")

        if title:
            stripped_content = self.strip_title_from_content(content, title)
            norm_stripped_content = self.normalize_dedup_text(stripped_content)
            if len(norm_stripped_content) >= 12:
                keys.add(f"content::{norm_stripped_content}")

        return keys

    @staticmethod
    def build_duplicate_preference_score(row: CLSTelegraph) -> tuple:
        return (
            len((row.content or "").strip()),
            len(row.subjects or []),
            1 if (row.title or "").strip() else 0,
            1 if row.source == "cls" else 0,
            row.publish_ts or 0,
        )

    def pick_better_duplicate_row(self, old_row: CLSTelegraph, new_row: CLSTelegraph) -> CLSTelegraph:
        old_score = self.build_duplicate_preference_score(old_row)
        new_score = self.build_duplicate_preference_score(new_row)
        return new_row if new_score > old_score else old_row

    def dedup_rows_in_batch(self, rows: list[CLSTelegraph]) -> tuple[list[CLSTelegraph], int]:
        if not rows:
            return rows, 0

        deduped_rows: list[CLSTelegraph] = []
        deduped_keys: list[set[str]] = []

        for row in rows:
            row_keys = self.build_cross_source_dedup_keys(row)
            if not row_keys:
                deduped_rows.append(row)
                deduped_keys.append(set())
                continue

            matched_index = None
            for idx, existing_keys in enumerate(deduped_keys):
                if row_keys & existing_keys:
                    matched_index = idx
                    break

            if matched_index is None:
                deduped_rows.append(row)
                deduped_keys.append(set(row_keys))
                continue

            kept_row = deduped_rows[matched_index]
            deduped_rows[matched_index] = self.pick_better_duplicate_row(kept_row, row)
            deduped_keys[matched_index] = deduped_keys[matched_index] | row_keys

        deduped_rows.sort(key=lambda x: x.publish_ts or 0)
        removed_count = len(rows) - len(deduped_rows)
        return deduped_rows, removed_count

    @staticmethod
    def filter_valid_incremental_rows(rows: list[CLSTelegraph], latest_ts: int | None) -> list[CLSTelegraph]:
        if not rows:
            return []

        valid_rows = [row for row in rows if row.event_id and row.content]
        deduped_rows = []
        seen_event_ids = set()

        for row in valid_rows:
            if row.event_id in seen_event_ids:
                continue
            seen_event_ids.add(row.event_id)

            row_ts = row.publish_ts or 0
            if latest_ts is not None and row_ts < latest_ts:
                continue

            deduped_rows.append(row)

        deduped_rows.sort(key=lambda x: x.publish_ts or 0)
        return deduped_rows
