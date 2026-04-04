from typing import Any

from fastapi import APIRouter, Query
from pymongo import DESCENDING

from app.db.mongo import db

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/latest")
async def get_latest_news(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    """
    获取最新资讯列表
    """
    cursor = (
        db["cls_telegraphs"]
        .find(
            {},
            {
                "_id": 0,
                "event_id": 1,
                "content": 1,
                "publish_ts": 1,
                "subjects": 1,
                "llm_analysis.score": 1,
                "llm_analysis.reason": 1,
                "llm_analysis.sectors": 1,
                "llm_analysis.companies": 1,
            },
        )
        .sort("publish_ts", DESCENDING)
        .limit(limit)
    )

    items = await cursor.to_list(length=limit)

    return {
        "code": 0,
        "message": "success",
        "data": items,
    }