import time
import re
import json
import hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.model import CLSTelegraph


BASE_URL = "https://www.jin10.com/"
DETAIL_BASE = "https://flash.jin10.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

CN_TZ = timezone(timedelta(hours=8))

session = requests.Session()
session.headers.update(HEADERS)


def fetch_home_html() -> str:
    resp = session.get(BASE_URL, timeout=15)
    resp.raise_for_status()

    # 金十页面编码有时识别不准，强制纠正
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def parse_flash_list(html: str) -> list[dict]:
    """
    从首页提取候选快讯：
    - time: 列表展示时间
    - summary: 简要摘要（仅用于兜底，不强制作为 title）
    - detail_url: 详情页链接
    """
    soup = BeautifulSoup(html, "html.parser")

    items: list[dict] = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()

        if "flash.jin10.com" not in href and "/detail/" not in href:
            continue
        if "/detail/" not in href:
            continue

        detail_url = href
        if detail_url.startswith("/"):
            detail_url = urljoin(DETAIL_BASE, detail_url)

        block_text = ""
        node = a.parent
        if node:
            block_text = node.get_text("\n", strip=True)

        # 向上扩大范围，尽量拿到更完整的文本块
        p = node
        for _ in range(3):
            if p and p.parent:
                p = p.parent
                text = p.get_text("\n", strip=True)
                if len(text) > len(block_text):
                    block_text = text

        if not block_text:
            continue

        time_match = re.search(r"\b(\d{2}:\d{2}:\d{2})\b", block_text)
        news_time = time_match.group(1) if time_match else None

        cleaned = block_text
        cleaned = re.sub(r"分享[:：]?\s*微信扫码分享", " ", cleaned)
        cleaned = re.sub(r"分享|收藏|详情|复制", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        if news_time:
            cleaned = cleaned.replace(news_time, "", 1).strip()

        # 列表摘要只保留短文本，避免整块脏 DOM 内容污染
        cleaned = cleaned[:120].strip()

        if len(cleaned) < 8:
            continue

        dedup_key = (news_time, cleaned[:100], detail_url)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        items.append(
            {
                "time": news_time,
                "summary": cleaned,
                "detail_url": detail_url,
            }
        )

    return items


def fetch_detail(detail_url: str) -> dict | None:
    """
    抓取详情页，提取完整发布时间和正文。
    """
    try:
        resp = session.get(detail_url, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
    except Exception:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\s+", " ", text).strip()

    # 兼容：2026-04-05 周日 21:03:23
    dt_match = re.search(
        r"(\d{4}-\d{2}-\d{2}\s+周.\s+\d{2}:\d{2}:\d{2})",
        text,
    )
    publish_datetime_str = dt_match.group(1) if dt_match else None

    cleaned = text
    cleaned = cleaned.replace("首页 快讯详情", " ")
    cleaned = cleaned.replace("JIN10.COM I 一个交易工具", " ")
    cleaned = cleaned.replace("分享： 微信扫码分享", " ")
    cleaned = cleaned.replace("分享 微信扫码分享", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return {
        "publish_datetime_str": publish_datetime_str,
        "content": cleaned,
    }


def parse_publish_ts(
    publish_datetime_str: str | None,
    fallback_hms: str | None = None,
) -> tuple[int | None, str | None]:
    """
    优先使用详情页完整日期时间。
    没有完整日期时，用当天日期 + 列表页 HH:MM:SS 兜底。
    """
    if publish_datetime_str:
        m = re.search(
            r"(\d{4}-\d{2}-\d{2})\s+周.\s+(\d{2}:\d{2}:\d{2})",
            publish_datetime_str,
        )
        if m:
            date_part = m.group(1)
            time_part = m.group(2)
            try:
                dt = datetime.strptime(
                    f"{date_part} {time_part}",
                    "%Y-%m-%d %H:%M:%S",
                ).replace(tzinfo=CN_TZ)
                return int(dt.timestamp()), time_part
            except Exception:
                pass

    if fallback_hms:
        try:
            today_cn = datetime.now(CN_TZ).strftime("%Y-%m-%d")
            dt = datetime.strptime(
                f"{today_cn} {fallback_hms}",
                "%Y-%m-%d %H:%M:%S",
            ).replace(tzinfo=CN_TZ)
            return int(dt.timestamp()), fallback_hms
        except Exception:
            return None, None

    return None, None


def extract_title(summary: str, content: str) -> str:
    """
    只在明确存在标题时返回：
    1. 【标题】正文
    2. 标题 + 金十数据X月X日讯 + 正文
    其他情况返回空字符串，不再硬截 summary。
    """
    summary = (summary or "").strip()
    content = (content or "").strip()

    # 情况1：以【标题】开头
    m = re.match(r"^[【\[]\s*([^】\]]+?)\s*[】\]]", content)
    if m:
        inner = m.group(1).strip()
        if inner and inner != "金十数据":
            return inner

    # 情况2：标题 金十数据4月5日讯...
    m = re.match(r"^(.{4,80}?)\s+金十数据\d{1,2}月\d{1,2}日讯", content)
    if m:
        candidate = m.group(1).strip()
        if not re.search(r"分享|收藏|详情|复制|微信扫码分享", candidate):
            return candidate

    # 情况3：summary 本身是纯净短标题时才返回
    if summary:
        if not re.search(r"分享|收藏|详情|复制|微信扫码分享", summary):
            if not re.search(r"\d{4}-\d{2}-\d{2}", summary):
                if len(summary) <= 80:
                    return summary

    return ""


def clean_content(content: str, summary: str) -> str:
    """
    清洗正文：
    - 去掉页面固定噪音
    - 去掉详情页中间拼接出来的“金十数据 + 时间 + 标题 + 重复正文”
    - 去掉前缀标题，避免 title/content 重复
    - 去掉尾部站点标识
    """
    content = (content or "").strip()
    summary = (summary or "").strip()

    if not content:
        return summary

    noise_patterns = [
        r"首页\s*快讯详情",
        r"JIN10\.COM\s*I\s*一个交易工具",
        r"分享[:：]?\s*微信扫码分享",
        r"分享\s*收藏\s*详情\s*复制",
    ]
    for pattern in noise_patterns:
        content = re.sub(pattern, " ", content)

    # 关键修复：
    # 去掉详情页整页文本里被拼进去的
    # “ - 金十数据 2026-04-05 周日 21:20:30 标题 金十数据4月5日讯 ...”
    # 保留前半段真正正文
    content = re.split(
        r"\s*[-—]\s*金十数据\s+\d{4}-\d{2}-\d{2}\s+周.\s+\d{2}:\d{2}:\d{2}\s+",
        content,
        maxsplit=1,
    )[0].strip()

    # 去掉开头的【标题】
    content = re.sub(r"^[【\[]\s*[^】\]]+?\s*[】\]]\s*", "", content, count=1)

    # 去掉类似 “标题 金十数据4月5日讯，正文...”
    content = re.sub(
        r"^(.{4,80}?)\s+金十数据\d{1,2}月\d{1,2}日讯[，,:：]?\s*",
        "",
        content,
        count=1,
    )

    # 去掉开头孤立的“金十数据”
    content = re.sub(r"^金十数据[，,:：]?\s*", "", content, count=1)

    # 去掉尾部站点标识
    content = re.sub(r"\s*[-—]\s*金十数据\s*$", "", content)
    content = re.sub(r"\s*金十数据\s*$", "", content)

    content = re.sub(r"\s+", " ", content).strip()
    return content

def build_event_id(detail_url: str | None, publish_ts: int | None, content: str) -> str:
    """
    优先用详情页 URL 生成稳定 event_id。
    没有详情链接时退化为 publish_ts + content + source。
    """
    if detail_url:
        return hashlib.md5(detail_url.encode("utf-8")).hexdigest()

    dedup_src = f"{publish_ts}+{content}+jin10"
    return hashlib.md5(dedup_src.encode("utf-8")).hexdigest()


def normalize_item(list_item: dict, detail_item: dict | None) -> CLSTelegraph | None:
    summary = (list_item.get("summary") or "").strip()
    fallback_hms = list_item.get("time")
    detail_url = list_item.get("detail_url")

    detail_publish_str = None
    detail_content = ""

    if detail_item:
        detail_publish_str = detail_item.get("publish_datetime_str")
        detail_content = detail_item.get("content") or ""

    publish_ts, publish_time = parse_publish_ts(detail_publish_str, fallback_hms)
    if publish_ts is None:
        return None

    raw_content = detail_content or summary
    content = clean_content(raw_content, summary)
    if not content:
        return None

    title = extract_title(summary, raw_content)
    event_id = build_event_id(detail_url, publish_ts, content)

    return CLSTelegraph(
        event_id=event_id,
        publish_ts=publish_ts,
        publish_time=publish_time,
        subjects=[],
        title=title,
        content=content,
        source="jin10",
        llm_analysis=None,
    )


def fetch_latest_telegraphs(
    limit: int = 20,
    detail_limit: int | None = None,
    sleep_seconds: float = 0.2,
) -> list[CLSTelegraph]:
    """
    统一返回 list[CLSTelegraph]，方便直接复用现有的
    llm 分析 / repository upsert / bootstrap 流程。
    """
    html = fetch_home_html()
    candidates = parse_flash_list(html)

    if limit > 0:
        candidates = candidates[:limit]

    if detail_limit is None:
        detail_limit = len(candidates)

    result: list[CLSTelegraph] = []
    seen = set()

    for idx, item in enumerate(candidates):
        detail = None
        if idx < detail_limit:
            detail = fetch_detail(item["detail_url"])
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        row = normalize_item(item, detail)
        if row is None:
            continue

        if not row.content:
            continue

        if row.event_id in seen:
            continue
        seen.add(row.event_id)

        result.append(row)

    result.sort(key=lambda x: x.publish_ts, reverse=True)
    return result


if __name__ == "__main__":
    rows = fetch_latest_telegraphs(limit=20, detail_limit=10, sleep_seconds=0.2)
    print(
        json.dumps(
            [row.model_dump() for row in rows[:5]],
            ensure_ascii=False,
            indent=2,
        )
    )