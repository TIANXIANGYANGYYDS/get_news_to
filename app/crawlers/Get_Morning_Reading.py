import re
import requests
from bs4 import BeautifulSoup


def fetch_and_split_morning_data(date: str) -> dict:
    """
    抓取同花顺早盘页面，并按正文栏目分段返回。

    Returns:
        {
            "source": "10jqka_zaopan",
            "date": "2026-03-27",
            "raw_content": "...",
            "sections": {
                "head": "...",
                "overseas": "...",
                "domestic": "...",
                "major_news": "...",
                "company_announcements": "...",
                "broker_views": "...",
                "calendar": "...",
            }
        }
    """
    url = f"https://stock.10jqka.com.cn/zaopan/{date}.shtml"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36"
        )
    }

    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    resp.encoding = "gbk"

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    date_matches = re.findall(r'Global\.date\s*=\s*"(\d{8})"', html)
    date_str = date_matches[-1] if date_matches else None

    formatted_date = None
    if date_str and len(date_str) == 8:
        formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

    main_block = soup.find("div", id="block_2125")
    raw_content = main_block.get_text("\n", strip=True) if main_block else ""

    sections = _split_sections(raw_content)

    return {
        "source": "10jqka_zaopan",
        "date": formatted_date,
        "request_url": url,
        "response_url": resp.url,
        "status_code": resp.status_code,
        "raw_content": raw_content,
        "sections": sections,
    }


def _split_sections(content: str) -> dict:
    """
    将正文按固定栏目拆分。
    """
    title_mapping = {
        "【隔夜海外行情动态】": "overseas",
        "【昨日国内行情回顾】": "domestic",
        "【重大新闻汇总】": "major_news",
        "【公司公告】": "company_announcements",
        "【券商观点】": "broker_views",
        "【今日重点关注的财经数据与事件】": "calendar",
    }

    result = {
        "head": [],
        "overseas": [],
        "domestic": [],
        "major_news": [],
        "company_announcements": [],
        "broker_views": [],
        "calendar": [],
    }

    current_key = "head"

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue

        matched_key = None
        for title, key in title_mapping.items():
            if title in line:
                matched_key = key
                break

        if matched_key:
            current_key = matched_key
            continue

        result[current_key].append(line)

    return {k: "\n".join(v).strip() for k, v in result.items()}
