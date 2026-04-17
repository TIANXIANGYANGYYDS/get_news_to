"""LEGACY wrapper (deprecated).

Use `infrastructure.crawlers.kline_snapshot_crawler.KlineSnapshotCrawler` instead.
"""

from infrastructure.crawlers.kline_snapshot_crawler import KlineSnapshotCrawler


class EastmoneyAShareCrawler:
    def __init__(self, *args, **kwargs):
        self._crawler = KlineSnapshotCrawler()

    def crawl_all_pages(self, use_proxy: bool = False):
        batch = self._crawler.fetch()
        return [row.to_dict() for row in batch.rows]


class ShanchenProxyProvider:
    def __init__(self, *args, **kwargs):
        pass

    def get_requests_proxies(self):
        return None
