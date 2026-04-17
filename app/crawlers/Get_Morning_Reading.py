"""LEGACY wrapper (deprecated).

Use `infrastructure.crawlers.morning_reading_crawler.MorningReadingCrawler` instead.
"""

from infrastructure.crawlers.morning_reading_crawler import MorningReadingCrawler


def fetch_and_split_morning_data(date: str) -> dict:
    crawler = MorningReadingCrawler()
    payload = crawler.fetch(date=date)
    return payload.to_dict()
