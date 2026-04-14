# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from typing import List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


class THSIndustryCrawler:
    BASE_URL = "https://q.10jqka.com.cn"
    INDUSTRY_URL = "https://q.10jqka.com.cn/thshy/"

    def __init__(self, timeout: int = 15, sleep_sec: float = 0.5):
        self.timeout = timeout
        self.sleep_sec = sleep_sec
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Connection": "keep-alive",
                "Referer": self.BASE_URL + "/",
            }
        )

    def _get_html(self, url: str) -> str:
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()

        if not resp.encoding or resp.encoding.lower() in {"iso-8859-1", "ascii"}:
            resp.encoding = resp.apparent_encoding or "gbk"

        return resp.text

    def _find_industry_table(self, soup: BeautifulSoup):
        boxes = soup.select("div.box")
        for box in boxes:
            head = box.select_one("div.head h2")
            if head and "同花顺行业一览表" in head.get_text(strip=True):
                return box
        raise RuntimeError("未找到“同花顺行业一览表”对应的表格区域")

    def _find_component_table(self, soup: BeautifulSoup):
        boxes = soup.select("div.box")
        for box in boxes:
            head = box.select_one("div.head h2")
            if head and "行业成分股涨跌排行榜" in head.get_text(strip=True):
                table = box.select_one("table.m-table")
                if table:
                    return table
        raise RuntimeError("未找到“行业成分股涨跌排行榜”表格")

    def get_top_industries(self, limit: int = 5) -> List[dict]:
        html = self._get_html(self.INDUSTRY_URL)
        soup = BeautifulSoup(html, "html.parser")

        table_box = self._find_industry_table(soup)
        rows = table_box.select("table.m-table tbody tr")

        results = []
        for row in rows[:limit]:
            cols = row.select("td")
            if len(cols) < 2:
                continue

            industry_a = cols[1].select_one("a")
            if not industry_a:
                continue

            href = industry_a.get("href", "").strip()
            detail_url = urljoin(self.BASE_URL, href)

            results.append(
                {
                    "detail_url": detail_url,
                }
            )

        if not results:
            raise RuntimeError("未从总页解析出任何板块数据")

        return results

    def get_top_stock_codes_from_industry_detail(
        self, detail_url: str, top_n: int = 20
    ) -> List[str]:
        html = self._get_html(detail_url)
        soup = BeautifulSoup(html, "html.parser")

        table = self._find_component_table(soup)
        rows = table.select("tbody tr")

        stock_codes: List[str] = []
        for row in rows[:top_n]:
            cols = row.select("td")
            if len(cols) < 2:
                continue

            code_a = cols[1].select_one("a")
            if not code_a:
                continue

            stock_code = code_a.get_text(strip=True)
            if stock_code:
                stock_codes.append(stock_code)

        return stock_codes

    def get_top5_industries_top20_stock_codes_flat(self) -> List[str]:
        industries = self.get_top_industries(limit=5)
        all_codes: List[str] = []

        for idx, industry in enumerate(industries, start=1):
            detail_url = industry["detail_url"]
            codes = self.get_top_stock_codes_from_industry_detail(detail_url, top_n=20)
            all_codes.extend(codes)

            if idx != len(industries):
                time.sleep(self.sleep_sec)

        return all_codes


def main():
    crawler = THSIndustryCrawler(timeout=15, sleep_sec=0.8)
    all_codes = crawler.get_top5_industries_top20_stock_codes_flat()
    print(all_codes)


if __name__ == "__main__":
    main()