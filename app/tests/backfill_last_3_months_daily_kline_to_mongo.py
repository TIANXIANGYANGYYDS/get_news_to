from __future__ import annotations

import math
import os
import random
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Protocol, Tuple
from uuid import uuid4

import requests
from pydantic import BaseModel, ConfigDict, Field
from pymongo import ASCENDING, MongoClient, UpdateOne
from pymongo.collection import Collection
from pymongo.errors import BulkWriteError

try:
    from dateutil.relativedelta import relativedelta
except Exception:
    relativedelta = None


# =============================================================================
# 1) 数据模型：保持和你现有 DailyKLineSnapshot 一致
# =============================================================================

class DailyKLineSnapshot(BaseModel):
    """
    A 股日度快照标准模型
    用于：
    1. 规范入库数据结构
    2. 将抓取结果中的中文字段转换为英文字段
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
    )

    id: str = Field(default_factory=lambda: str(uuid4()), description="独立主键 id")
    trade_date: str = Field(..., description="交易日期，格式 YYYY-MM-DD")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    symbol: str = Field(..., alias="代码", description="股票代码")
    name: str = Field(..., alias="名称", description="股票名称")

    open_price: Optional[float] = Field(default=None, alias="开盘价", description="开盘价")
    close_price: Optional[float] = Field(default=None, alias="关盘价", description="收盘价")
    high_price: Optional[float] = Field(default=None, alias="最高价", description="最高价")
    low_price: Optional[float] = Field(default=None, alias="最低价", description="最低价")
    prev_close_price: Optional[float] = Field(default=None, alias="昨收价", description="昨收价")

    change_percent: Optional[float] = Field(default=None, alias="涨跌幅(%)", description="涨跌幅百分比")
    change_amount: Optional[float] = Field(default=None, alias="涨跌", description="涨跌额")
    speed_percent: Optional[float] = Field(default=None, alias="涨速(%)", description="涨速百分比")
    turnover_percent: Optional[float] = Field(default=None, alias="换手(%)", description="换手率")
    volume_ratio: Optional[float] = Field(default=None, alias="量比", description="量比")
    amplitude_percent: Optional[float] = Field(default=None, alias="振幅(%)", description="振幅百分比")

    turnover_amount_yuan: Optional[float] = Field(default=None, alias="成交额_元", description="成交额，单位元")
    float_shares: Optional[float] = Field(default=None, alias="流通股_股", description="流通股数")
    float_market_cap_yuan: Optional[float] = Field(default=None, alias="流通市值_元", description="流通市值，单位元")
    total_market_cap_yuan: Optional[float] = Field(default=None, alias="总市值_元", description="总市值，单位元")
    pe_ratio: Optional[float] = Field(default=None, alias="市盈率", description="市盈率")

    @classmethod
    def from_raw_row(
        cls,
        raw_row: dict[str, Any],
        trade_date: str,
        now: datetime,
    ) -> "DailyKLineSnapshot":
        payload = {
            **raw_row,
            "trade_date": trade_date,
            "created_at": now,
            "updated_at": now,
        }
        return cls.model_validate(payload)

    def to_mongo_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=False)


# =============================================================================
# 2) 代理层
# =============================================================================

class ProxyProvider(Protocol):
    def get_requests_proxies(self) -> Optional[Dict[str, str]]:
        ...

    def on_success(self) -> None:
        ...

    def on_failure(self, exc: Exception) -> None:
        ...


class NoProxyProvider:
    def get_requests_proxies(self) -> Optional[Dict[str, str]]:
        return None

    def on_success(self) -> None:
        pass

    def on_failure(self, exc: Exception) -> None:
        pass


class ShanchenProxyProvider:
    """
    山城代理 API 接入版（缓存当前代理版）

    逻辑：
    - 默认不会每次请求都切换代理
    - 只在“当前代理不存在”时拉取新代理
    - 当前代理请求失败后，清空并在下一次请求时更换
    """

    def __init__(
        self,
        api_url: str,
        timeout: int = 10,
        scheme: str = "http",
    ) -> None:
        self.api_url = api_url
        self.timeout = timeout
        self.scheme = scheme

        self.last_endpoint: Optional[Tuple[str, int]] = None
        self.current_endpoint: Optional[Tuple[str, int]] = None
        self.current_proxies: Optional[Dict[str, str]] = None

    def _extract_ip_port(self, data: Any) -> Optional[Tuple[str, int]]:
        if isinstance(data, dict):
            status = str(data.get("status", "")).strip()
            if status and status != "0":
                info = data.get("info", "未知错误")
                print(f"[代理池] 代理接口返回失败 status={status}, info={info}")
                return None

            candidates = data.get("list")
            if isinstance(candidates, list) and candidates:
                item = candidates[0]
                if isinstance(item, dict):
                    ip = (
                        item.get("sever")
                        or item.get("server")
                        or item.get("ip")
                        or item.get("IP")
                        or item.get("host")
                    )
                    port = item.get("port") or item.get("Port")
                    if ip and port:
                        return str(ip).strip(), int(str(port).strip())

        if isinstance(data, str):
            text = data.strip()
            if not text:
                return None

            first_line = text.splitlines()[0].strip()
            if ":" in first_line:
                host, port = first_line.split(":", 1)
                host = host.strip()
                port = port.strip()
                if host and port:
                    return host, int(port)

        return None

    def _fetch_proxy_endpoint(self) -> Optional[Tuple[str, int]]:
        try:
            resp = requests.get(self.api_url, timeout=self.timeout)
            resp.raise_for_status()

            text = resp.text.strip()

            try:
                data = resp.json()
                endpoint = self._extract_ip_port(data)
                if endpoint is None:
                    print(f"[代理池] JSON 已返回，但未解析出 ip:port，原始 JSON: {data}")
                else:
                    print(f"[代理池] 获取到新代理: {endpoint[0]}:{endpoint[1]}")
                self.last_endpoint = endpoint
                return endpoint
            except Exception:
                endpoint = self._extract_ip_port(text)
                if endpoint is None:
                    print(f"[代理池] 文本已返回，但未解析出 ip:port，原始文本: {text}")
                else:
                    print(f"[代理池] 获取到新代理: {endpoint[0]}:{endpoint[1]}")
                self.last_endpoint = endpoint
                return endpoint

        except Exception as e:
            print(f"[代理池] 获取代理失败: {repr(e)}")
            self.last_endpoint = None
            return None

    def _build_proxies_from_endpoint(self, endpoint: Tuple[str, int]) -> Dict[str, str]:
        host, port = endpoint
        proxy_url = f"{self.scheme}://{host}:{port}"
        return {
            "http": proxy_url,
            "https": proxy_url,
        }

    def _clear_current_proxy(self) -> None:
        self.current_endpoint = None
        self.current_proxies = None

    def get_requests_proxies(self) -> Optional[Dict[str, str]]:
        if self.current_proxies is not None and self.current_endpoint is not None:
            print(
                f"[代理池] 继续复用当前代理: "
                f"{self.current_endpoint[0]}:{self.current_endpoint[1]}"
            )
            return self.current_proxies

        endpoint = self._fetch_proxy_endpoint()
        if endpoint is None:
            print("[代理池] 当前没有拿到可用代理，本次请求返回 None")
            self._clear_current_proxy()
            return None

        proxies = self._build_proxies_from_endpoint(endpoint)
        self.current_endpoint = endpoint
        self.current_proxies = proxies

        print(f"[代理池] 切换为新代理: {endpoint[0]}:{endpoint[1]}")
        print(f"[代理池] 本次 requests 使用代理: {proxies}")
        return proxies

    def on_success(self) -> None:
        if self.current_endpoint:
            print(
                f"[代理池] 当前代理请求成功，继续复用: "
                f"{self.current_endpoint[0]}:{self.current_endpoint[1]}"
            )

    def on_failure(self, exc: Exception) -> None:
        if self.current_endpoint:
            print(
                f"[代理池] 当前代理请求失败，准备弃用: "
                f"{self.current_endpoint[0]}:{self.current_endpoint[1]} | {repr(exc)}"
            )
        else:
            print(f"[代理池] 请求失败，但当前未记录代理: {repr(exc)}")

        self._clear_current_proxy()


# =============================================================================
# 3) 抓取器
# =============================================================================

class EastmoneyBackfillCrawler:
    """
    功能：
    1. 抓取当前 A 股全市场股票列表
    2. 对每只股票抓取过去三个月历史日K（单股票单次区间请求）
    """

    LIST_URL = "https://82.push2.eastmoney.com/api/qt/clist/get"
    HISTORY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    def __init__(
        self,
        timeout: Tuple[int, int] = (10, 20),
        page_size: int = 500,
        page_retry: int = 8,
        min_sleep: float = 0.05,
        max_sleep: float = 0.2,
        proxy_provider: Optional[ProxyProvider] = None,
    ) -> None:
        self.timeout = timeout
        self.page_size = page_size
        self.page_retry = page_retry
        self.min_sleep = min_sleep
        self.max_sleep = max_sleep
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
    def _build_session() -> requests.Session:
        s = requests.Session()
        s.trust_env = False
        s.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
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
    def _random_sleep(min_sleep: float, max_sleep: float) -> None:
        if max_sleep <= 0:
            return
        time.sleep(random.uniform(min_sleep, max_sleep))

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        if value in (None, "", "-", "--"):
            return None
        try:
            v = float(value)
            if math.isnan(v):
                return None
            return v
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_trade_date(text: str) -> str:
        text = str(text).strip()
        if "-" in text:
            return text
        if len(text) == 8 and text.isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        raise ValueError(f"非法日期格式: {text}")

    @staticmethod
    def infer_secid(symbol: str) -> str:
        """
        东方财富 secid 规则：
        - 上海：1.xxxxxx
        - 深圳/北交：0.xxxxxx
        """
        symbol = symbol.strip()
        if len(symbol) != 6 or not symbol.isdigit():
            raise ValueError(f"非法股票代码: {symbol}")

        if symbol.startswith(("5", "6", "9")):
            market = 1
        elif symbol.startswith(("0", "1", "2", "3", "4", "8")):
            market = 0
        else:
            raise ValueError(f"无法识别市场: {symbol}")

        return f"{market}.{symbol}"

    @staticmethod
    def get_last_3_months_range() -> Tuple[str, str]:
        now = datetime.now()
        end_date = now.date()

        if relativedelta is not None:
            begin_date = (now - relativedelta(months=3)).date()
        else:
            begin_date = (now - timedelta(days=92)).date()

        return begin_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d")

    def _get_proxies(self) -> Optional[Dict[str, str]]:
        return self.proxy_provider.get_requests_proxies()

    def _request_json(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        last_error: Optional[Exception] = None

        for i in range(1, self.page_retry + 1):
            proxies = self._get_proxies()
            try:
                self.session.headers["User-Agent"] = random.choice(
                    [
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    ]
                )

                print(f"[REQ] 第 {i}/{self.page_retry} 次 url={url} proxies={proxies}")

                resp = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                    proxies=proxies,
                )
                resp.raise_for_status()
                data = resp.json()

                self.proxy_provider.on_success()
                return data

            except Exception as e:
                last_error = e
                print(f"[WARN] 请求失败，第 {i}/{self.page_retry} 次: {repr(e)}")
                self.proxy_provider.on_failure(e)
                self._rebuild_session()

                if i < self.page_retry:
                    sleep_s = min(8.0, 1.5 * i) + random.uniform(0.5, 1.2)
                    print(f"[WARN] {sleep_s:.2f}s 后切换新代理重试")
                    time.sleep(sleep_s)

        assert last_error is not None
        raise last_error

    def fetch_all_stock_list(self, verbose: bool = True) -> List[Dict[str, Any]]:
        """
        抓取当前A股全市场股票列表
        """
        all_rows: List[Dict[str, Any]] = []
        page = 1

        while True:
            params = {
                "pn": page,
                "pz": self.page_size,
                "po": 1,
                "np": 1,
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": 2,
                "invt": 2,
                "fid": "f3",
                "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
                "fields": "f12,f14",
                "_": int(time.time() * 1000),
            }

            data = self._request_json(self.LIST_URL, params)
            payload = data.get("data") or {}
            diff = payload.get("diff") or []

            if isinstance(diff, dict):
                diff = list(diff.values())

            if not diff:
                if verbose:
                    print(f"[INFO] 股票列表抓取结束，最后页为空: page={page}")
                break

            for item in diff:
                symbol = str(item.get("f12") or "").strip()
                name = str(item.get("f14") or "").strip()
                if symbol and name:
                    all_rows.append(
                        {
                            "代码": symbol,
                            "名称": name,
                        }
                    )

            if verbose:
                print(f"[INFO] 股票列表第 {page} 页: {len(diff)} 条，累计 {len(all_rows)} 条")

            page += 1
            self._random_sleep(self.min_sleep, self.max_sleep)

        dedup: Dict[str, Dict[str, Any]] = {}
        for row in all_rows:
            dedup[row["代码"]] = row

        result = list(dedup.values())
        result.sort(key=lambda x: x["代码"])

        if verbose:
            print(f"[INFO] 全市场股票总数(去重后): {len(result)}")

        return result

    def fetch_symbol_history_last_3_months(
        self,
        symbol: str,
        verbose: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        单股票单次区间请求：
        一次请求返回这只股票过去三个月的整段日K
        """
        secid = self.infer_secid(symbol)
        beg, end = self.get_last_3_months_range()

        params = {
            "secid": secid,
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",   # 日K
            "fqt": "1",     # 前复权
            "beg": beg,
            "end": end,
            "_": int(time.time() * 1000),
        }

        data = self._request_json(self.HISTORY_URL, params)
        payload = data.get("data") or {}

        if not payload:
            if verbose:
                print(f"[WARN] {symbol} 历史K线 data 为空")
            return []

        name = str(payload.get("name") or "").strip()
        klines = payload.get("klines") or []

        if not isinstance(klines, list) or not klines:
            if verbose:
                print(f"[WARN] {symbol} 历史K线为空")
            return []

        rows: List[Dict[str, Any]] = []
        prev_close: Optional[float] = None

        for item in klines:
            if not isinstance(item, str):
                continue

            parts = item.split(",")
            if len(parts) < 11:
                continue

            trade_date = self._normalize_trade_date(parts[0])

            open_price = self._to_float(parts[1])
            close_price = self._to_float(parts[2])
            high_price = self._to_float(parts[3])
            low_price = self._to_float(parts[4])
            turnover_amount_yuan = self._to_float(parts[6])
            amplitude_percent = self._to_float(parts[7])
            change_percent = self._to_float(parts[8])
            change_amount = self._to_float(parts[9])
            turnover_percent = self._to_float(parts[10])

            row = {
                "代码": symbol,
                "名称": name,
                "开盘价": open_price,
                "关盘价": close_price,
                "最高价": high_price,
                "最低价": low_price,
                "昨收价": prev_close,
                "涨跌幅(%)": change_percent,
                "涨跌": change_amount,
                "涨速(%)": None,
                "换手(%)": turnover_percent,
                "量比": None,
                "振幅(%)": amplitude_percent,
                "成交额_元": turnover_amount_yuan,
                "流通股_股": None,
                "流通市值_元": None,
                "总市值_元": None,
                "市盈率": None,
                "trade_date": trade_date,
            }
            rows.append(row)
            prev_close = close_price

        if verbose:
            print(f"[INFO] {symbol} {name} 历史K线条数: {len(rows)}")

        return rows


