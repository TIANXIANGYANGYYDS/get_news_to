import json
import os
import random
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.crawlers.proxy_provider import (
    NoProxyProvider,
    ProxyProvider,
    ShanchenProxyProvider,
    quick_test_proxy,
)


class EastmoneyAShareCrawler:
    BASE_URL = "https://82.push2.eastmoney.com/api/qt/clist/get"

    def __init__(
        self,
        page_size: int = 100,
        timeout: Tuple[int, int] = (10, 20),
        page_retry: int = 8,
        min_sleep: float = 0.0,
        max_sleep: float = 0.0,
        batch_pages: int = 0,
        batch_sleep_min: float = 0.0,
        batch_sleep_max: float = 0.0,
        checkpoint_file: str = "eastmoney_a_share_checkpoint.json",
        proxy_provider: Optional[ProxyProvider] = None,
    ):
        self.page_size = page_size
        self.timeout = timeout
        self.page_retry = page_retry
        self.min_sleep = min_sleep
        self.max_sleep = max_sleep
        self.batch_pages = batch_pages
        self.batch_sleep_min = batch_sleep_min
        self.batch_sleep_max = batch_sleep_max
        self.checkpoint_file = checkpoint_file
        self.proxy_provider = proxy_provider or NoProxyProvider()

        self._clear_proxy_env()
        self.session = self._build_session()

    @staticmethod
    def _clear_proxy_env() -> None:
        for key in [
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ]:
            os.environ.pop(key, None)

    @staticmethod
    def _random_user_agent() -> str:
        uas = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ]
        return random.choice(uas)

    def _build_session(self) -> requests.Session:
        s = requests.Session()
        s.trust_env = False
        s.headers.update(
            {
                "User-Agent": self._random_user_agent(),
                "Referer": "https://quote.eastmoney.com/",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Connection": "close",
            }
        )
        return s

    def _rebuild_session(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass
        self.session = self._build_session()

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        if value in (None, "", "-", "--"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_yi_yuan(value: Optional[float]) -> Optional[str]:
        if value is None:
            return None
        return f"{value / 1e8:.2f}亿"

    @staticmethod
    def _format_yi_shares(value: Optional[float]) -> Optional[str]:
        if value is None:
            return None
        return f"{value / 1e8:.2f}亿股"

    def _sleep_page(self) -> None:
        if self.max_sleep <= 0:
            return
        time.sleep(random.uniform(self.min_sleep, self.max_sleep))

    def _sleep_batch(self) -> None:
        if self.batch_sleep_max <= 0:
            return
        time.sleep(random.uniform(self.batch_sleep_min, self.batch_sleep_max))

    def _build_params(self, page: int) -> Dict[str, Any]:
        return {
            "pn": page,
            "pz": self.page_size,
            "po": 1,
            "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
            "fields": ",".join(
                [
                    "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10",
                    "f12", "f14", "f15", "f16", "f17", "f18", "f20", "f21", "f22",
                ]
            ),
            "_": int(time.time() * 1000),
        }

    def _get_proxies(self) -> Optional[Dict[str, str]]:
        return self.proxy_provider.get_requests_proxies()

    def _request_page_once(self, page: int) -> List[Dict[str, Any]]:
        params = self._build_params(page)
        proxies = self._get_proxies()

        self.session.headers["User-Agent"] = self._random_user_agent()
        print(f"第 {page} 页使用代理: {proxies}")

        resp = self.session.get(
            self.BASE_URL,
            params=params,
            timeout=self.timeout,
            proxies=proxies,
        )
        resp.raise_for_status()

        text = resp.text
        data = json.loads(text)

        payload = data.get("data") or {}
        diff = payload.get("diff") or []

        if isinstance(diff, dict):
            diff = list(diff.values())

        return diff

    def _request_page(self, page: int, verbose: bool = True) -> List[Dict[str, Any]]:
        """
        单页请求策略：
        - 某个 IP 失败，立即弃用
        - 下次自动换一个新 IP
        - 最多尝试 self.page_retry 个 IP
        - 全部失败后，抛错停止
        """
        last_error: Optional[Exception] = None

        for ip_attempt in range(1, self.page_retry + 1):
            try:
                rows = self._request_page_once(page)
                self.proxy_provider.on_success()

                if verbose:
                    print(f"第 {page} 页使用第 {ip_attempt} 个IP请求成功")
                return rows

            except Exception as e:
                last_error = e
                self.proxy_provider.on_failure(e)

                if verbose:
                    print(f"第 {page} 页第 {ip_attempt} 个IP失败: {repr(e)}")

                if ip_attempt >= self.page_retry:
                    if verbose:
                        print(f"第 {page} 页连续更换 {self.page_retry} 个IP仍失败，停止抓取")
                    break

                backoff = min(20, 2.5 * ip_attempt) + random.uniform(1.0, 3.0)
                if verbose:
                    print(f"失败后退避 {backoff:.2f} 秒，并重建 Session 后切换新代理重试")

                time.sleep(backoff)
                self._rebuild_session()

        assert last_error is not None
        raise last_error

    def _load_checkpoint(self) -> Dict[str, Any]:
        if not os.path.exists(self.checkpoint_file):
            return {
                "next_page": 1,
                "raw_rows": [],
            }

        with open(self.checkpoint_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_checkpoint(self, next_page: int, raw_rows: List[Dict[str, Any]]) -> None:
        payload = {
            "next_page": next_page,
            "raw_rows": raw_rows,
        }
        with open(self.checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def clear_checkpoint(self) -> None:
        if os.path.exists(self.checkpoint_file):
            os.remove(self.checkpoint_file)

    def _transform_row_raw(self, row: Dict[str, Any]) -> Dict[str, Any]:
        close_price = self._to_float(row.get("f2"))
        open_price = self._to_float(row.get("f17"))
        high_price = self._to_float(row.get("f15"))
        low_price = self._to_float(row.get("f16"))
        pct_change = self._to_float(row.get("f3"))
        change_amount = self._to_float(row.get("f4"))
        speed_pct = self._to_float(row.get("f22"))
        turnover_pct = self._to_float(row.get("f8"))
        volume_ratio = self._to_float(row.get("f10"))
        amplitude_pct = self._to_float(row.get("f7"))
        turnover_amount_yuan = self._to_float(row.get("f6"))
        total_market_cap_yuan = self._to_float(row.get("f20"))
        float_market_cap_yuan = self._to_float(row.get("f21"))
        pe_ratio = self._to_float(row.get("f9"))
        prev_close_price = self._to_float(row.get("f18"))

        float_shares = None
        if float_market_cap_yuan is not None and close_price not in (None, 0):
            float_shares = float_market_cap_yuan / close_price

        return {
            "代码": row.get("f12"),
            "名称": row.get("f14"),
            "开盘价": open_price,
            "关盘价": close_price,
            "最高价": high_price,
            "最低价": low_price,
            "昨收价": prev_close_price,
            "涨跌幅(%)": pct_change,
            "涨跌": change_amount,
            "涨速(%)": speed_pct,
            "换手(%)": turnover_pct,
            "量比": volume_ratio,
            "振幅(%)": amplitude_pct,
            "成交额_元": turnover_amount_yuan,
            "流通股_股": float_shares,
            "流通市值_元": float_market_cap_yuan,
            "总市值_元": total_market_cap_yuan,
            "市盈率": pe_ratio,
        }

    def _transform_row_display(self, raw_row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "代码": raw_row["代码"],
            "名称": raw_row["名称"],
            "开盘价": raw_row["开盘价"],
            "关盘价": raw_row["关盘价"],
            "最高价": raw_row["最高价"],
            "最低价": raw_row["最低价"],
            "涨跌幅(%)": raw_row["涨跌幅(%)"],
            "涨跌": raw_row["涨跌"],
            "涨速(%)": raw_row["涨速(%)"],
            "换手(%)": raw_row["换手(%)"],
            "量比": raw_row["量比"],
            "振幅(%)": raw_row["振幅(%)"],
            "成交额": self._format_yi_yuan(raw_row["成交额_元"]),
            "流通股": self._format_yi_shares(raw_row["流通股_股"]),
            "流通市值": self._format_yi_yuan(raw_row["流通市值_元"]),
            "市盈率": raw_row["市盈率"],
        }

    def fetch_all(
        self,
        max_pages: int = 80,
        verbose: bool = True,
        resume: bool = True,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        if resume:
            checkpoint = self._load_checkpoint()
            start_page = checkpoint.get("next_page", 1)
            raw_rows: List[Dict[str, Any]] = checkpoint.get("raw_rows", [])
            if verbose and start_page > 1:
                print(f"从断点继续，起始页: {start_page}")
        else:
            start_page = 1
            raw_rows = []

        for page in range(start_page, max_pages + 1):
            rows = self._request_page(page, verbose=verbose)

            if not rows:
                if verbose:
                    print(f"第 {page} 页为空，停止抓取")
                self._save_checkpoint(page, raw_rows)
                break

            if verbose:
                print(f"第 {page} 页: {len(rows)} 条")

            transformed = [self._transform_row_raw(x) for x in rows]
            transformed = [x for x in transformed if x["代码"] and x["名称"]]
            raw_rows.extend(transformed)

            self._save_checkpoint(page + 1, raw_rows)
            self._sleep_page()

            if self.batch_pages > 0 and page % self.batch_pages == 0:
                if verbose and self.batch_sleep_max > 0:
                    print(
                        f"已完成一批 {self.batch_pages} 页，休眠 "
                        f"{self.batch_sleep_min:.1f} ~ {self.batch_sleep_max:.1f} 秒"
                    )
                self._sleep_batch()

        display_rows = [self._transform_row_display(x) for x in raw_rows]
        return raw_rows, display_rows



if __name__ == "__main__":
    proxy_api_url = (
        "https://sch.shanchendaili.com/api.html"
        "?action=get_ip"
        "&key=HU1f9998719199159938hw9n"
        "&time=1"
        "&count=1"
        "&type=json"
        "&only=1"
    )

    provider = ShanchenProxyProvider(
        api_url=proxy_api_url,
        timeout=10,
        scheme="http",
    )

    quick_test_proxy(provider)

    crawler = EastmoneyAShareCrawler(
        page_size=100,
        timeout=(10, 20),
        page_retry=8,
        min_sleep=0.0,
        max_sleep=0.0,
        batch_pages=0,
        batch_sleep_min=0.0,
        batch_sleep_max=0.0,
        checkpoint_file="eastmoney_a_share_checkpoint.json",
        proxy_provider=provider,
    )

    raw_rows, display_rows = crawler.fetch_all(
        max_pages=80,
        verbose=True,
        resume=True,
    )

    print("总条数:", len(raw_rows))
    print("前 3 条 raw_rows:")
    for item in raw_rows[:3]:
        print(item)

    print("前 3 条 display_rows:")
    for item in display_rows[:3]:
        print(item)