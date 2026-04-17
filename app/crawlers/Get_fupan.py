"""LEGACY wrapper (deprecated).

Use `infrastructure.crawlers.fupan_review_crawler.FupanReviewCrawler` instead.
"""

from infrastructure.crawlers.fupan_review_crawler import FupanReviewCrawler


def build_fupan_url(date: str) -> str:
    return f"https://stock.10jqka.com.cn/fupan/{date}.shtml"


def fetch_fupan_full_visible_text(url: str) -> str:
    # derive date from URL tail to preserve backward behavior
    date = url.rstrip("/").split("/")[-1].split(".")[0]
    crawler = FupanReviewCrawler()
    payload = crawler.fetch(date=date)
    return payload.content