# =============================================================================
# 4) Mongo Repo
# =============================================================================

class DailyKLineMongoRepo:
    """
    独立脚本版 Mongo Repo
    """

    def __init__(
        self,
        mongo_uri: str,
        mongo_db_name: str,
        collection_name: str = "daily_kline_snapshots",
    ) -> None:
        self.client = MongoClient(mongo_uri)
        self.db = self.client[mongo_db_name]
        self.collection: Collection = self.db[collection_name]

    def ensure_indexes(self) -> None:
        self.collection.create_index(
            [("symbol", ASCENDING), ("trade_date", ASCENDING)],
            unique=True,
            name="uniq_symbol_trade_date",
            background=True,
        )
        self.collection.create_index(
            [("trade_date", ASCENDING)],
            name="idx_trade_date",
            background=True,
        )
        self.collection.create_index(
            [("symbol", ASCENDING)],
            name="idx_symbol",
            background=True,
        )

    def load_symbols_from_existing_collection(self) -> List[Dict[str, Any]]:
        rows = list(
            self.collection.aggregate(
                [
                    {
                        "$group": {
                            "_id": "$symbol",
                            "name": {"$first": "$name"},
                        }
                    },
                    {
                        "$project": {
                            "_id": 0,
                            "代码": "$_id",
                            "名称": "$name",
                        }
                    },
                    {
                        "$sort": {"代码": 1}
                    },
                ]
            )
        )
        return rows

    def bulk_upsert_snapshots(
        self,
        snapshots: List[DailyKLineSnapshot],
        batch_size: int = 1000,
    ) -> Tuple[int, int, int]:
        if not snapshots:
            return 0, 0, 0

        total_upserted = 0
        total_matched = 0
        total_modified = 0

        for i in range(0, len(snapshots), batch_size):
            batch = snapshots[i:i + batch_size]
            ops: List[UpdateOne] = []

            for item in batch:
                doc = item.to_mongo_dict()
                ops.append(
                    UpdateOne(
                        filter={
                            "symbol": item.symbol,
                            "trade_date": item.trade_date,
                        },
                        update={
                            "$set": {
                                k: v for k, v in doc.items()
                                if k != "id"
                            },
                            "$setOnInsert": {
                                "id": item.id,
                            },
                        },
                        upsert=True,
                    )
                )

            try:
                result = self.collection.bulk_write(ops, ordered=False)
                total_upserted += int(result.upserted_count or 0)
                total_matched += int(result.matched_count or 0)
                total_modified += int(result.modified_count or 0)
            except BulkWriteError as e:
                print(f"[ERROR] bulk_write 失败: {e.details}")
                raise

        return total_upserted, total_matched, total_modified


