# Schema Migration & Rollback Guide (v3)

## 1) Scope

### Collection Mapping (forward)
- `cls_telegraphs` -> `news_events`
- `daily_market_analysis` -> `market_analysis_reports`
- `daily_kline_snapshots` -> `kline_snapshots`
- `sector_market_heat_rankings` -> `sector_heat_rankings`
- `sector_investment_preference_rankings` -> `sector_preference_rankings`

### Field Mapping (forward)
`news_events`:
- `subjects` -> `subject_names`
- `source` -> `source_type`
- `llm_analysis` -> `analysis`

### Rollback Mapping
Forward mapping is fully reversible via:
- `scripts/migrations/20260417_unify_schema_rollback.py`

## 2) Runbook

### Step A: dry-run migration
```bash
python scripts/migrations/20260417_unify_schema.py --mongo-uri "$DB_MONGO_URI" --db "$DB_MONGO_NAME"
```

### Step B: execute migration
```bash
python scripts/migrations/20260417_unify_schema.py --mongo-uri "$DB_MONGO_URI" --db "$DB_MONGO_NAME" --execute
```

### Step C: verify summary
- check `schema_migration_reports` collection
- check `summary.validation.sample_checks`
- check renamed collections document counts

## 3) Rollback

### Step A: dry-run rollback
```bash
python scripts/migrations/20260417_unify_schema_rollback.py --mongo-uri "$DB_MONGO_URI" --db "$DB_MONGO_NAME"
```

### Step B: execute rollback
```bash
python scripts/migrations/20260417_unify_schema_rollback.py --mongo-uri "$DB_MONGO_URI" --db "$DB_MONGO_NAME" --execute
```

## 4) Idempotency & Safety
- both migration and rollback scripts are idempotent by design:
  - collection rename only runs when target doesn't exist
  - report collection records each operation summary
- migration report is persisted in `schema_migration_reports`
- execute only after dry-run and backup snapshot
