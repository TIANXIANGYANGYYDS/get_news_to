from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from shared.logging.logger import get_logger


CN_TZ = timezone(timedelta(hours=8))


class BaseCrawler(ABC):
    source_name: str = "unknown"

    def __init__(self, *, timeout_seconds: int = 15, max_retries: int = 2, backoff_seconds: float = 0.5):
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.session = requests.Session()
        self.logger = get_logger(f"crawler.{self.source_name}")

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                response = self.session.request(method, url, timeout=self.timeout_seconds, **kwargs)
                response.raise_for_status()
                return response
            except Exception as exc:  # noqa: PERF203
                last_error = exc
                if attempt > self.max_retries:
                    break
                sleep_seconds = self.backoff_seconds * (2 ** (attempt - 1))
                self.logger.warning("request failed, retrying", extra={"attempt": attempt, "url": url})
                time.sleep(sleep_seconds)
        raise RuntimeError(f"request failed after retry: {url}, error={last_error}")

    @abstractmethod
    def fetch(self, limit: int = 20):
        raise NotImplementedError


class BaseNewsCrawler(BaseCrawler, ABC):
    def parse_timestamp(self, value: int | str | None) -> tuple[int | None, str | None]:
        if value is None:
            return None, None
        try:
            ts = int(value)
            if ts > 10**12:
                ts //= 1000
            dt = datetime.fromtimestamp(ts, tz=CN_TZ)
            return ts, dt.strftime("%H:%M:%S")
        except Exception:
            return None, None

    def deduplicate_key(self, publish_ts: int, title: str, content: str) -> str:
        raw = f"{self.source_name}|{publish_ts}|{title.strip()}|{content.strip()}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()


class BaseMarketDataCrawler(BaseCrawler, ABC):
    pass
