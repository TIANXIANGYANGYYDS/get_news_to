from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request

from app.api.dashboard_schemas import DashboardResponse
from app.services.dashboard_query_service import DashboardQueryService


router = APIRouter(prefix="/api/v1", tags=["dashboard"])


def get_application(request: Request) -> Any:
    return request.app.state.application


def _service(application: Any) -> DashboardQueryService:
    return DashboardQueryService(application)


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_sentiment(score: Any) -> str:
    parsed = _safe_float(score, 0.0)
    if parsed >= 20:
        return "positive"
    if parsed <= -20:
        return "negative"
    return "neutral"


def _normalize_priority(rank: int, value: Any) -> str:
    text = _safe_str(value).lower()
    if text in {"high", "medium", "low"}:
        return text
    if rank <= 2:
        return "high"
    if rank <= 4:
        return "medium"
    return "low"


def _split_key_points(text: str, max_items: int = 3) -> list[str]:
    content = _safe_str(text)
    if not content:
        return []

    normalized = (
        content.replace("；", "。")
        .replace(";", "。")
        .replace("！", "。")
        .replace("!", "。")
        .replace("？", "。")
        .replace("?", "。")
        .replace("\n", "。")
    )

    items: list[str] = []
    for part in normalized.split("。"):
        sentence = _safe_str(part)
        if not sentence:
            continue
        items.append(sentence)
        if len(items) >= max_items:
            break
    return items


