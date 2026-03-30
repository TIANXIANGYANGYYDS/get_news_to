from bs4 import BeautifulSoup
import requests
import re

from datetime import datetime, timedelta

def get_prev_weekday(dt: datetime) -> datetime:
    prev_day = dt - timedelta(days=1)
    while prev_day.weekday() >= 5:
        prev_day -= timedelta(days=1)
    return prev_day

def build_fupan_url(date: str) -> str:
    return f"https://stock.10jqka.com.cn/fupan/{date}.shtml"

def fetch_fupan_full_visible_text(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36"
        )
    }

    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()

    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding

    return extract_fupan_full_visible_text_from_html(resp.text)


def extract_fupan_full_visible_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    def clean_text(text: str) -> str:
        text = re.sub(r"\xa0", " ", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    result = []

    # 1. 页头
    h1 = soup.select_one("div.header h1")
    if h1:
        result.append(clean_text(h1.get_text(" ", strip=True)))

    logo = soup.select_one("img.master_logo")
    if logo and logo.get("alt"):
        result.append(clean_text(logo.get("alt", "")))

    main_title = soup.select_one("p.main_title")
    if main_title:
        result.append(clean_text(main_title.get_text(" ", strip=True)))

    # 2. 综合描述
    summary_title = soup.find(string=lambda s: s and "综合描述" in s)
    if summary_title:
        result.append("综合描述")

    summary_block = soup.select_one("#block_1887")
    if summary_block:
        result.append(clean_text(summary_block.get_text("\n", strip=True)))

    # 3. 顶部指数栏
    nav_items = soup.select("div.nav ul.nav_list li")
    for li in nav_items:
        parts = [x.get_text(" ", strip=True) for x in li.find_all(["strong", "span"])]
        parts = [p for p in parts if p]
        if parts:
            result.append("".join(parts))

    # 4. 主内容区，按页面顺序提取
    for item in soup.select("div.container > div[class^='fp_item_']"):
        # 标题编号和名称
        no = item.select_one(".fp_item_hd .no")
        tx = item.select_one(".fp_item_hd .tx")
        if no and tx:
            result.append(clean_text(no.get_text(" ", strip=True)))
            result.append(clean_text(tx.get_text(" ", strip=True)))

        # strong / p / div / li / table
        content_lines = []

        # 4.1 strong 标题
        for strong in item.select(".fp_item_cnt strong"):
            txt = clean_text(strong.get_text(" ", strip=True))
            if txt:
                content_lines.append(txt)

        # 4.2 特殊 block 内容
        for div in item.select(".fp_item_cnt div[id^='block_']"):
            txt = clean_text(div.get_text("\n", strip=True))
            if txt:
                content_lines.append(txt)

        # 4.3 涨幅前三 tab 表格
        for tipbox in item.select(".rise_top3_tipbox"):
            title = tipbox.select_one("strong")
            if title:
                t = clean_text(title.get_text(" ", strip=True))
                if t:
                    content_lines.append(t)

            for tr in tipbox.select("tr"):
                tds = [clean_text(td.get_text(" ", strip=True)) for td in tr.select("td")]
                tds = [x for x in tds if x]
                if tds:
                    content_lines.append("\t".join(tds))

        # 4.4 普通 ul li
        for li in item.select(".fp_item_cnt li"):
            # 排除 rise_top3 这些已经处理过的
            if li.find_parent(class_="rise_top3_tipbox"):
                continue
            txt = clean_text(li.get_text(" ", strip=True))
            if txt:
                content_lines.append(txt)

        # 4.5 同比指数盈利区块，保留文字
        for node in item.select(".fp_item_cnt .yLegendTop, .fp_item_cnt .yLegendBottom, .fp_item_cnt .axisTip, .fp_item_cnt .question_tip_content"):
            txt = clean_text(node.get_text("\n", strip=True))
            if txt:
                content_lines.append(txt)

        # 去重但保序
        deduped = []
        seen = set()
        for line in content_lines:
            key = re.sub(r"\s+", " ", line)
            if key and key not in seen:
                seen.add(key)
                deduped.append(line)

        result.extend(deduped)

    # 5. 页脚
    footer = soup.select_one("div.footer")
    if footer:
        txt = clean_text(footer.get_text(" ", strip=True))
        if txt:
            result.append(txt)

    # 6. 侧边导航
    side_links = []
    for a in soup.select("#nav a, .side_nav a"):
        txt = clean_text(a.get_text(" ", strip=True))
        if txt:
            side_links.append(txt)

    if side_links:
        deduped = []
        seen = set()
        for x in side_links:
            if x not in seen:
                seen.add(x)
                deduped.append(x)
        result.extend(deduped)

    # 最终清洗
    final_lines = []
    seen = set()
    for line in result:
        line = clean_text(line)
        if not line:
            continue
        # 过滤明显脚本噪音
        if "window.location.href" in line or "document.domain" in line:
            continue
        if line not in seen:
            seen.add(line)
            final_lines.append(line)

    return "\n".join(final_lines)


if __name__ == "__main__":
    url = "https://stock.10jqka.com.cn/fupan/20260326.shtml"
    text = fetch_fupan_full_visible_text(url)
    print(text)