# =============================================================================
# 5) 组装与主流程
# =============================================================================

def build_snapshots_from_rows(
    raw_rows: List[Dict[str, Any]],
    now: datetime,
) -> List[DailyKLineSnapshot]:
    snapshots: List[DailyKLineSnapshot] = []

    for row in raw_rows:
        trade_date = row.pop("trade_date")
        snapshot = DailyKLineSnapshot.from_raw_row(
            raw_row=row,
            trade_date=trade_date,
            now=now,
        )
        snapshots.append(snapshot)

    return snapshots
MONGO_URI="mongodb://shilv:shilv114514%21@127.0.0.1:27017"
MONGO_DB_NAME="daily_pe_reporter"

SHANCHEN_PROXY_KEY="HU1f9998719199159938hw9n"

def build_proxy_provider_from_env() -> ProxyProvider:
    """
    环境变量：
    - SHANCHEN_PROXY_KEY
    - SHANCHEN_PROXY_TIME，默认 3
    - SHANCHEN_PROXY_COUNT，默认 1
    - SHANCHEN_PROXY_ONLY，默认 1
    - SHANCHEN_PROXY_SCHEME，默认 http
    """
    proxy_key = SHANCHEN_PROXY_KEY
    if not proxy_key:
        print("[WARN] 未配置 SHANCHEN_PROXY_KEY，将使用直连模式")
        return NoProxyProvider()

    proxy_time = os.getenv("SHANCHEN_PROXY_TIME", "3").strip() or "3"
    proxy_count = os.getenv("SHANCHEN_PROXY_COUNT", "1").strip() or "1"
    proxy_only = os.getenv("SHANCHEN_PROXY_ONLY", "1").strip() or "1"
    proxy_scheme = os.getenv("SHANCHEN_PROXY_SCHEME", "http").strip() or "http"

    proxy_api_url = (
        "https://sch.shanchendaili.com/api.html"
        f"?action=get_ip"
        f"&key={proxy_key}"
        f"&time={proxy_time}"
        f"&count={proxy_count}"
        f"&type=json"
        f"&only={proxy_only}"
    )

    print(f"[INFO] 使用山城代理，time={proxy_time}, count={proxy_count}, only={proxy_only}, scheme={proxy_scheme}")

    return ShanchenProxyProvider(
        api_url=proxy_api_url,
        timeout=10,
        scheme=proxy_scheme,
    )


