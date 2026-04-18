from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

from proxy_provider import ProxyProvider, ShanchenProxyProvider


class FiveMajorIndexCrawler:
    """
    五大指数实时抓取器

    逻辑：
    1. 先使用本机 IP 直接请求一次
    2. 如果本机 IP 失败，则开始调用 proxy_provider 获取代理
    3. 代理请求失败后，通知 provider.on_failure(exc)
    4. 然后继续循环，再次让 provider 获取新代理
    5. 直到成功；如果你不想无限重试，可以把 max_total_attempts 改成整数

    trade_date 逻辑：
    1. 先通过上游历史日 K 接口拿最近交易日 date（权威来源优先）
    2. 若失败，再使用本地时间规则兜底计算
    """

    URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    HISTORY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    CHINA_TZ = ZoneInfo("Asia/Shanghai")

    # 东方财富 secid 规则：
    # 上交所指数一般是 1.xxxxxx
    # 深市/北证相关这里使用 0.xxxxxx
    INDEX_SECIDS: Dict[str, str] = {
        "上证指数": "1.000001",
        "深证成指": "0.399001",
        "创业板指": "0.399006",
        "科创50": "1.000688",
        "北证50": "0.899050",
    }

    # 常用行情字段
    # f2: 最新价
    # f3: 涨跌幅
    # f4: 涨跌额
    # f5: 成交量
    # f6: 成交额
    # f12: 代码
    # f13: 市场编号
    # f14: 名称
    # f15: 最高
    # f16: 最低
    # f17: 今开
    # f18: 昨收
    FIELDS = "f2,f3,f4,f5,f6,f12,f13,f14,f15,f16,f17,f18"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/135.0.0.0 Safari/537.36"
        ),
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "application/json,text/plain,*/*",
        "Connection": "keep-alive",
    }

    def __init__(
        self,
        proxy_provider: ProxyProvider,
        timeout: int = 15,
        retry_sleep: float = 2.0,
        max_total_attempts: Optional[int] = None,
    ) -> None:
        """
        :param proxy_provider: 你现有的代理提供器对象
        :param timeout: 单次请求超时秒数
        :param retry_sleep: 每次失败后的等待秒数
        :param max_total_attempts:
            - None: 无限重试，直到成功
            - 整数: 最多重试多少次（含本机 IP 那次）
        """
        self.proxy_provider = proxy_provider
        self.timeout = timeout
        self.retry_sleep = retry_sleep
        self.max_total_attempts = max_total_attempts

        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value in (None, "", "-"):
            return None
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        if value in (None, "", "-"):
            return None
        try:
            return int(float(value))
        except Exception:
            return None

    @classmethod
    def _calc_trade_date(cls) -> str:
        """
        本地兜底 trade_date 计算逻辑：
        1. 使用中国时区
        2. 周六 -> 回退到周五
        3. 周日 -> 回退到周五
        4. 工作日 09:00 前 -> 回退到上一个工作日
        5. 其余时间 -> 当天

        注意：
        - 这里没有接入法定节假日交易日历
        - 仅作为上游权威日期获取失败时的兜底方案
        """
        now = datetime.now(cls.CHINA_TZ)
        current_date = now.date()
        weekday = current_date.weekday()  # Monday=0, Sunday=6

        if weekday == 5:
            trade_date = current_date - timedelta(days=1)
        elif weekday == 6:
            trade_date = current_date - timedelta(days=2)
        elif now.hour < 9:
            if weekday == 0:
                trade_date = current_date - timedelta(days=3)
            else:
                trade_date = current_date - timedelta(days=1)
        else:
            trade_date = current_date

        return trade_date.strftime("%Y-%m-%d")

    def _fetch_authoritative_trade_date(self) -> Optional[str]:
        """
        优先从上游历史日 K 接口获取最近一个交易日。
        获取失败时返回 None，由本地 _calc_trade_date() 兜底。

        这里不改你现有的实时抓取主体逻辑，也不改现有代理重试主流程。
        """
        anchor_secid = self.INDEX_SECIDS["上证指数"]

        params = {
            "secid": anchor_secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "0",
            "beg": "0",
            "end": "20500101",
            "lmt": "1",
            "_": str(int(time.time() * 1000)),
        }

        try:
            resp = self.session.get(
                self.HISTORY_KLINE_URL,
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()

            data = resp.json()
            klines = ((data or {}).get("data") or {}).get("klines") or []
            if not klines:
                return None

            last_kline = klines[-1]
            if not isinstance(last_kline, str):
                return None

            parts = last_kline.split(",")
            if not parts:
                return None

            trade_date = parts[0].strip()
            if len(trade_date) == 10:
                return trade_date

            return None
        except Exception as exc:
            print(f"[五大指数] 获取上游权威 trade_date 失败，回退本地计算: {repr(exc)}")
            return None

    def _build_params(self) -> Dict[str, Any]:
        return {
            "OSVersion": "14.3",
            "appVersion": "6.3.8",
            "fields": self.FIELDS,
            "fltt": "2",
            "plat": "Iphone",
            "product": "EFund",
            "secids": ",".join(self.INDEX_SECIDS.values()),
            "serverVersion": "6.3.6",
            "version": "6.3.8",
            "_": str(int(time.time() * 1000)),
        }

    def _do_request(
        self,
        proxies: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        resp = self.session.get(
            self.URL,
            params=self._build_params(),
            proxies=proxies,
            timeout=self.timeout,
        )
        resp.raise_for_status()

        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"接口返回不是 dict: {data!r}")

        inner = data.get("data") or {}
        diff = inner.get("diff")
        if not diff:
            raise RuntimeError(f"接口返回为空或没有 diff: {data}")

        return data

    def _normalize(self, raw_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        code_to_name = {
            secid.split(".")[-1]: display_name
            for display_name, secid in self.INDEX_SECIDS.items()
        }

        result_map: Dict[str, Dict[str, Any]] = {}
        now_str = datetime.now(self.CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        authoritative_trade_date = self._fetch_authoritative_trade_date()
        trade_date = authoritative_trade_date or self._calc_trade_date()

        for item in raw_rows:
            code = str(item.get("f12", "")).zfill(6)
            if code not in code_to_name:
                continue

            result_map[code] = {
                "index_name": code_to_name[code],
                "index_code": code,
                "trade_date": trade_date,
                "latest": self._safe_float(item.get("f2")),
                "pct_change": self._safe_float(item.get("f3")),
                "change": self._safe_float(item.get("f4")),
                "volume": self._safe_int(item.get("f5")),
                "amount": self._safe_float(item.get("f6")),
                "high": self._safe_float(item.get("f15")),
                "low": self._safe_float(item.get("f16")),
                "open": self._safe_float(item.get("f17")),
                "prev_close": self._safe_float(item.get("f18")),
                "market_id": self._safe_int(item.get("f13")),
                "raw_name": item.get("f14"),
                "source": "eastmoney",
                "crawl_time": now_str,
            }

        rows: List[Dict[str, Any]] = []
        for display_name, secid in self.INDEX_SECIDS.items():
            code = secid.split(".")[-1]
            if code not in result_map:
                raise RuntimeError(f"批量结果中缺少指数 {display_name}({code})")
            rows.append(result_map[code])

        return rows

    def _fetch_with_local_ip(self) -> List[Dict[str, Any]]:
        print("[五大指数] 先尝试使用本机 IP 直接抓取")
        data = self._do_request(proxies=None)
        diff = (data.get("data") or {}).get("diff") or []
        rows = self._normalize(diff)
        print("[五大指数] 本机 IP 抓取成功")
        return rows

    def _fetch_with_proxy_retry_forever(self, start_attempt: int) -> List[Dict[str, Any]]:
        attempt = start_attempt

        while True:
            if self.max_total_attempts is not None and attempt > self.max_total_attempts:
                raise RuntimeError(f"抓取失败，已达到最大尝试次数: {self.max_total_attempts}")

            proxies = self.proxy_provider.get_requests_proxies()
            print(f"[五大指数] 第 {attempt} 次尝试，代理参数: {proxies}")

            if not proxies:
                print("[五大指数] provider 没有返回可用代理，等待后继续重试")
                time.sleep(self.retry_sleep)
                attempt += 1
                continue

            try:
                data = self._do_request(proxies=proxies)
                diff = (data.get("data") or {}).get("diff") or []
                rows = self._normalize(diff)
                self.proxy_provider.on_success()
                print("[五大指数] 代理抓取成功")
                return rows
            except Exception as exc:
                self.proxy_provider.on_failure(exc)
                print(f"[五大指数] 代理抓取失败: {repr(exc)}")
                time.sleep(self.retry_sleep)
                attempt += 1

    def fetch(self) -> List[Dict[str, Any]]:
        """
        对外统一入口：
        - 先本机 IP
        - 失败后代理循环重试
        """
        attempt = 1

        try:
            return self._fetch_with_local_ip()
        except Exception as exc:
            print(f"[五大指数] 本机 IP 抓取失败: {repr(exc)}")
            time.sleep(self.retry_sleep)
            attempt += 1

        print("[五大指数] 开始切换到代理模式重试")
        return self._fetch_with_proxy_retry_forever(start_attempt=attempt)


if __name__ == "__main__":
    # 这里填你山城代理 API
    proxy_api_url = (
        "http://你的代理接口地址"
        # 例如:
        # "http://api.shanchendaili.com/api.html?action=get_ip&key=你的key"
        # "&time=1&count=1&type=json&only=1"
    )

    proxy_provider = ShanchenProxyProvider(
        api_url=proxy_api_url,
        timeout=10,
        scheme="http",
    )

    crawler = FiveMajorIndexCrawler(
        proxy_provider=proxy_provider,
        timeout=15,
        retry_sleep=2.0,
        max_total_attempts=None,  # None = 无限重试，直到成功
    )

    rows = crawler.fetch()

    print("=" * 140)
    print("五大指数实时快照")
    print("=" * 140)
    for row in rows:
        print(
            f"{row['index_name']}({row['index_code']}) | "
            f"trade_date={row['trade_date']} | "
            f"最新={row['latest']} | "
            f"涨跌额={row['change']} | "
            f"涨跌幅={row['pct_change']}% | "
            f"今开={row['open']} | "
            f"最高={row['high']} | "
            f"最低={row['low']} | "
            f"昨收={row['prev_close']} | "
            f"成交量={row['volume']} | "
            f"成交额={row['amount']} | "
            f"抓取时间={row['crawl_time']}"
        )