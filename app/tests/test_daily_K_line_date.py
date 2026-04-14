"""
支持山城代理 API 参数化：time / count / type / only / province / city
支持统一对照组 + 长时代理额外慢速组
每个组合固定跑 10 次
单次拿到坏 IP、warm-up 失败、页中失败，都只结束该次样本，不会结束整个组合
整个测试矩阵会一直跑完
输出每个组合 10 次明细 + 汇总统计
输出均值 / 中位数 / 最小 / 最大 / warm-up 失败次数 / 0 页次数
可直接拿来后续估算每页成本
"""

import json
import random
import time
from datetime import datetime
from statistics import mean, median
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests


class ShanchenSingleProxyTester:
    BASE_URL = "https://82.push2.eastmoney.com/api/qt/clist/get"
    WARMUP_URL = "https://quote.eastmoney.com/center/gridlist.html#hs_a_board"

    def __init__(
        self,
        proxy_api_key: str,
        proxy_minutes: int,
        page_size: int = 100,
        timeout: int = 15,
        min_sleep: float = 2.0,
        max_sleep: float = 4.0,
        max_pages: int = 100,
        request_scheme: str = "http",
        only: int = 1,
        province: Optional[str] = None,
        city: Optional[str] = None,
    ):
        self.proxy_api_key = proxy_api_key
        self.proxy_minutes = proxy_minutes
        self.page_size = page_size
        self.timeout = timeout
        self.min_sleep = min_sleep
        self.max_sleep = max_sleep
        self.max_pages = max_pages
        self.request_scheme = request_scheme
        self.only = only
        self.province = province
        self.city = city

        self.proxy_expire_time: Optional[datetime] = None
        self.current_proxy_endpoint: Optional[Tuple[str, int]] = None
        self.session = self._build_session()

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

    @staticmethod
    def _random_user_agent() -> str:
        uas = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ]
        return random.choice(uas)

    def _build_proxy_api_url(self) -> str:
        params = {
            "action": "get_ip",
            "key": self.proxy_api_key,
            "time": self.proxy_minutes,
            "count": 1,
            "type": "json",
            "only": self.only,
        }
        if self.province:
            params["province"] = self.province
        if self.city:
            params["city"] = self.city
        return f"https://sch.shanchendaili.com/api.html?{urlencode(params)}"

    def _extract_ip_port_and_expire(
        self,
        data: Dict[str, Any],
    ) -> Tuple[Tuple[str, int], Optional[datetime]]:
        status = str(data.get("status", "")).strip()
        if status != "0":
            info = data.get("info", "未知错误")
            raise RuntimeError(f"代理接口返回失败: status={status}, info={info}")

        proxy_list = data.get("list") or []
        if not proxy_list:
            raise RuntimeError(f"代理接口未返回 list: {data}")

        item = proxy_list[0]
        ip = item.get("sever")
        port = item.get("port")
        if not ip or not port:
            raise RuntimeError(f"代理接口缺少 sever/port: {data}")

        expire_raw = data.get("expire")
        expire_dt = None
        if expire_raw:
            expire_dt = datetime.strptime(str(expire_raw), "%Y-%m-%d %H:%M:%S")

        return (str(ip).strip(), int(str(port).strip())), expire_dt

    def fetch_one_proxy(self) -> Dict[str, str]:
        api_url = self._build_proxy_api_url()
        print(f"代理 API: {api_url}")

        resp = requests.get(api_url, timeout=10)
        resp.raise_for_status()

        data = resp.json()
        endpoint, expire_dt = self._extract_ip_port_and_expire(data)

        self.current_proxy_endpoint = endpoint
        self.proxy_expire_time = expire_dt

        host, port = endpoint
        proxy_url = f"{self.request_scheme}://{host}:{port}"
        proxies = {
            "http": proxy_url,
            "https": proxy_url,
        }

        print("=" * 100)
        print(f"拿到新代理: {host}:{port}")
        print(f"代理时长: {self.proxy_minutes} 分钟")
        print(f"代理过期时间: {expire_dt}")
        print(f"请求间隔策略: {self.min_sleep} ~ {self.max_sleep} 秒")
        print(f"requests proxies: {proxies}")
        print("=" * 100)
        return proxies

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

    def _sleep_page(self) -> float:
        sec = random.uniform(self.min_sleep, self.max_sleep)
        print(f"页间休眠 {sec:.2f} 秒")
        time.sleep(sec)
        return sec

    def warm_up(self, proxies: Dict[str, str]) -> None:
        print("开始 warm-up")
        resp = self.session.get(
            self.WARMUP_URL,
            timeout=self.timeout,
            proxies=proxies,
        )
        resp.raise_for_status()
        print("warm-up 成功")

    def fetch_page_once(self, page: int, proxies: Dict[str, str]) -> int:
        self.session.headers["User-Agent"] = self._random_user_agent()
        params = self._build_params(page)

        print(f"请求第 {page} 页，使用代理: {proxies}")

        start = time.time()
        resp = self.session.get(
            self.BASE_URL,
            params=params,
            timeout=self.timeout,
            proxies=proxies,
        )
        resp.raise_for_status()
        cost = time.time() - start

        data = resp.json()
        payload = data.get("data") or {}
        diff = payload.get("diff") or []

        if isinstance(diff, dict):
            diff = list(diff.values())

        row_count = len(diff)
        print(f"第 {page} 页成功，条数={row_count}，耗时={cost:.2f} 秒")
        return row_count

    def run_single_proxy_test(self) -> Dict[str, Any]:
        all_start = time.time()

        result = {
            "proxy_minutes": self.proxy_minutes,
            "sleep_range": (self.min_sleep, self.max_sleep),
            "proxy_endpoint": None,
            "proxy_expire_time": None,
            "success_pages": 0,
            "total_rows": 0,
            "total_cost_seconds": 0.0,
            "avg_cost_per_page_seconds": 0.0,
            "failed_page": None,
            "failure_reason": None,
            "stopped_by_expire": False,
            "warmup_ok": False,
            "page_sleep_seconds": [],
        }

        proxies = self.fetch_one_proxy()
        result["proxy_endpoint"] = self.current_proxy_endpoint
        result["proxy_expire_time"] = (
            self.proxy_expire_time.strftime("%Y-%m-%d %H:%M:%S")
            if self.proxy_expire_time else None
        )

        try:
            self.warm_up(proxies)
            result["warmup_ok"] = True
        except Exception as e:
            result["failure_reason"] = f"warm-up 失败: {repr(e)}"
            result["total_cost_seconds"] = round(time.time() - all_start, 2)
            return result

        for page in range(1, self.max_pages + 1):
            if self.proxy_expire_time and datetime.now() >= self.proxy_expire_time:
                print(f"代理已过期，停止测试。过期时间={self.proxy_expire_time}")
                result["stopped_by_expire"] = True
                break

            try:
                row_count = self.fetch_page_once(page, proxies)
                result["success_pages"] += 1
                result["total_rows"] += row_count

                if row_count == 0:
                    print(f"第 {page} 页为空，停止测试")
                    break

            except Exception as e:
                result["failed_page"] = page
                result["failure_reason"] = repr(e)
                print(f"第 {page} 页失败，停止测试。原因: {repr(e)}")
                break

            if page < self.max_pages:
                slept = self._sleep_page()
                result["page_sleep_seconds"].append(round(slept, 2))

        result["total_cost_seconds"] = round(time.time() - all_start, 2)
        if result["success_pages"] > 0:
            result["avg_cost_per_page_seconds"] = round(
                result["total_cost_seconds"] / result["success_pages"],
                2,
            )

        return result


