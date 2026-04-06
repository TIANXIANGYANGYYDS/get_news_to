import re
import json
import hashlib
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

from app.model import CLSTelegraph


URL_CANDIDATES = [
    "https://news.10jqka.com.cn/realtimenews.html",
    "https://news.10jqka.com.cn/gdkx_list/",
    "https://www.10jqka.com.cn/",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.10jqka.com.cn/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CN_TZ = timezone(timedelta(hours=8))


def fetch_html(url: str, timeout: int = 15) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()

    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"

    return resp.text


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_time_line(text: str) -> bool:
    return bool(re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", text.strip()))


def parse_raw_items(html: str) -> list[dict]:
    """
    从 10jqka 页面文本中尽量宽松地抽取：
    HH:MM -> title -> content
    """
    soup = BeautifulSoup(html, "html.parser")
    texts = [clean_text(x) for x in soup.stripped_strings]
    texts = [x for x in texts if x]

    items = []
    i = 0

    skip_words = {
        "A股", "重要", "公告", "期货", "异动", "港股", "美股", "全部",
        "快讯", "7*24", "7×24", "7x24", "全球财经直播", "滚动快讯",
    }

    while i < len(texts) - 2:
        if is_time_line(texts[i]):
            time_str = texts[i]

            j = i + 1
            while j < len(texts) and texts[j] in skip_words:
                j += 1

            if j + 1 < len(texts):
                title = texts[j].lstrip("#").strip()
                content = texts[j + 1].strip()

                if title and content and (not is_time_line(title)) and (not is_time_line(content)):
                    items.append(
                        {
                            "time": time_str,
                            "title": title,
                            "content": content,
                            "subjects": [],
                            "source": "10jqka",
                        }
                    )
                    i = j + 2
                    continue

        i += 1

    dedup = []
    seen = set()
    for row in items:
        key = (row["time"], row["title"], row["content"])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(row)

    return dedup


def parse_publish_time_from_hhmm(text: str) -> tuple[int | None, str | None]:
    """
    10jqka 当前抓到的是 HH:MM / HH:MM:SS
    这里补成北京时间时间戳。
    如果解析出来的时间比当前时间还“超前”太多，
    视为跨天数据，自动回退一天。
    """
    if not text:
        return None, None

    m = re.fullmatch(r"(\d{2}):(\d{2})(?::(\d{2}))?", text.strip())
    if not m:
        return None, None

    hour = int(m.group(1))
    minute = int(m.group(2))
    second = int(m.group(3) or 0)

    now = datetime.now(CN_TZ)
    dt = now.replace(hour=hour, minute=minute, second=second, microsecond=0)

    # 防止凌晨附近抓到上一天的 23:xx 数据时被错误当成今天未来时间
    if dt > now + timedelta(minutes=5):
        dt -= timedelta(days=1)

    return int(dt.timestamp()), dt.strftime("%H:%M:%S")


def normalize_item(item: dict) -> CLSTelegraph | None:
    raw_title = (item.get("title") or "").strip()
    raw_content = (item.get("content") or "").strip()

    title = raw_title
    content = raw_content or raw_title

    publish_ts, publish_time = parse_publish_time_from_hhmm(
        item.get("time") or item.get("publish_time") or ""
    )

    if publish_ts is None:
        return None

    if not content:
        return None

    raw_event_id = item.get("event_id") or item.get("id")
    if raw_event_id is None or raw_event_id == "":
        dedup_src = f"{publish_ts}+{title}+{content}+10jqka"
        event_id = hashlib.md5(dedup_src.encode("utf-8")).hexdigest()
    else:
        event_id = str(raw_event_id)

    return CLSTelegraph(
        event_id=event_id,
        publish_ts=publish_ts,
        publish_time=publish_time,
        subjects=item.get("subjects", []) or [],
        title=title,
        content=content,
        source="10jqka",
        llm_analysis=None,
    )


def fetch_raw_telegraphs(rn: int = 20) -> list[dict]:
    for url in URL_CANDIDATES:
        try:
            html = fetch_html(url)
            items = parse_raw_items(html)
            if items:
                return items[:rn]
        except Exception as e:
            print(f"[WARN] 抓取失败: {url}, error={e}")

    return []


def fetch_latest_telegraphs(rn: int = 20) -> list[CLSTelegraph]:
    raw_items = fetch_raw_telegraphs(rn=rn)

    result = [normalize_item(x) for x in raw_items]

    seen = set()
    cleaned: list[CLSTelegraph] = []

    for row in result:
        if row is None:
            continue
        if not row.content:
            continue
        if row.event_id in seen:
            continue
        seen.add(row.event_id)
        cleaned.append(row)

    cleaned.sort(key=lambda x: x.publish_ts, reverse=True)
    return cleaned[:rn]


if __name__ == "__main__":
    rows = fetch_latest_telegraphs(rn=20)
    print(
        json.dumps(
            [row.model_dump() for row in rows],
            ensure_ascii=False,
            indent=2,
        )
    )