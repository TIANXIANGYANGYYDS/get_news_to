# Stock News Engineering Platform (Unified v3.1)

## 1. Runtime architecture (single authority)

```text
app/main.py -> server.app_factory.create_app()

server/
  api/routes.py
  app_factory.py
  services/*

domain/
  enums/*
  models/*

infrastructure/
  crawlers/*
  llm/*
  repositories/*

scheduler/
  core/*
  jobs/*
  workers/*

shared/
  base/*
  config/*
```

`app/bootstrap.py` and `app/crawlers/Get_*`, `app/llm/Moring_Reading_llm.py` are **legacy wrappers only** and are removed from runtime import path.

## 2. Main business chains

- News ingestion: crawler -> dedup -> llm analysis -> news repository
- Morning analysis: morning crawler -> morning analyzer -> market analysis repository
- Fupan review: fupan crawler -> market analysis repository
- Kline snapshot: market data crawler -> kline repository
- Aggregation and notification: sector aggregation service + notification service

All above chains are orchestrated through `TaskOrchestrationService` and executed by scheduler workers.

## 3. Scheduler closure

Implemented runtime logic:
- task claim with lease ownership
- heartbeat during execution
- timeout handling + retry backoff
- stale-running recovery
- dead-letter transition
- compensation task creation
- scheduled task materialization + backfill for missed windows

## 4. Model convergence

Primary runtime models are under `domain/models`:
- `news_models.py`
- `analysis_models.py`
- `database_models.py`
- `scheduler_models.py`
- `pipeline_models.py`

Core service orchestration now uses typed payload models for task creation and notification:
- `TaskCreateRequest`
- `NotificationPayload`
- `MorningReadingPayload`
- `FupanReviewPayload`
- `KlineSnapshotBatch`

## 5. Naming convergence

Runtime path naming is unified to snake_case (file), PascalCase (class), and normalized field/collection names.
Legacy names are retained only as compatibility wrappers and are no longer depended on by runtime modules.

## 6. Migration & rollback

See `scripts/migrations/README.md`:
- forward migration script
- rollback script
- runbook and idempotency notes
