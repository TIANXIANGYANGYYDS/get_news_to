"""
Forward migration for unified v3 schema.

Features:
- collection rename
- field rename
- idempotent execution
- migration report collection write
- validation summary
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pymongo import MongoClient

MIGRATION_ID = "20260417_unify_schema_v3"

COLLECTION_MAPPING = {
    "cls_telegraphs": "news_events",
    "daily_market_analysis": "market_analysis_reports",
    "daily_kline_snapshots": "kline_snapshots",
    "sector_market_heat_rankings": "sector_heat_rankings",
    "sector_investment_preference_rankings": "sector_preference_rankings",
}

FIELD_MAPPING = {
    "news_events": {
        "subjects": "subject_names",
        "source": "source_type",
        "llm_analysis": "analysis",
    }
}


def _get_report_collection(db):
    return db["schema_migration_reports"]


def mark_started(db, execute: bool):
    report_col = _get_report_collection(db)
    report_col.update_one(
        {"migration_id": MIGRATION_ID},
        {
            "$setOnInsert": {
                "migration_id": MIGRATION_ID,
                "started_at": datetime.utcnow(),
                "execute": execute,
                "status": "running",
            }
        },
        upsert=True,
    )


def mark_finished(db, status: str, summary: dict):
    report_col = _get_report_collection(db)
    report_col.update_one(
        {"migration_id": MIGRATION_ID},
        {
            "$set": {
                "finished_at": datetime.utcnow(),
                "status": status,
                "summary": summary,
            }
        },
        upsert=True,
    )


def rename_collections(db, execute: bool) -> list[str]:
    operations: list[str] = []
    for old_name, new_name in COLLECTION_MAPPING.items():
        if old_name in db.list_collection_names() and new_name not in db.list_collection_names():
            operations.append(f"rename collection {old_name} -> {new_name}")
            if execute:
                db[old_name].rename(new_name)
    return operations


def rename_fields(db, execute: bool) -> list[str]:
    operations: list[str] = []
    for collection_name, mapping in FIELD_MAPPING.items():
        if collection_name not in db.list_collection_names():
            continue
        operations.append(f"rename fields in {collection_name}: {mapping}")
        if execute:
            db[collection_name].update_many(
                {},
                {
                    "$rename": mapping,
                    "$set": {"schema_version": "v3", "schema_migrated_at": datetime.utcnow()},
                },
            )
    return operations


def validate(db) -> dict:
    summary = {"collections": {}, "sample_checks": {}}
    for new_name in COLLECTION_MAPPING.values():
        if new_name in db.list_collection_names():
            count = db[new_name].count_documents({})
            summary["collections"][new_name] = count

    if "news_events" in db.list_collection_names():
        sample = db["news_events"].find_one({}, projection={"subject_names": 1, "source_type": 1, "analysis": 1}) or {}
        summary["sample_checks"] = {
            "subject_names_exists": "subject_names" in sample,
            "source_type_exists": "source_type" in sample,
            "analysis_exists": "analysis" in sample,
        }
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mongo-uri", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    client = MongoClient(args.mongo_uri)
    db = client[args.db]

    mark_started(db, execute=args.execute)

    operations = []
    operations.extend(rename_collections(db, execute=args.execute))
    operations.extend(rename_fields(db, execute=args.execute))
    validation = validate(db)

    summary = {"operations": operations, "validation": validation, "execute": args.execute}
    mark_finished(db, status="done", summary=summary)

    print("migration completed")
    print(summary)


if __name__ == "__main__":
    main()
