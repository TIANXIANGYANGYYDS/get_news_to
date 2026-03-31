import time
import re
import json
import hashlib
import urllib.parse
from datetime import datetime, timezone, timedelta

import requests


BASE_URL = "https://www.cls.cn/nodeapi/telegraphList"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.cls.cn/telegraph",
    "Accept": "application/json, text/plain, */*",
}
CN_TZ = timezone(timedelta(hours=8))


def make_sign(params: dict) -> str:
    """
    sign = md5(sha1(sorted_query_string))
    """
    sorted_items = sorted((k, str(v)) for k, v in params.items())
    query_string = urllib.parse.urlencode(sorted_items)
    sha1_hex = hashlib.sha1(query_string.encode("utf-8")).hexdigest()
    return hashlib.md5(sha1_hex.encode("utf-8")).hexdigest()


def build_latest_params(last_time: int | None = None, rn: int = 20) -> dict:
    if last_time is None:
        last_time = int(time.time())

    params = {
        "app": "CailianpressWeb",
        "lastTime": str(last_time),
        "last_time": str(last_time),
        "os": "web",
        "refresh_type": "1",
        "rn": str(rn),
        "sv": "8.4.6",
    }
    params["sign"] = make_sign(params)
    return params


def find_items(payload: dict) -> list[dict]:
    """
    尽量兼容不同返回结构，优先找常见位置。
    """
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            if isinstance(data.get("roll_data"), list):
                return data["roll_data"]
            if isinstance(data.get("data"), list):
                return data["data"]
            if isinstance(data.get("list"), list):
                return data["list"]
        if isinstance(data, list):
            return data

    candidates = []

    def walk(node, path="root"):
        if isinstance(node, list) and node and all(isinstance(x, dict) for x in node):
            score = 0
            for item in node[:5]:
                keys = set(item.keys())
                if {"content", "ctime"} & keys:
                    score += 2
                if {"title", "time", "id"} & keys:
                    score += 1
            if score > 0:
                candidates.append((score, len(node), path, node))
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}")

    walk(payload)

    if not candidates:
        return []

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates[0][3]


def split_title_and_content(title: str, content: str) -> tuple[str, str]:
    """
    兼容两种情况：
    1. title 字段本身就有值
    2. content 以【标题】开头
    """
    title = (title or "").strip()
    content = (content or "").strip()

    if not title:
        m = re.match(r"^[【\[〖]\s*([^】\]〗]+?)\s*[】\]〗]", content)
        if m:
            title = m.group(1).strip()

    content = re.sub(r"^[【\[〖]\s*[^】\]〗]+?\s*[】\]〗]\s*", "", content, count=1).strip()
    return title, content


def format_publish_time(ts) -> tuple[int | None, str | None]:
    if ts is None:
        return None, None

    try:
        ts = int(ts)
        if ts > 10**12:
            ts = ts // 1000
        dt = datetime.fromtimestamp(ts, tz=CN_TZ)
        return ts, dt.strftime("%H:%M:%S")
    except Exception:
        return None, None


def extract_subjects(item: dict) -> list[str]:
    subjects = []
    for subject in item.get("subjects", []) or []:
        name = (subject.get("subject_name") or "").strip()
        if name and name not in subjects:
            subjects.append(name)
    return subjects


def normalize_item(item: dict) -> dict:
    raw_title = item.get("title", "")
    raw_content = item.get("content", "")

    title, content = split_title_and_content(raw_title, raw_content)
    merged_content = f"{title} {content}".strip() if title else content

    publish_ts, publish_time = format_publish_time(
        item.get("ctime") or item.get("time") or item.get("created_at")
    )

    dedup_src = f"{publish_ts}|{merged_content}"
    event_id = item.get("event_id") or hashlib.md5(dedup_src.encode("utf-8")).hexdigest()

    return {
        "event_id": event_id,
        "publish_ts": publish_ts,
        "publish_time": publish_time,
        "subjects": extract_subjects(item),
        "content": merged_content,
    }


def fetch_latest_telegraphs(rn: int = 20) -> list[dict]:
    params = build_latest_params(rn=rn)

    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    payload = resp.json()
    items = find_items(payload)

    result = [normalize_item(x) for x in items]

    seen = set()
    cleaned = []
    for row in result:
        if not row["content"]:
            continue
        if row["event_id"] in seen:
            continue
        seen.add(row["event_id"])
        cleaned.append(row)

    cleaned.sort(key=lambda x: x["publish_ts"] or 0, reverse=True)
    return cleaned


if __name__ == "__main__":
    rows = fetch_latest_telegraphs(rn=20)
    print(json.dumps(rows[:5], ensure_ascii=False, indent=2))