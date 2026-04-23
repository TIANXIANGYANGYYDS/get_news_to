from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import sys

# 让脚本在 app/tests 目录下直接执行时，也能正确导入项目根目录下的 app 包
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import exchange_calendars as xcals
import pandas as pd

from app.config import settings
from app.db.mongo import client, db
from app.repo.daily_kline_snapshot import DailyKLineSnapshotRepository
from app.llm.k_line_analysis_llm import analyze_buy_point
from app.crawlers.Get_Daily_K_line_data import (
    EastmoneyAShareCrawler,
    ShanchenProxyProvider,
)
from app.crawlers.proxy_provider import NoProxyProvider


XSHG = xcals.get_calendar("XSHG")
CN_TZ = ZoneInfo("Asia/Shanghai")


def get_a_share_trade_dates(now: datetime | None = None) -> tuple[str, str]:
    """
    复用你项目 bootstrap 里的交易日语义：
    - 9点前：默认仍归到前一个交易日
    - 9点后：归到当天；若非交易日则回退最近交易日

    返回：
    - today_trade_date: YYYY-MM-DD
    - prev_trade_date: YYYY-MM-DD
    """
    now = now.astimezone(CN_TZ) if now else datetime.now(CN_TZ)
    candidate_date = now.date() if now.hour >= 9 else (now - timedelta(days=1)).date()
    candidate = pd.Timestamp(candidate_date)

    if XSHG.is_session(candidate):
        today_trade_day = candidate
    else:
        today_trade_day = XSHG.date_to_session(candidate, direction="previous")

    prev_trade_day = XSHG.previous_session(today_trade_day)
    return today_trade_day.strftime("%Y-%m-%d"), prev_trade_day.strftime("%Y-%m-%d")


def build_proxy_provider():
    """
    优先复用项目现有代理配置。
    没配 PROXY_API_KEY 就退化为直连。
    """
    proxy_api_key = (getattr(settings, "proxy_api_key", "") or "").strip()
    if not proxy_api_key:
        return NoProxyProvider()

    proxy_api_url = (
        "https://sch.shanchendaili.com/api.html"
        "?action=get_ip"
        f"&key={proxy_api_key}"
        "&time=1"
        "&count=1"
        "&type=json"
        "&only=0"
    )
    return ShanchenProxyProvider(
        api_url=proxy_api_url,
        timeout=10,
        scheme="http",
    )


def build_crawler(trade_date: str) -> EastmoneyAShareCrawler:
    checkpoint_file = f"startup_kline_snapshot_checkpoint_{trade_date}.json"
    return EastmoneyAShareCrawler(
        page_size=100,
        timeout=20,
        page_retry=8,
        min_sleep=0.0,
        max_sleep=0.0,
        batch_pages=0,
        batch_sleep_min=0.0,
        batch_sleep_max=0.0,
        checkpoint_file=checkpoint_file,
        proxy_provider=build_proxy_provider(),
    )


def cleanup_checkpoint(trade_date: str) -> None:
    checkpoint_file = Path(f"startup_kline_snapshot_checkpoint_{trade_date}.json")
    if checkpoint_file.exists():
        checkpoint_file.unlink()


def raw_snapshot_row_to_bar(row: dict[str, Any], trade_date: str) -> dict[str, Any] | None:
    """
    EastmoneyAShareCrawler.fetch_all() 返回的 raw_rows 是你当前项目里的中文字段格式。
    这里统一转成 analyze_buy_point 需要的 K 线格式。
    """
    symbol = str(row.get("代码") or "").strip()
    name = str(row.get("名称") or "").strip()

    open_price = row.get("开盘价")
    high_price = row.get("最高价")
    low_price = row.get("最低价")
    close_price = row.get("关盘价")

    if (
        not symbol
        or open_price is None
        or high_price is None
        or low_price is None
        or close_price is None
    ):
        return None

    return {
        "symbol": symbol,
        "name": name,
        "trade_date": trade_date,
        "open_price": float(open_price),
        "high_price": float(high_price),
        "low_price": float(low_price),
        "close_price": float(close_price),
    }