def build_test_matrix() -> List[Tuple[int, Tuple[float, float], str]]:
    matrix: List[Tuple[int, Tuple[float, float], str]] = []

    common_sleep_ranges = [
        ((2, 3), "common_2_3"),
        ((5, 7), "common_5_7"),
        ((10, 15), "common_10_15"),
    ]
    for minutes in [1, 3, 10, 30]:
        for sleep_range, tag in common_sleep_ranges:
            matrix.append((minutes, sleep_range, tag))

    long_only_sleep_ranges = [
        ((20, 30), "long_20_30"),
        ((30, 45), "long_30_45"),
    ]
    for minutes in [10, 30]:
        for sleep_range, tag in long_only_sleep_ranges:
            matrix.append((minutes, sleep_range, tag))

    return matrix


def summarize_case_results(
    proxy_minutes: int,
    sleep_range: Tuple[float, float],
    strategy_tag: str,
    sample_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    success_pages_list = [int(x.get("success_pages", 0) or 0) for x in sample_results]
    total_rows_list = [int(x.get("total_rows", 0) or 0) for x in sample_results]
    total_cost_list = [float(x.get("total_cost_seconds", 0.0) or 0.0) for x in sample_results]

    warmup_failures = 0
    zero_page_failures = 0
    expired_count = 0

    for x in sample_results:
        reason = str(x.get("failure_reason") or "")
        if "warm-up 失败" in reason:
            warmup_failures += 1
        if int(x.get("success_pages", 0) or 0) == 0:
            zero_page_failures += 1
        if x.get("stopped_by_expire"):
            expired_count += 1

    summary = {
        "proxy_minutes": proxy_minutes,
        "sleep_range": sleep_range,
        "strategy_tag": strategy_tag,
        "samples": len(sample_results),
        "sample_results": sample_results,
        "success_pages_samples": success_pages_list,
        "total_rows_samples": total_rows_list,
        "total_cost_seconds_samples": total_cost_list,
        "avg_success_pages": round(mean(success_pages_list), 2) if success_pages_list else 0.0,
        "median_success_pages": median(success_pages_list) if success_pages_list else 0.0,
        "min_success_pages": min(success_pages_list) if success_pages_list else 0,
        "max_success_pages": max(success_pages_list) if success_pages_list else 0,
        "avg_total_rows": round(mean(total_rows_list), 2) if total_rows_list else 0.0,
        "avg_total_cost_seconds": round(mean(total_cost_list), 2) if total_cost_list else 0.0,
        "warmup_failures": warmup_failures,
        "zero_page_failures": zero_page_failures,
        "expired_count": expired_count,
    }
    return summary


def run_case_n_times(
    proxy_api_key: str,
    proxy_minutes: int,
    sleep_range: Tuple[float, float],
    strategy_tag: str,
    samples: int = 10,
    page_size: int = 100,
    timeout: int = 15,
    max_pages: int = 100,
    only: int = 1,
    province: Optional[str] = None,
    city: Optional[str] = None,
) -> Dict[str, Any]:
    min_sleep, max_sleep = sleep_range
    sample_results: List[Dict[str, Any]] = []

    print("\n" + "=" * 140)
    print(
        f"开始组合测试: 分钟档={proxy_minutes}, "
        f"sleep={min_sleep}~{max_sleep}, tag={strategy_tag}, samples={samples}"
    )
    print("=" * 140)

    for i in range(1, samples + 1):
        print("\n" + "-" * 120)
        print(
            f"第 {i}/{samples} 次采样 -> "
            f"分钟档={proxy_minutes}, sleep={min_sleep}~{max_sleep}, tag={strategy_tag}"
        )
        print("-" * 120)

        try:
            tester = ShanchenSingleProxyTester(
                proxy_api_key=proxy_api_key,
                proxy_minutes=proxy_minutes,
                page_size=page_size,
                timeout=timeout,
                min_sleep=min_sleep,
                max_sleep=max_sleep,
                max_pages=max_pages,
                request_scheme="http",
                only=only,
                province=province,
                city=city,
            )
            result = tester.run_single_proxy_test()
        except Exception as e:
            result = {
                "proxy_minutes": proxy_minutes,
                "sleep_range": (min_sleep, max_sleep),
                "proxy_endpoint": None,
                "proxy_expire_time": None,
                "success_pages": 0,
                "total_rows": 0,
                "total_cost_seconds": 0.0,
                "avg_cost_per_page_seconds": 0.0,
                "failed_page": None,
                "failure_reason": f"sample_exception: {repr(e)}",
                "stopped_by_expire": False,
                "warmup_ok": False,
                "page_sleep_seconds": [],
            }

        result["strategy_tag"] = strategy_tag
        result["sample_index"] = i
        sample_results.append(result)

        print("单次采样结果:")
        print(json.dumps(result, ensure_ascii=False, indent=2))

        if i < samples:
            cooldown = random.uniform(3, 8)
            print(f"样本间休眠 {cooldown:.2f} 秒")
            time.sleep(cooldown)

    summary = summarize_case_results(
        proxy_minutes=proxy_minutes,
        sleep_range=sleep_range,
        strategy_tag=strategy_tag,
        sample_results=sample_results,
    )

    print("\n组合汇总结果:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("=" * 140)

    return summary


def compare_proxy_minutes_with_matrix(
    proxy_api_key: str,
    page_size: int = 100,
    timeout: int = 15,
    max_pages: int = 100,
    only: int = 1,
    province: Optional[str] = None,
    city: Optional[str] = None,
    samples_per_case: int = 10,
) -> List[Dict[str, Any]]:
    all_case_summaries: List[Dict[str, Any]] = []
    matrix = build_test_matrix()

    print("\n测试矩阵如下：")
    for minutes, sleep_range, tag in matrix:
        print(f"minutes={minutes}, sleep={sleep_range}, tag={tag}")
    print()

    for idx, (minutes, sleep_range, tag) in enumerate(matrix, start=1):
        print("\n" + "#" * 160)
        print(f"开始矩阵组合 {idx}/{len(matrix)}: minutes={minutes}, sleep={sleep_range}, tag={tag}")
        print("#" * 160)

        summary = run_case_n_times(
            proxy_api_key=proxy_api_key,
            proxy_minutes=minutes,
            sleep_range=sleep_range,
            strategy_tag=tag,
            samples=samples_per_case,
            page_size=page_size,
            timeout=timeout,
            max_pages=max_pages,
            only=only,
            province=province,
            city=city,
        )
        all_case_summaries.append(summary)

        if idx < len(matrix):
            cooldown = random.uniform(5, 12)
            print(f"组合间休眠 {cooldown:.2f} 秒")
            time.sleep(cooldown)

    return all_case_summaries


if __name__ == "__main__":
    PROXY_API_KEY = "HU1f9998719199159938hw9n"

    results = compare_proxy_minutes_with_matrix(
        proxy_api_key=PROXY_API_KEY,
        page_size=100,
        timeout=15,
        max_pages=100,
        only=1,
        province=None,
        city=None,
        samples_per_case=10,
    )

    print("\n最终对比结果（组合汇总）")
    print(json.dumps(results, ensure_ascii=False, indent=2))