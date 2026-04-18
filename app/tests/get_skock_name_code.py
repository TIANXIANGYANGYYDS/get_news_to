import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://q.10jqka.com.cn"
LIST_URL = "https://q.10jqka.com.cn/thshy/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Referer": "https://q.10jqka.com.cn/",
}


def fetch_sector_name_and_code():
    resp = requests.get(LIST_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    # 10jqka 页面常见是 gbk / gb18030
    resp.encoding = resp.apparent_encoding or "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        name = a.get_text(strip=True)

        # 只要同花顺行业详情链接
        # 例如 /thshy/detail/code/881121/
        m = re.search(r"/thshy/detail/code/(\d{6})/?", href)
        if not m:
            continue

        if not name:
            continue

        code = m.group(1)
        full_url = urljoin(BASE_URL, href)
        key = (name, code)

        if key in seen:
            continue
        seen.add(key)

        results.append({
            "sector_name": name,
            "sector_code": code,
            "detail_url": full_url,
        })

    # 按代码排序，方便后续使用
    results.sort(key=lambda x: x["sector_code"])
    return results


if __name__ == "__main__":
    data = fetch_sector_name_and_code()
    for row in data:
        print(row)