def mongo_row_to_llm_bar(row: dict[str, Any]) -> dict[str, Any] | None:
    trade_date = row.get("trade_date")
    open_price = row.get("open_price")
    high_price = row.get("high_price")
    low_price = row.get("low_price")
    close_price = row.get("close_price")

    if (
        not trade_date
        or open_price is None
        or high_price is None
        or low_price is None
        or close_price is None
    ):
        return None

    return {
        "trade_date": str(trade_date),
        "open_price": float(open_price),
        "high_price": float(high_price),
        "low_price": float(low_price),
        "close_price": float(close_price),
    }


async def crawl_current_snapshot_rows(today_trade_date: str) -> list[dict[str, Any]]:
    crawler = build_crawler(today_trade_date)
    raw_rows, _display_rows = await asyncio.to_thread(
        crawler.fetch_all,
        80,
        True,
        False,
    )
    return raw_rows or []


async def fetch_previous_29_bars(
    repo: DailyKLineSnapshotRepository,
    symbol: str,
    prev_trade_date: str,
) -> list[dict[str, Any]]:
    """
    只读查询：
    - 通过 repo.get_recent_bars() 查 prev_trade_date（含）之前最近 29 根
    - 不写库，不改库
    """
    rows = await repo.get_recent_bars(
        symbol=symbol,
        end_trade_date=prev_trade_date,
        limit=29,
    )
    bars = []
    for row in rows:
        item = mongo_row_to_llm_bar(row)
        if item is not None:
            bars.append(item)
    return bars


def build_compact_success_item(
    *,
    current_bar: dict[str, Any],
    history_bars: list[dict[str, Any]],
    today_trade_date: str,
    prev_trade_date: str,
    result,
) -> dict[str, Any]:
    input_bars_count = len(history_bars) + 1
    kline_trade_date_start = history_bars[0]["trade_date"] if history_bars else current_bar["trade_date"]
    kline_trade_date_end = current_bar["trade_date"]

    llm_analysis = result.llm_analysis.model_dump()

    return {
        "symbol": current_bar["symbol"],
        "name": current_bar["name"],
        "status": "succeeded",
        "bars_count": input_bars_count,
        "history_bars_count": len(history_bars),
        "today_trade_date": today_trade_date,
        "prev_trade_date": prev_trade_date,
        "kline_trade_date_start": kline_trade_date_start,
        "kline_trade_date_end": kline_trade_date_end,
        "current_snapshot_bar": {
            "trade_date": current_bar["trade_date"],
            "open_price": current_bar["open_price"],
            "high_price": current_bar["high_price"],
            "low_price": current_bar["low_price"],
            "close_price": current_bar["close_price"],
        },
        "llm_analysis": llm_analysis,
        "formatted_markdown": result.formatted_markdown,
    }


async def analyze_one_symbol(
    repo: DailyKLineSnapshotRepository,
    current_row: dict[str, Any],
    today_trade_date: str,
    prev_trade_date: str,
) -> dict[str, Any]:
    current_bar = raw_snapshot_row_to_bar(current_row, today_trade_date)
    if current_bar is None:
        return {
            "symbol": str(current_row.get("代码") or "").strip(),
            "name": str(current_row.get("名称") or "").strip(),
            "status": "skipped_invalid_current_snapshot",
            "reason": "current snapshot row missing OHLC fields",
        }

    history_bars = await fetch_previous_29_bars(
        repo=repo,
        symbol=current_bar["symbol"],
        prev_trade_date=prev_trade_date,
    )

    input_bars = history_bars + [
        {
            "trade_date": current_bar["trade_date"],
            "open_price": current_bar["open_price"],
            "high_price": current_bar["high_price"],
            "low_price": current_bar["low_price"],
            "close_price": current_bar["close_price"],
        }
    ]

    if len(input_bars) < 20:
        return {
            "symbol": current_bar["symbol"],
            "name": current_bar["name"],
            "status": "skipped_data_insufficient",
            "reason": f"need >=20 bars, got {len(input_bars)}",
            "bars_count": len(input_bars),
            "history_bars_count": len(history_bars),
            "today_trade_date": today_trade_date,
            "prev_trade_date": prev_trade_date,
            "current_snapshot_bar": {
                "trade_date": current_bar["trade_date"],
                "open_price": current_bar["open_price"],
                "high_price": current_bar["high_price"],
                "low_price": current_bar["low_price"],
                "close_price": current_bar["close_price"],
            },
        }

    result = await asyncio.to_thread(
        analyze_buy_point,
        symbol=current_bar["symbol"],
        bars=input_bars,
        period="日线",
    )

    return build_compact_success_item(
        current_bar=current_bar,
        history_bars=history_bars,
        today_trade_date=today_trade_date,
        prev_trade_date=prev_trade_date,
        result=result,
    )


