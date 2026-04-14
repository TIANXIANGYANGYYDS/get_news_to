import re
import json
import time
import requests
from bs4 import BeautifulSoup


M_RANK_URL = "https://m.10jqka.com.cn/hq/rank/"
PC_RANK_URL = "https://data.10jqka.com.cn/market/zdfph/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.10jqka.com.cn/",
    "Connection": "keep-alive",
}


def extract_codes_from_text(text: str) -> list[str]:
    """
    从文本中提取 6 位股票代码，保序去重
    """
    seen = set()
    result = []

    for code in re.findall(r"\b\d{6}\b", text):
        if code not in seen:
            seen.add(code)
            result.append(code)

    return result


def try_parse_json_blocks(html: str) -> list[str]:
    """
    尝试从 script/json 数据块中提取股票代码
    """
    codes = []

    # 直接从整页文本先粗提一次
    codes.extend(extract_codes_from_text(html))

    # 尝试从 script 标签里找更集中的数据
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        script_text = script.get_text(" ", strip=True)
        if not script_text:
            continue

        page_codes = extract_codes_from_text(script_text)
        if page_codes:
            codes.extend(page_codes)

    # 去重保序
    final_codes = []
    seen = set()
    for code in codes:
        if code not in seen:
            seen.add(code)
            final_codes.append(code)

    return final_codes


def try_parse_links(html: str) -> list[str]:
    """
    尝试从页面链接中提取股票代码
    常见形态：/.../000001/ 或 href 中带 6 位代码
    """
    soup = BeautifulSoup(html, "html.parser")
    codes = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True)
        merged = f"{href} {text}"

        found = re.findall(r"\b\d{6}\b", merged)
        for code in found:
            if code not in seen:
                seen.add(code)
                codes.append(code)

    return codes


def fetch_html(session: requests.Session, url: str) -> str:
    resp = session.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"

    return resp.text


def get_top_100_stock_ids() -> list[str]:
    session = requests.Session()

    candidates = []

    # 先抓手机排行页
    html = fetch_html(session, M_RANK_URL)
    candidates.extend(try_parse_links(html))
    candidates.extend(try_parse_json_blocks(html))

    # 若不足，再抓 PC 排行页兜底
    if len(candidates) < 100:
        time.sleep(1.5)
        html2 = fetch_html(session, PC_RANK_URL)
        candidates.extend(try_parse_links(html2))
        candidates.extend(try_parse_json_blocks(html2))

    # 过滤 A 股常见 6 位股票代码
    # 这里不强行只保留 0/3/6/8/4 开头，避免北交所或页面结构变化时漏掉
    result = []
    seen = set()
    for code in candidates:
        if re.fullmatch(r"\d{6}", code) and code not in seen:
            seen.add(code)
            result.append(code)

    return result[:100]


if __name__ == "__main__":
    top_100_ids = get_top_100_stock_ids()
    print(f"count={len(top_100_ids)}")
    print(top_100_ids)