def _relative_time_text(publish_ts: Any) -> str:
    try:
        target = datetime.fromtimestamp(int(publish_ts), ZoneInfo("Asia/Shanghai"))
    except (TypeError, ValueError, OSError):
        return ""

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    delta = now - target
    seconds = int(delta.total_seconds())

    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{max(seconds // 60, 1)}分钟前"
    if seconds < 86400:
        return f"{max(seconds // 3600, 1)}小时前"
    if seconds < 86400 * 7:
        return f"{max(seconds // 86400, 1)}天前"
    return target.strftime("%m-%d %H:%M")


def _parse_trade_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def _trade_date_range(trade_date: str) -> tuple[int, int]:
    start_dt = _parse_trade_date(trade_date).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    end_dt = (start_dt + timedelta(days=1)) - timedelta(seconds=1)
    return int(start_dt.timestamp()), int(end_dt.timestamp())


def _build_news_item(row: dict[str, Any]) -> dict[str, Any]:
    llm_analysis = row.get("llm_analysis") or {}
    score = _safe_float(llm_analysis.get("score"), 0.0)
    reason = _safe_str(llm_analysis.get("reason"))
    companies = llm_analysis.get("companies") if isinstance(llm_analysis.get("companies"), list) else []
    sectors = llm_analysis.get("sectors") if isinstance(llm_analysis.get("sectors"), list) else []
    content = _safe_str(row.get("content"))
    summary = reason or (content[:120] if len(content) > 120 else content)

    return {
        "id": _safe_str(row.get("event_id")),
        "title": _safe_str(row.get("title")),
        "summary": summary,
        "content": content,
        "source": _safe_str(row.get("source")),
        "time": _relative_time_text(row.get("publish_ts")) or _safe_str(row.get("publish_time")),
        "publishTime": _safe_str(row.get("publish_time")),
        "publishTs": row.get("publish_ts"),
        "author": _safe_str(row.get("source")) or "system",
        "sentiment": _normalize_sentiment(score),
        "relatedStocks": companies,
        "relatedSectors": sectors,
        "impact": score,
        "keyPoints": _split_key_points(reason or content),
        "analysisReason": reason,
        "subjects": row.get("subjects") or [],
    }


def _build_preopen_mainlines(mainline_sectors: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for idx, item in enumerate(mainline_sectors or [], start=1):
        if isinstance(item, dict):
            title = _safe_str(item.get("sector_name") or item.get("title") or item.get("name") or item.get("sector"))
            reason = _safe_str(item.get("reason") or item.get("analysis") or item.get("summary"))
            priority = _normalize_priority(idx, item.get("priority"))
        else:
            title = _safe_str(item)
            reason = ""
            priority = _normalize_priority(idx, None)

        if not title:
            continue

        result.append(
            {
                "rank": idx,
                "title": title,
                "priority": priority,
                "reason": reason,
            }
        )
    return result


def _extract_latest_bar(row: dict[str, Any]) -> dict[str, Any]:
    bars = row.get("input_bars") or []
    if not isinstance(bars, list) or not bars:
        return {}
    latest = bars[-1] if isinstance(bars[-1], dict) else {}
    return latest if isinstance(latest, dict) else {}


def _build_sector_stock_item(row: dict[str, Any], trade_date: str) -> dict[str, Any]:
    latest_bar = _extract_latest_bar(row)
    kline = []
    for bar in row.get("input_bars") or []:
        if not isinstance(bar, dict):
            continue
        kline.append(
            {
                "date": _safe_str(bar.get("trade_date") or bar.get("date")),
                "open": bar.get("open_price", bar.get("open")),
                "high": bar.get("high_price", bar.get("high")),
                "low": bar.get("low_price", bar.get("low")),
                "close": bar.get("close_price", bar.get("close")),
            }
        )

    recommendation = "hold"
    can_trigger_buy = _safe_str(row.get("can_trigger_buy")).lower()
    if can_trigger_buy in {"yes", "true", "1", "买", "buy"}:
        recommendation = "buy"
    elif "sell" in _safe_str(row.get("conclusion")).lower() or "卖" in _safe_str(row.get("conclusion")):
        recommendation = "sell"

    return {
        "code": _safe_str(row.get("stock_code")),
        "name": _safe_str(row.get("stock_name")),
        "tradeDate": trade_date,
        "open": latest_bar.get("open_price", latest_bar.get("open")),
        "high": latest_bar.get("high_price", latest_bar.get("high")),
        "low": latest_bar.get("low_price", latest_bar.get("low")),
        "close": latest_bar.get("close_price", latest_bar.get("close")) or row.get("current_price"),
        "changeAmount": latest_bar.get("price_change"),
        "changePercent": latest_bar.get("pct_change"),
        "amplitudePercent": latest_bar.get("amplitude"),
        "amount": latest_bar.get("turnover_amount"),
        "turnoverPercent": latest_bar.get("turnover_rate"),
        "recommendation": recommendation,
        "analysis": _safe_str(row.get("reason") or row.get("conclusion") or row.get("error_message")),
        "conclusion": _safe_str(row.get("conclusion")),
        "analysisStatus": _safe_str(row.get("analysis_status")),
        "buyPrice": row.get("buy_price"),
        "stopLoss": row.get("stop_loss"),
        "takeProfit": row.get("take_profit"),
        "triggerCondition": _safe_str(row.get("trigger_condition")),
        "expectedEntry": _safe_str(row.get("expected_entry")),
        "kline": kline,
    }


async def _build_sentiment_overview(application: Any, trade_date: str) -> dict[str, Any]:
    repo = application.cls_telegraph_repository
    start_ts, end_ts = _trade_date_range(trade_date)

    async def _count_sentiment(day_start: int, day_end: int) -> dict[str, int]:
        pipeline = [
            {
                "$match": {
                    "publish_ts": {
                        "$gte": day_start,
                        "$lte": day_end,
                    }
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "score": {"$ifNull": ["$llm_analysis.score", 0]},
                }
            },
            {
                "$group": {
                    "_id": None,
                    "positive": {
                        "$sum": {
                            "$cond": [{"$gte": ["$score", 20]}, 1, 0]
                        }
                    },
                    "negative": {
                        "$sum": {
                            "$cond": [{"$lte": ["$score", -20]}, 1, 0]
                        }
                    },
                    "neutral": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {"$gt": ["$score", -20]},
                                        {"$lt": ["$score", 20]},
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                    "total": {"$sum": 1},
                }
            },
        ]
        rows = await repo.collection.aggregate(pipeline).to_list(length=1)
        return rows[0] if rows else {"positive": 0, "negative": 0, "neutral": 0, "total": 0}

    current = await _count_sentiment(start_ts, end_ts)

    previous_date = (_parse_trade_date(trade_date) - timedelta(days=1)).strftime("%Y-%m-%d")
    prev_start_ts, prev_end_ts = _trade_date_range(previous_date)
    previous = await _count_sentiment(prev_start_ts, prev_end_ts)

    def _percent(part: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return round(part * 100.0 / total, 2)

    current_total = _safe_int(current.get("total"), 0)
    previous_total = _safe_int(previous.get("total"), 0)

    positive_percent = _percent(_safe_int(current.get("positive"), 0), current_total)
    neutral_percent = _percent(_safe_int(current.get("neutral"), 0), current_total)
    negative_percent = _percent(_safe_int(current.get("negative"), 0), current_total)

    previous_positive_percent = _percent(_safe_int(previous.get("positive"), 0), previous_total)
    previous_neutral_percent = _percent(_safe_int(previous.get("neutral"), 0), previous_total)
    previous_negative_percent = _percent(_safe_int(previous.get("negative"), 0), previous_total)

    return {
        "tradeDate": trade_date,
        "positivePercent": positive_percent,
        "positiveDelta": round(positive_percent - previous_positive_percent, 2),
        "neutralPercent": neutral_percent,
        "neutralDelta": round(neutral_percent - previous_neutral_percent, 2),
        "negativePercent": negative_percent,
        "negativeDelta": round(negative_percent - previous_negative_percent, 2),
        "counts": {
            "positive": _safe_int(current.get("positive"), 0),
            "neutral": _safe_int(current.get("neutral"), 0),
            "negative": _safe_int(current.get("negative"), 0),
            "total": current_total,
        },
    }


async def _build_trend_series(
    ranking_repo: Any,
    *,
    biz_date: str,
    top_items: list[dict[str, Any]],
    value_key: str,
    days: int = 7,
) -> list[dict[str, Any]]:
    collection = getattr(ranking_repo, "target_collection", None)
    if collection is None:
        return []

    rows = await collection.find(
        {"biz_date": {"$lte": biz_date}},
        projection={"_id": 0, "biz_date": 1, "sector_rankings": 1},
        sort=[("biz_date", -1)],
        limit=max(days, 1),
    ).to_list(length=max(days, 1))

    rows = list(reversed(rows))
    sector_names = [_safe_str(item.get("sector") or item.get("name")) for item in top_items[:5]]

    output: list[dict[str, Any]] = []
    for sector_name in sector_names:
        if not sector_name:
            continue

        data = []
        for row in rows:
            biz = _safe_str(row.get("biz_date"))
            rankings = row.get("sector_rankings") or []
            matched = next(
                (item for item in rankings if _safe_str(item.get("sector")) == sector_name),
                None,
            )
            data.append(
                {
                    "date": biz,
                    "value": _safe_float((matched or {}).get(value_key), 0.0),
                }
            )

        output.append({"name": sector_name, "data": data})
    return output


@router.get("/dashboard/major-indices", response_model=DashboardResponse)
async def get_major_indices(application: Any = Depends(get_application)):
    service = _service(application)
    data = await service.get_major_indices()
    return DashboardResponse(ok=True, data=data, message="")


@router.get("/dashboard/overview", response_model=DashboardResponse)
async def get_overview(
    trade_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    service = _service(application)
    data = await service.get_overview(trade_date=trade_date)
    return DashboardResponse(ok=True, data=data, message="")


@router.get("/dashboard/mainline-sectors", response_model=DashboardResponse)
async def get_mainline_sectors(
    trade_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    service = _service(application)
    data = await service.get_mainline_sectors(trade_date=trade_date)
    return DashboardResponse(ok=True, data=data, message="")


@router.get("/dashboard/sectors/{sector_name}", response_model=DashboardResponse)
async def get_sector_detail(
    sector_name: str,
    trade_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    service = _service(application)
    data = await service.get_sector_detail(sector_name=sector_name, trade_date=trade_date)
    if not data:
        return DashboardResponse(ok=True, data=None, message="sector not found")
    return DashboardResponse(ok=True, data=data, message="")


@router.get("/dashboard/stocks/{stock_code}/technical", response_model=DashboardResponse)
async def get_stock_technical(
    stock_code: str,
    trade_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    service = _service(application)
    data = await service.get_stock_technical(stock_code=stock_code, trade_date=trade_date)
    if not data:
        return DashboardResponse(ok=True, data=None, message="technical result not found")
    return DashboardResponse(ok=True, data=data, message="")


@router.get("/dashboard/news-feed", response_model=DashboardResponse)
async def get_news_feed(
    trade_date: str | None = Query(default=None),
    sector: str | None = Query(default=None),
    source: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    min_score: float | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    application: Any = Depends(get_application),
):
    service = _service(application)
    data = await service.get_news_feed(
        trade_date=trade_date,
        sector=sector,
        source=source,
        keyword=keyword,
        min_score=min_score,
        page=page,
        page_size=page_size,
    )
    return DashboardResponse(ok=True, data=data, message="")


@router.get("/dashboard/rankings", response_model=DashboardResponse)
async def get_rankings(
    biz_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    service = _service(application)
    data = await service.get_rankings(biz_date=biz_date)
    return DashboardResponse(ok=True, data=data, message="")


@router.get("/market/indices")
async def get_frontend_market_indices(application: Any = Depends(get_application)):
    service = _service(application)
    data = await service.get_major_indices()

    return {
        "tradeDate": _safe_str(data.get("trade_date")),
        "updatedAt": _safe_str(data.get("updated_at")),
        "items": [
            {
                "name": _safe_str(item.get("name")),
                "code": _safe_str(item.get("code")),
                "value": item.get("price"),
                "changePercent": item.get("change_percent"),
                "changeValue": item.get("change"),
            }
            for item in (data.get("indices") or [])
        ],
    }


@router.get("/market/preopen-analysis")
async def get_frontend_preopen_analysis(
    trade_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    service = _service(application)
    overview = await service.get_overview(trade_date=trade_date)

    return {
        "date": _safe_str(overview.get("analysis_date") or overview.get("trade_date")),
        "tradeDate": _safe_str(overview.get("trade_date")),
        "analysisText": _safe_str(overview.get("analysis_text")),
        "mainLines": _build_preopen_mainlines(overview.get("mainline_sectors") or []),
        "investmentRankingTop5": overview.get("investment_ranking_top5") or [],
        "marketHeatTop5": overview.get("market_heat_top5") or [],
        "stockAnalysisProgress": overview.get("stock_analysis_progress") or {},
        "systemStatus": overview.get("system_status") or {},
    }


@router.get("/news")
async def get_frontend_news(
    trade_date: str | None = Query(default=None),
    sector: str | None = Query(default=None),
    source: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sentiment: str | None = Query(default=None),
    sort: str | None = Query(default="latest"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    application: Any = Depends(get_application),
):
    service = _service(application)

    normalized_sentiment = _safe_str(sentiment).lower()
    min_score = None
    if normalized_sentiment == "positive":
        min_score = 20.0

    data = await service.get_news_feed(
        trade_date=trade_date,
        sector=sector,
        source=source,
        keyword=search,
        min_score=min_score,
        page=page,
        page_size=page_size,
    )

    items = [_build_news_item(item) for item in (data.get("items") or [])]

    if normalized_sentiment == "negative":
        items = [item for item in items if item.get("sentiment") == "negative"]
    elif normalized_sentiment == "neutral":
        items = [item for item in items if item.get("sentiment") == "neutral"]
    elif normalized_sentiment == "positive":
        items = [item for item in items if item.get("sentiment") == "positive"]

    normalized_sort = _safe_str(sort).lower()
    if normalized_sort in {"impact_desc", "impact"}:
        items.sort(key=lambda x: (_safe_float(x.get("impact"), 0.0), x.get("publishTs") or 0), reverse=True)
    elif normalized_sort == "impact_asc":
        items.sort(key=lambda x: (_safe_float(x.get("impact"), 0.0), x.get("publishTs") or 0))
    else:
        items.sort(key=lambda x: (x.get("publishTs") or 0, _safe_str(x.get("id"))), reverse=True)

    pagination = data.get("pagination") or {}
    pagination["returned"] = len(items)

    return {
        "tradeDate": trade_date or "",
        "items": items,
        "pagination": pagination,
    }


@router.get("/news/sentiment-overview")
async def get_frontend_news_sentiment_overview(
    trade_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    service = _service(application)
    resolved_trade_date = service._resolve_trade_date(trade_date)
    return await _build_sentiment_overview(application, resolved_trade_date)


@router.get("/sector/trend")
async def get_frontend_sector_trend(
    biz_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    service = _service(application)
    rankings = await service.get_rankings(biz_date=biz_date)
    biz_date_value = _safe_str(rankings.get("biz_date"))

    items = []
    for item in (rankings.get("investment_ranking") or [])[:10]:
        score = _safe_float(item.get("final_score"), 0.0)
        items.append(
            {
                "rank": _safe_int(item.get("rank"), len(items) + 1),
                "name": _safe_str(item.get("sector")),
                "score": score,
                "change": _safe_float(item.get("time_score"), 0.0),
                "trend": "up" if score >= 0 else "down",
                "newsCount": _safe_int(item.get("news_count"), 0),
            }
        )

    series = await _build_trend_series(
        application.sector_investment_preference_ranking_repository,
        biz_date=biz_date_value,
        top_items=items,
        value_key="final_score",
        days=7,
    )

    return {
        "bizDate": biz_date_value,
        "items": items,
        "series": series,
    }


@router.get("/news/heatmap")
async def get_frontend_news_heatmap(
    biz_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    service = _service(application)
    rankings = await service.get_rankings(biz_date=biz_date)
    biz_date_value = _safe_str(rankings.get("biz_date"))

    items = []
    for item in (rankings.get("market_heat_ranking") or [])[:10]:
        final_score = _safe_float(item.get("final_score"), 0.0)
        items.append(
            {
                "rank": _safe_int(item.get("rank"), len(items) + 1),
                "name": _safe_str(item.get("sector")),
                "count": _safe_int(item.get("news_count"), 0),
                "growth": _safe_float(item.get("time_score"), 0.0),
                "avgSentiment": "positive" if final_score >= 60 else "neutral",
                "score": final_score,
            }
        )

    series = await _build_trend_series(
        application.sector_market_heat_ranking_repository,
        biz_date=biz_date_value,
        top_items=items,
        value_key="final_score",
        days=7,
    )

    return {
        "bizDate": biz_date_value,
        "items": items,
        "series": series,
    }


@router.get("/sectors/{sector_name}/stocks")
async def get_frontend_sector_stocks(
    sector_name: str,
    trade_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    service = _service(application)
    resolved_trade_date = service._resolve_trade_date(trade_date)
    rows = await application.daily_stock_technical_analysis_result_repository.list_by_trade_date_sector(
        resolved_trade_date,
        sector_name,
    )

    items = [_build_sector_stock_item(row, resolved_trade_date) for row in rows]

    return {
        "sectorName": sector_name,
        "tradeDate": resolved_trade_date,
        "items": items,
    }


@router.get("/stocks/{stock_code}/technical")
async def get_frontend_stock_technical(
    stock_code: str,
    trade_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    service = _service(application)
    data = await service.get_stock_technical(stock_code=stock_code, trade_date=trade_date)
    if not data:
        return {
            "tradeDate": trade_date or "",
            "stockCode": stock_code,
            "stockName": "",
            "sectorName": "",
            "analysis": None,
        }

    analysis = data.get("analysis") or {}
    return {
        "tradeDate": _safe_str(data.get("trade_date")),
        "stockCode": _safe_str(data.get("stock_code")),
        "stockName": _safe_str(data.get("stock_name")),
        "sectorName": _safe_str(data.get("sector_name")),
        "analysis": _build_sector_stock_item(analysis, _safe_str(data.get("trade_date"))),
        "raw": analysis,
    }