async def run(
    output_json: str | None = None,
    limit_stocks: int | None = None,
    worker_concurrency: int | None = None,
) -> str:
    repo = DailyKLineSnapshotRepository(db)

    today_trade_date, prev_trade_date = get_a_share_trade_dates()
    raw_rows = await crawl_current_snapshot_rows(today_trade_date)

    if limit_stocks is not None and limit_stocks > 0:
        raw_rows = raw_rows[:limit_stocks]

    output_path = Path(
        output_json
        or f"./output/startup_kline_llm_analysis_compact_{today_trade_date.replace('-', '')}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    concurrency = worker_concurrency or int(
        getattr(settings, "stock_tech_analysis_worker_concurrency", 6) or 6
    )
    concurrency = max(1, min(concurrency, 16))

    result_payload: dict[str, Any] = {
        "generated_at": datetime.now(CN_TZ).isoformat(),
        "today_trade_date": today_trade_date,
        "prev_trade_date": prev_trade_date,
        "total_snapshot_rows": len(raw_rows),
        "worker_concurrency": concurrency,
        "read_only_mongo": True,
        "compact_json": True,
        "items": [],
        "summary": {
            "succeeded": 0,
            "skipped_data_insufficient": 0,
            "skipped_invalid_current_snapshot": 0,
            "failed": 0,
        },
    }

    semaphore = asyncio.Semaphore(concurrency)

    async def _worker(row: dict[str, Any]) -> None:
        async with semaphore:
            try:
                item = await analyze_one_symbol(
                    repo=repo,
                    current_row=row,
                    today_trade_date=today_trade_date,
                    prev_trade_date=prev_trade_date,
                )
            except Exception as e:
                item = {
                    "symbol": str(row.get("代码") or "").strip(),
                    "name": str(row.get("名称") or "").strip(),
                    "status": "failed",
                    "reason": str(e),
                }

            result_payload["items"].append(item)
            status = item.get("status") or "failed"
            result_payload["summary"][status] = result_payload["summary"].get(status, 0) + 1

    await asyncio.gather(*[_worker(row) for row in raw_rows])

    result_payload["items"].sort(
        key=lambda x: (
            str(x.get("status") or ""),
            str(x.get("symbol") or ""),
        )
    )

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result_payload, f, ensure_ascii=False, indent=2)

    cleanup_checkpoint(today_trade_date)
    return str(output_path.resolve())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="启动时抓取当下全市场股票快照 + 从 Mongo 取前 29 根日K + 调项目现有 Price Action 分析器 + 保存精简 JSON（只读 Mongo）"
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="输出 JSON 文件路径，默认 ./output/startup_kline_llm_analysis_compact_YYYYMMDD.json",
    )
    parser.add_argument(
        "--limit-stocks",
        type=int,
        default=None,
        help="只处理前 N 只股票，便于测试",
    )
    parser.add_argument(
        "--worker-concurrency",
        type=int,
        default=None,
        help="并发数，默认复用 settings.stock_tech_analysis_worker_concurrency",
    )
    return parser.parse_args()


async def _amain() -> None:
    args = parse_args()
    try:
        output_path = await run(
            output_json=args.output_json,
            limit_stocks=args.limit_stocks,
            worker_concurrency=args.worker_concurrency,
        )
        print(f"[OK] JSON saved to: {output_path}")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(_amain())