from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from zoneinfo import ZoneInfo

from app.crawlers.Get_five_major_index_crawler import FiveMajorIndexCrawler
from app.crawlers.proxy_provider import NoProxyProvider


router = APIRouter(tags=["dashboard"])

CN_TZ = ZoneInfo("Asia/Shanghai")

FIXED_INDEX_NAME_MAP = {
    "000001": "上证指数",
    "399001": "深证成指",
    "399006": "创业板指",
    "000688": "科创50",
    "899050": "北证50",
}

PREFERRED_INDEX_CODES = [
    "000001",
    "399001",
    "399006",
    "000688",
    "899050",
]

KLINE_UNIFIED_FIELDS = [
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "prev_close_price",
    "change_percent",
    "change_amount",
    "turnover_percent",
    "amplitude_percent",
    "turnover_amount_yuan",
    "volume_ratio",
    "pe_ratio",
]

LATEST_SNAPSHOT_FIELDS = KLINE_UNIFIED_FIELDS + [
    "name",
    "float_market_cap_yuan",
    "total_market_cap_yuan",
]


def get_application(request: Request) -> Any:
    return request.app.state.application


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_date(value: str | None) -> str | None:
    text = _safe_str(value)
    if not text:
        return None
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _normalize_datetime_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")

    text = _safe_str(value)
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=CN_TZ)
        return parsed.astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text


def _date_candidates(value: str | None) -> list[str]:
    normalized = _normalize_date(value)
    if not normalized:
        return []
    ymd = normalized.replace("-", "")
    candidates = [normalized]
    if ymd != normalized:
        candidates.append(ymd)
    return candidates


def _resolve_trade_date(application: Any, trade_date: str | None) -> str:
    normalized = _normalize_date(trade_date)
    if normalized:
        return normalized
    return application.resolve_target_trade_date()


def _to_datetime_text_from_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _normalize_sentiment(score: Any) -> str:
    parsed = _safe_float(score, 0.0) or 0.0
    if parsed >= 20:
        return "positive"
    if parsed <= -20:
        return "negative"
    return "neutral"


def _parse_mainline_reasons(analysis_text: str) -> list[dict[str, str]]:
    text = _safe_str(analysis_text)
    if not text:
        return []

    lines = [line.rstrip() for line in text.splitlines()]
    mainline_pattern = re.compile(r"^\s*第[一二三四五六七八九十\d]+主线\s*[：:]\s*(.+?)\s*$")
    reason_pattern = re.compile(r"^\s*理由\s*[：:]\s*(.*)$")

    result: list[dict[str, str]] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        matched_mainline = mainline_pattern.match(line)
        if not matched_mainline:
            idx += 1
            continue

        sector_name = _safe_str(matched_mainline.group(1))
        reason_parts: list[str] = []
        idx += 1

        while idx < len(lines):
            next_line = lines[idx]
            if mainline_pattern.match(next_line):
                break

            matched_reason = reason_pattern.match(next_line)
            if matched_reason:
                first_reason_line = _safe_str(matched_reason.group(1))
                if first_reason_line:
                    reason_parts.append(first_reason_line)
                idx += 1
                while idx < len(lines):
                    follow = lines[idx]
                    if mainline_pattern.match(follow):
                        break
                    if reason_pattern.match(follow):
                        break
                    follow_text = _safe_str(follow)
                    if follow_text:
                        reason_parts.append(follow_text)
                    idx += 1
                continue

            idx += 1

        result.append(
            {
                "sector_name": sector_name,
                "reason": "\n".join(reason_parts).strip(),
            }
        )

    return result


def _pick_score(item: dict[str, Any]) -> float | None:
    for key in ("final_score", "score"):
        if key in item:
            value = _safe_float(item.get(key), None)
            if value is not None:
                return value
    return None


