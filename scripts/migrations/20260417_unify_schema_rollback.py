"""
Rollback migration for unified v3 schema.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pymongo import MongoClient

MIGRATION_ID = "20260417_unify_schema_v3"

REVERSE_COLLECTION_MAPPING = {
    "news_events": "cls_telegraphs",
    "market_analysis_reports": "daily_market_analysis",
    "kline_snapshots": "daily_kline_snapshots",
    "sector_heat_rankings": "sector_market_heat_rankings",
    "sector_preference_rankings": "sector_investment_preference_rankings",
}

REVERSE_FIELD_MAPPING = {
    "news_events": {
        "subject_names": "subjects",
        "source_type": "source",
        "analysis": "llm_analysis",
    }
}


def rollback_collections(db, execute: bool) -> list[str]:
    operations = []
    for new_name, old_name in REVERSE_COLLECTION_MAPPING.items():
        if new_name in db.list_collection_names() and old_name not in db.list_collection_names():
            operations.append(f"rename collection {new_name} -> {old_name}")
            if execute:
                db[new_name].rename(old_name)
    return operations


def rollback_fields(db, execute: bool) -> list[str]:
    operations = []
    for collection_name, mapping in REVERSE_FIELD_MAPPING.items():
        if collection_name not in db.list_collection_names():
            continue
        operations.append(f"rename fields in {collection_name}: {mapping}")
        if execute:
            db[collection_name].update_many(
                {},
                {"$rename": mapping, "$set": {"schema_rollback_at": datetime.utcnow()}},
            )
    return operations


def mark_rollback(db, summary: dict):
    db["schema_migration_reports"].update_one(
        {"migration_id": MIGRATION_ID},
        {
            "$set": {
                "rollback_at": datetime.utcnow(),
                "rollback_summary": summary,
            }
        },
        upsert=True,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mongo-uri", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    client = MongoClient(args.mongo_uri)
    db = client[args.db]

    operations = []
    operations.extend(rollback_fields(db, execute=args.execute))
    operations.extend(rollback_collections(db, execute=args.execute))

    summary = {"execute": args.execute, "operations": operations}
    mark_rollback(db, summary)

    print("rollback completed")
    print(summary)


if __name__ == "__main__":
    main()
