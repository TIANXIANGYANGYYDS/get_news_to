from __future__ import annotations

from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.constants.stock_code_url import skock_code_urls_map
from app.crawlers.proxy_provider import NoProxyProvider, ProxyProvider
from app.logger import get_logger


logger = get_logger("Get_10jqka_sector_top_stocks")

_HEADERS = {
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
    "Referer": "https://q.10jqka.com.cn/",
    "Connection": "keep-alive",
}

_SECTOR_MAP = {item.get("sector_name"): item for item in skock_code_urls_map if isinstance(item, dict)}


def _extract_stocks_from_detail_html(html: str) -> tuple[list[dict], str | None]:
    soup = BeautifulSoup(html, "html.parser")
    table = None

    for box in soup.select("div.box"):
        head = box.select_one("div.head h2")
        if head and "行业成分股涨跌排行榜" in head.get_text(strip=True):
            table = box.select_one("table.m-table")
            break

    if table is None:
        return [], None

    stocks: list[dict] = []
    for row in table.select("tbody tr"):
        cols = row.select("td")
        if len(cols) < 3:
            continue

        code = ""
        name = ""

        code_a = cols[1].select_one("a")
        if code_a:
            code = code_a.get_text(strip=True)

        name_a = cols[2].select_one("a")
        if name_a:
            name = name_a.get_text(strip=True)
        elif cols[2]:
            name = cols[2].get_text(strip=True)

        if code and name:
            stocks.append({"code": code, "name": name})

    next_page_url = None
    next_link = soup.select_one("span.page_info a.changePage")
    if next_link:
        page_attr = (next_link.get("page") or "").strip()
        if page_attr.isdigit():
            href = (next_link.get("href") or "").strip()
            if href:
                next_page_url = urljoin("https://q.10jqka.com.cn", href)

    return stocks, next_page_url


def _request_with_local_then_proxy(
    session: requests.Session,
    url: str,
    *,
    timeout: int,
    sector_name: str,
    proxy_provider: ProxyProvider,
    proxy_max_attempts: int,
) -> requests.Response:
    try:
        response = session.get(url, timeout=timeout, proxies=None)
        response.raise_for_status()
        logger.info("sector detail local request success, sector_name=%s", sector_name)
        return response
    except Exception as local_exc:
        logger.warning(
            "sector detail local request failed, switch proxy, sector_name=%s, err=%s",
            sector_name,
            local_exc,
        )

    last_proxy_exc: Exception | None = None
    for _ in range(max(proxy_max_attempts, 1)):
        proxies = proxy_provider.get_requests_proxies()
        try:
            response = session.get(url, timeout=timeout, proxies=proxies)
            response.raise_for_status()
            proxy_provider.on_success()
            logger.info("sector detail proxy request success, sector_name=%s", sector_name)
            return response
        except Exception as proxy_exc:
            last_proxy_exc = proxy_exc
            proxy_provider.on_failure(proxy_exc)
            logger.warning(
                "sector detail proxy request failed, sector_name=%s, err=%s",
                sector_name,
                proxy_exc,
            )

    if last_proxy_exc is not None:
        raise last_proxy_exc
    raise RuntimeError(f"sector detail request failed, sector_name={sector_name}")


def fetch_sector_top_stocks_by_name(
    sector_name: str,
    top_n: int = 20,
    timeout: int = 12,
    proxy_provider: ProxyProvider | None = None,
    proxy_max_attempts: int = 1,
) -> dict:
    """
    根据板块名称抓取同花顺行业详情页默认排序的前 N 只股票。
    失败时降级返回空 stocks，不抛出异常。
    """
    sector_name = (sector_name or "").strip()
    if not sector_name:
        return {"sector_name": sector_name, "sector_code": None, "stocks": []}

    mapping = _SECTOR_MAP.get(sector_name)
    if not mapping:
        logger.warning("sector mapping not found: %s", sector_name)
        return {"sector_name": sector_name, "sector_code": None, "stocks": []}

    sector_code = mapping.get("sector_code")
    detail_url = mapping.get("detail_url")
    if not detail_url:
        logger.warning("detail_url is empty for sector_name=%s", sector_name)
        return {"sector_name": sector_name, "sector_code": sector_code, "stocks": []}

    stocks: list[dict] = []
    current_url = detail_url
    seen_urls: set[str] = set()
    provider = proxy_provider or NoProxyProvider()

    try:
        with requests.Session() as session:
            session.headers.update(_HEADERS)
            while current_url and len(stocks) < top_n and current_url not in seen_urls:
                seen_urls.add(current_url)
                response = _request_with_local_then_proxy(
                    session,
                    current_url,
                    timeout=timeout,
                    sector_name=sector_name,
                    proxy_provider=provider,
                    proxy_max_attempts=proxy_max_attempts,
                )

                if not response.encoding or response.encoding.lower() in {"iso-8859-1", "ascii"}:
                    response.encoding = response.apparent_encoding or "gbk"

                page_stocks, next_page_url = _extract_stocks_from_detail_html(response.text)
                if not page_stocks:
                    break

                remain = top_n - len(stocks)
                stocks.extend(page_stocks[:remain])
                current_url = next_page_url if len(stocks) < top_n else None
    except Exception as e:
        logger.exception(
            "fetch sector top stocks failed, downgrade to empty stocks, sector_name=%s, err=%s",
            sector_name,
            e,
        )
        return {"sector_name": sector_name, "sector_code": sector_code, "stocks": []}

    return {
        "sector_name": sector_name,
        "sector_code": sector_code,
        "stocks": stocks[:top_n],
    }