def _normalize_kline_bar(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "trade_date": _normalize_date(raw.get("trade_date") or raw.get("date")),
        "open_price": raw.get("open_price", raw.get("open")),
        "high_price": raw.get("high_price", raw.get("high")),
        "low_price": raw.get("low_price", raw.get("low")),
        "close_price": raw.get("close_price", raw.get("close")),
        "prev_close_price": raw.get("prev_close_price"),
        "change_percent": raw.get("change_percent"),
        "change_amount": raw.get("change_amount"),
        "turnover_percent": raw.get("turnover_percent"),
        "amplitude_percent": raw.get("amplitude_percent"),
        "turnover_amount_yuan": raw.get("turnover_amount_yuan"),
        "volume_ratio": raw.get("volume_ratio"),
        "pe_ratio": raw.get("pe_ratio"),
    }


def _normalize_latest_snapshot(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw:
        return None

    normalized = {
        "trade_date": _normalize_date(raw.get("trade_date") or raw.get("date")),
        "name": raw.get("name"),
        "open_price": raw.get("open_price", raw.get("open")),
        "high_price": raw.get("high_price", raw.get("high")),
        "low_price": raw.get("low_price", raw.get("low")),
        "close_price": raw.get("close_price", raw.get("close")),
        "prev_close_price": raw.get("prev_close_price"),
        "change_percent": raw.get("change_percent"),
        "change_amount": raw.get("change_amount"),
        "turnover_percent": raw.get("turnover_percent"),
        "amplitude_percent": raw.get("amplitude_percent"),
        "turnover_amount_yuan": raw.get("turnover_amount_yuan"),
        "volume_ratio": raw.get("volume_ratio"),
        "pe_ratio": raw.get("pe_ratio"),
        "float_market_cap_yuan": raw.get("float_market_cap_yuan"),
        "total_market_cap_yuan": raw.get("total_market_cap_yuan"),
    }
    return normalized


def _normalize_technical_item_dates(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    normalized["trade_date"] = _normalize_date(item.get("trade_date"))
    normalized["kline_trade_date_start"] = _normalize_date(item.get("kline_trade_date_start"))
    normalized["kline_trade_date_end"] = _normalize_date(item.get("kline_trade_date_end"))
    normalized["analysis_time"] = _normalize_datetime_text(item.get("analysis_time"))
    return normalized


async def _query_by_date_candidates(
    collection: Any,
    date_field: str,
    date_value: str,
    extra_filter: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    query: dict[str, Any] = extra_filter.copy() if extra_filter else {}
    candidates = _date_candidates(date_value)
    if not candidates:
        return None
    if len(candidates) == 1:
        query[date_field] = candidates[0]
    else:
        query[date_field] = {"$in": candidates}

    return await collection.find_one(query, projection={"_id": 0}, sort=[("updated_at", -1)])


async def _find_ranking_doc_with_fallback(collection: Any, biz_date: str) -> dict[str, Any] | None:
    date_candidates = _date_candidates(biz_date)

    today_doc = await collection.find_one(
        {"biz_date": {"$in": date_candidates}},
        projection={"_id": 0},
        sort=[("biz_date", -1), ("updated_at_ts", -1)],
    )
    if today_doc:
        return today_doc

    fallback_doc = await collection.find_one(
        {
            "$or": [
                {"biz_date": {"$lte": biz_date}},
                {"biz_date": {"$lte": biz_date.replace("-", "")}},
            ]
        },
        projection={"_id": 0},
        sort=[("biz_date", -1), ("updated_at_ts", -1)],
    )
    return fallback_doc


async def _fetch_ranking_items(
    repo: Any,
    biz_date: str,
    topn: int,
    history_days: int,
) -> dict[str, Any]:
    collection = repo.target_collection
    doc = await _find_ranking_doc_with_fallback(collection, biz_date)

    if not doc:
        return {"biz_date": biz_date, "window_days": history_days, "items": []}

    actual_biz_date = _normalize_date(doc.get("biz_date")) or biz_date
    today_rankings = doc.get("sector_rankings") or []
    top_items_raw = [item for item in today_rankings if isinstance(item, dict)][:topn]

    history_docs = await collection.find(
        {
            "$or": [
                {"biz_date": {"$lte": actual_biz_date}},
                {"biz_date": {"$lte": actual_biz_date.replace("-", "")}},
            ]
        },
        projection={"_id": 0, "biz_date": 1, "sector_rankings": 1},
        sort=[("biz_date", -1)],
        limit=max(history_days, 1),
    ).to_list(length=max(history_days, 1))
    history_docs.reverse()

    items: list[dict[str, Any]] = []
    for index, item in enumerate(top_items_raw, start=1):
        sector_name = _safe_str(item.get("sector") or item.get("sector_name"))
        if not sector_name:
            continue

        history: list[dict[str, Any]] = []
        for hist_doc in history_docs:
            doc_biz_date = _normalize_date(hist_doc.get("biz_date")) or _safe_str(hist_doc.get("biz_date"))
            rank_items = hist_doc.get("sector_rankings") or []
            matched = next(
                (
                    row
                    for row in rank_items
                    if _safe_str(row.get("sector") or row.get("sector_name")) == sector_name
                ),
                None,
            )
            if not matched:
                continue

            history.append(
                {
                    "biz_date": doc_biz_date,
                    "score": _pick_score(matched),
                }
            )

        items.append(
            {
                "rank": item.get("rank") or index,
                "sector_name": sector_name,
                "score": _pick_score(item),
                "news_count": item.get("news_count"),
                "history": history,
                "raw": item,
            }
        )

    return {
        "biz_date": actual_biz_date,
        "window_days": history_days,
        "items": items,
    }


@router.get("/market/indices")
async def get_market_indices(application: Any = Depends(get_application)):
    crawler = FiveMajorIndexCrawler(
        proxy_provider=NoProxyProvider(),
        timeout=15,
        retry_sleep=1.0,
        max_total_attempts=3,
    )
    rows = await asyncio.to_thread(crawler.fetch)

    normalized_rows: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        code = _safe_str(row.get("index_code")).zfill(6)
        normalized_rows.append(
            {
                "index_code": code,
                "index_name": FIXED_INDEX_NAME_MAP.get(code) or _safe_str(row.get("index_name")),
                "latest": _safe_float(row.get("latest"), None),
                "change": _safe_float(row.get("change"), None),
                "pct_change": _safe_float(row.get("pct_change"), None),
                "trade_date": _normalize_date(row.get("trade_date")),
                "crawl_time": _safe_str(row.get("crawl_time")),
            }
        )

    row_map = {item["index_code"]: item for item in normalized_rows if item.get("index_code")}

    selected: list[dict[str, Any]] = []
    selected_codes: set[str] = set()
    for code in PREFERRED_INDEX_CODES:
        picked = row_map.get(code)
        if not picked:
            continue
        selected.append(
            {
                "index_code": code,
                "index_name": FIXED_INDEX_NAME_MAP.get(code, picked.get("index_name") or ""),
                "latest": picked.get("latest"),
                "change": picked.get("change"),
                "pct_change": picked.get("pct_change"),
                "trade_date": picked.get("trade_date"),
                "crawl_time": picked.get("crawl_time"),
            }
        )
        selected_codes.add(code)

    for item in normalized_rows:
        code = item.get("index_code")
        if not code or code in selected_codes or code == "000300":
            continue
        selected.append(item)
        selected_codes.add(code)
        if len(selected) >= 5:
            break

    selected = selected[:5]

    trade_date = ""
    updated_at = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    for item in selected:
        if not trade_date and item.get("trade_date"):
            trade_date = item["trade_date"]
        if item.get("crawl_time"):
            updated_at = item["crawl_time"]

    return {
        "trade_date": trade_date or datetime.now(CN_TZ).strftime("%Y-%m-%d"),
        "updated_at": updated_at,
        "items": [
            {
                "index_code": item.get("index_code"),
                "index_name": FIXED_INDEX_NAME_MAP.get(item.get("index_code") or "", item.get("index_name") or ""),
                "latest": item.get("latest"),
                "change": item.get("change"),
                "pct_change": item.get("pct_change"),
            }
            for item in selected
        ],
    }


@router.get("/news/recent")
async def get_recent_news(
    days: int = Query(default=3, ge=1, le=30),
    application: Any = Depends(get_application),
):
    end_dt = datetime.now(CN_TZ)
    start_dt = end_dt - timedelta(days=days)
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())

    rows = await application.cls_telegraph_repository.collection.find(
        {
            "publish_ts": {
                "$gte": start_ts,
                "$lte": end_ts,
            }
        },
        projection={"_id": 0},
        sort=[("publish_ts", -1), ("event_id", 1)],
    ).to_list(length=None)

    items: list[dict[str, Any]] = []
    for row in rows:
        llm_analysis = row.get("llm_analysis") or {}
        score = _safe_float(llm_analysis.get("score"), 0.0) or 0.0
        publish_ts = int(row.get("publish_ts") or 0)
        items.append(
            {
                "event_id": _safe_str(row.get("event_id")),
                "publish_ts": publish_ts,
                "publish_time": _safe_str(row.get("publish_time")) or _to_datetime_text_from_ts(publish_ts),
                "source": _safe_str(row.get("source")),
                "title": _safe_str(row.get("title")),
                "content": _safe_str(row.get("content")),
                "subjects": row.get("subjects") or [],
                "score": score,
                "sentiment": _normalize_sentiment(score),
                "reason": _safe_str(llm_analysis.get("reason")),
                "companies": llm_analysis.get("companies"),
                "sectors": llm_analysis.get("sectors") or [],
            }
        )

    return {
        "range": {
            "days": days,
            "start_time": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "total": len(items),
        "items": items,
    }


@router.get("/morning-analysis")
async def get_morning_analysis(
    trade_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    resolved_trade_date = _resolve_trade_date(application, trade_date)
    collection = application.daily_market_analysis_repository.collection

    doc = await _query_by_date_candidates(collection, "trade_date", resolved_trade_date)
    if not doc:
        doc = await _query_by_date_candidates(collection, "analysis_date", resolved_trade_date)
    if not doc:
        doc = await collection.find_one({}, projection={"_id": 0}, sort=[("analysis_date", -1), ("updated_at", -1)])

    if not doc:
        raise HTTPException(status_code=404, detail="morning analysis not found")

    analysis_text = _safe_str(doc.get("analysis_text"))
    parsed_reasons = _parse_mainline_reasons(analysis_text)
    reason_map = {_safe_str(item.get("sector_name")): _safe_str(item.get("reason")) for item in parsed_reasons}

    raw_mainline_sectors = doc.get("mainline_sectors") or []
    normalized_mainline_sectors: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_mainline_sectors, start=1):
        if not isinstance(item, dict):
            sector_name = _safe_str(item)
            normalized_mainline_sectors.append({"rank": idx, "sector_name": sector_name, "reason": ""})
            continue

        sector_name = _safe_str(item.get("sector_name") or item.get("name") or item.get("sector"))
        normalized_mainline_sectors.append(
            {
                "rank": item.get("rank") or idx,
                "sector_name": sector_name,
                "reason": reason_map.get(sector_name, ""),
            }
        )

    return {
        "analysis_date": _normalize_date(doc.get("analysis_date")),
        "trade_date": _normalize_date(doc.get("trade_date")) or resolved_trade_date,
        "prev_trade_date": _normalize_date(doc.get("prev_trade_date")),
        "source": _safe_str(doc.get("source")),
        "mainline_sectors": normalized_mainline_sectors,
        "sector_top_stocks": doc.get("sector_top_stocks") or [],
        "analysis_text": analysis_text,
    }


@router.get("/rankings/investment-preference")
async def get_investment_preference_rankings(
    biz_date: str | None = Query(default=None),
    topn: int = Query(default=10, ge=1, le=20),
    history_days: int = Query(default=10, ge=1, le=30),
    application: Any = Depends(get_application),
):
    resolved_biz_date = _resolve_trade_date(application, biz_date)
    repo = application.sector_investment_preference_ranking_repository
    return await _fetch_ranking_items(repo, resolved_biz_date, topn, history_days)


@router.get("/rankings/market-heat")
async def get_market_heat_rankings(
    biz_date: str | None = Query(default=None),
    topn: int = Query(default=10, ge=1, le=20),
    history_days: int = Query(default=10, ge=1, le=30),
    application: Any = Depends(get_application),
):
    resolved_biz_date = _resolve_trade_date(application, biz_date)
    repo = application.sector_market_heat_ranking_repository
    return await _fetch_ranking_items(repo, resolved_biz_date, topn, history_days)


@router.get("/sector-stock-analysis")
async def get_sector_stock_analysis(
    sector_name: str = Query(..., min_length=1),
    trade_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    resolved_trade_date = _resolve_trade_date(application, trade_date)
    normalized_sector_name = _safe_str(sector_name)
    if not normalized_sector_name:
        raise HTTPException(status_code=422, detail="sector_name is required")

    trade_date_candidates = _date_candidates(resolved_trade_date)
    rows: list[dict[str, Any]] = []
    for candidate in trade_date_candidates:
        rows = await application.daily_stock_technical_analysis_result_repository.list_by_trade_date_sector(
            candidate,
            normalized_sector_name,
        )
        if rows:
            break

    if not rows:
        return {
            "trade_date": resolved_trade_date,
            "sector_name": normalized_sector_name,
            "total": 0,
            "default_stock_code": "",
            "items": [],
        }

    items: list[dict[str, Any]] = []
    for row in rows:
        base_item = _normalize_technical_item_dates(dict(row))

        stock_code = _safe_str(base_item.get("stock_code")).zfill(6)
        end_trade_date = _normalize_date(base_item.get("kline_trade_date_end")) or resolved_trade_date

        snapshot_rows: list[dict[str, Any]] = []
        for end_date_candidate in _date_candidates(end_trade_date):
            snapshot_rows = await application.daily_kline_snapshot_repository.get_recent_bars(
                symbol=stock_code,
                end_trade_date=end_date_candidate,
                limit=30,
            )
            if snapshot_rows:
                break

        normalized_snapshot_rows = [_normalize_kline_bar(item) for item in snapshot_rows if isinstance(item, dict)]
        latest_snapshot = _normalize_latest_snapshot(snapshot_rows[-1] if snapshot_rows else None)

        if len(normalized_snapshot_rows) >= 30:
            kline_30 = normalized_snapshot_rows
        else:
            fallback_bars = base_item.get("input_bars") if isinstance(base_item.get("input_bars"), list) else []
            kline_30 = [_normalize_kline_bar(item) for item in fallback_bars if isinstance(item, dict)]
            if latest_snapshot is None and kline_30:
                latest_snapshot = _normalize_latest_snapshot(kline_30[-1])

        for bar in kline_30:
            for field in KLINE_UNIFIED_FIELDS:
                bar.setdefault(field, None)

        if latest_snapshot is not None:
            for field in LATEST_SNAPSHOT_FIELDS:
                latest_snapshot.setdefault(field, None)

        base_item["stock_code"] = stock_code
        base_item["latest_snapshot"] = latest_snapshot
        base_item["kline_30"] = kline_30
        items.append(base_item)

    default_stock_code = _safe_str(items[0].get("stock_code")) if items else ""

    return {
        "trade_date": _normalize_date(items[0].get("trade_date")) or resolved_trade_date,
        "sector_name": normalized_sector_name,
        "total": len(items),
        "default_stock_code": default_stock_code,
        "items": items,
    }