def main() -> int:
    mongo_uri = MONGO_URI
    mongo_db_name = MONGO_DB_NAME
    collection_name = os.getenv("DAILY_KLINE_COLLECTION", "daily_kline_snapshots").strip()

    if not mongo_uri:
        print("[ERROR] 缺少环境变量 MONGO_URI")
        return 1

    if not mongo_db_name:
        print("[ERROR] 缺少环境变量 MONGO_DB_NAME")
        return 1

    proxy_provider = build_proxy_provider_from_env()

    crawler = EastmoneyBackfillCrawler(
        timeout=(10, 20),
        page_size=500,
        page_retry=8,
        min_sleep=0.05,
        max_sleep=0.15,
        proxy_provider=proxy_provider,
    )

    repo = DailyKLineMongoRepo(
        mongo_uri=mongo_uri,
        mongo_db_name=mongo_db_name,
        collection_name=collection_name,
    )
    repo.ensure_indexes()

    print("=" * 100)
    print("[STEP 1] 优先从现有库中读取股票列表")
    stock_list = repo.load_symbols_from_existing_collection()
    if stock_list:
        print(f"[OK] 从现有库中读取到股票数: {len(stock_list)}")
    else:
        print("[INFO] 现有库中没有 symbol，开始抓取当前A股全市场股票列表")
        stock_list = crawler.fetch_all_stock_list(verbose=True)
        print(f"[OK] 当前A股股票数: {len(stock_list)}")

    total_symbol_count = len(stock_list)
    total_history_row_count = 0
    total_snapshot_count = 0
    total_upserted = 0
    total_matched = 0
    total_modified = 0
    failed_symbols: List[str] = []

    print("=" * 100)
    print("[STEP 2] 逐只抓取过去三个月历史日K并入库")
    print("[INFO] 注意：单只股票只会请求 1 次历史K线接口，返回整个三个月区间")

    for idx, stock in enumerate(stock_list, start=1):
        symbol = stock["代码"]
        name = stock["名称"]

        print("-" * 100)
        print(f"[{idx}/{total_symbol_count}] 开始处理: {symbol} {name}")

        try:
            raw_rows = crawler.fetch_symbol_history_last_3_months(
                symbol=symbol,
                verbose=False,
            )

            if not raw_rows:
                print(f"[WARN] {symbol} {name} 未抓到历史数据，跳过")
                continue

            total_history_row_count += len(raw_rows)

            now = datetime.now()
            snapshots = build_snapshots_from_rows(raw_rows=raw_rows, now=now)
            total_snapshot_count += len(snapshots)

            upserted_count, matched_count, modified_count = repo.bulk_upsert_snapshots(
                snapshots=snapshots,
                batch_size=1000,
            )

            total_upserted += upserted_count
            total_matched += matched_count
            total_modified += modified_count

            print(
                f"[OK] {symbol} {name} "
                f"历史行数={len(raw_rows)} "
                f"upserted={upserted_count} matched={matched_count} modified={modified_count}"
            )

        except Exception as e:
            failed_symbols.append(symbol)
            print(f"[ERROR] {symbol} {name} 处理失败: {repr(e)}")

        crawler._random_sleep(0.05, 0.2)

    print("=" * 100)
    print("[SUMMARY] 回补完成")
    print(f"股票总数: {total_symbol_count}")
    print(f"历史K线总行数: {total_history_row_count}")
    print(f"构造快照总数: {total_snapshot_count}")
    print(f"bulk upsert upserted_count 总计: {total_upserted}")
    print(f"bulk upsert matched_count 总计: {total_matched}")
    print(f"bulk upsert modified_count 总计: {total_modified}")
    print(f"失败股票数: {len(failed_symbols)}")
    if failed_symbols:
        print(f"失败股票代码前20个: {failed_symbols[:20]}")
    print("=" * 100)

    return 0


if __name__ == "__main__":
    sys.exit(main())