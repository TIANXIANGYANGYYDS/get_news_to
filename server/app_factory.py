from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from domain.models.scheduler_models import RetryPolicy, ScheduledJob
from infrastructure.crawlers.cls_news_crawler import CLSNewsCrawler
from infrastructure.crawlers.fupan_review_crawler import FupanReviewCrawler
from infrastructure.crawlers.jin10_news_crawler import Jin10NewsCrawler
from infrastructure.crawlers.kline_snapshot_crawler import KlineSnapshotCrawler
from infrastructure.crawlers.morning_reading_crawler import MorningReadingCrawler
from infrastructure.crawlers.tenjqka_news_crawler import TenjqkaNewsCrawler
from infrastructure.llm.news_analyzer import NewsLLMAnalyzer
from infrastructure.llm.morning_market_analyzer import MorningMarketAnalyzer
from infrastructure.llm.openai_client import OpenAILLMClient
from infrastructure.notifiers.feishu_notifier import FeishuNotifier
from infrastructure.repositories.kline_snapshot_repository import KlineSnapshotRepository
from infrastructure.repositories.market_analysis_repository import MarketAnalysisRepository
from infrastructure.repositories.news_repository import NewsRepository
from infrastructure.repositories.notification_repository import NotificationRepository
from infrastructure.repositories.scheduler_task_repository import SchedulerTaskRepository
from scheduler.core.dispatcher import TaskDispatcher
from scheduler.core.executor import TaskExecutor
from scheduler.core.scheduler import SchedulerEngine
from scheduler.jobs.job_handlers import JobHandlers
from scheduler.workers.worker import WorkerPool
from server.api.routes import router
from server.dependencies.database import MongoManager
from server.services.fupan_review_service import FupanReviewService
from server.services.kline_snapshot_service import KlineSnapshotService
from server.services.morning_analysis_service import MorningAnalysisService
from server.services.news_analysis_service import NewsAnalysisService
from server.services.news_deduplication_service import NewsDeduplicationService
from server.services.news_ingestion_service import NewsIngestionService
from server.services.notification_service import NotificationService
from server.services.sector_aggregation_service import SectorAggregationService
from server.services.task_orchestration_service import TaskOrchestrationService
from server.services.task_service import TaskService
from shared.config.settings import settings


class Container:
    pass


container = Container()


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo = MongoManager()
    await mongo.connect()

    news_repo = NewsRepository(mongo.db)
    scheduler_repo = SchedulerTaskRepository(mongo.db)
    market_analysis_repo = MarketAnalysisRepository(mongo.db)
    kline_repo = KlineSnapshotRepository(mongo.db)
    notification_repo = NotificationRepository(mongo.db)

    await news_repo.ensure_indexes()
    await scheduler_repo.ensure_indexes()
    await market_analysis_repo.ensure_indexes()
    await kline_repo.ensure_indexes()
    await notification_repo.ensure_indexes()

    llm_client = OpenAILLMClient(
        api_key=settings.llm.api_key,
        base_url=settings.llm.base_url,
        model_name=settings.llm.model_name,
        timeout_seconds=settings.llm.timeout_seconds,
        max_retries=settings.llm.max_retries,
    )
    analyzer = NewsLLMAnalyzer(llm_client)

    crawlers = [
        CLSNewsCrawler(timeout_seconds=settings.crawler.default_timeout_seconds, max_retries=settings.crawler.max_retries, backoff_seconds=settings.crawler.backoff_seconds),
        Jin10NewsCrawler(timeout_seconds=settings.crawler.default_timeout_seconds, max_retries=settings.crawler.max_retries, backoff_seconds=settings.crawler.backoff_seconds),
        TenjqkaNewsCrawler(timeout_seconds=settings.crawler.default_timeout_seconds, max_retries=settings.crawler.max_retries, backoff_seconds=settings.crawler.backoff_seconds),
    ]

    dedup_service = NewsDeduplicationService()
    analysis_service = NewsAnalysisService(analyzer)
    ingestion_service = NewsIngestionService(crawlers, news_repo, dedup_service, analysis_service)
    aggregation_service = SectorAggregationService(news_repo)

    notifier = FeishuNotifier(
        app_id=settings.notifier.feishu_app_id,
        app_secret=settings.notifier.feishu_app_secret,
        chat_id=settings.notifier.feishu_chat_id,
        bot_name=settings.notifier.feishu_bot_name,
    )
    notification_service = NotificationService(notifier, notification_repo)

    morning_analyzer = MorningMarketAnalyzer(llm_client)
    morning_service = MorningAnalysisService(MorningReadingCrawler(timeout_seconds=settings.crawler.default_timeout_seconds, max_retries=settings.crawler.max_retries, backoff_seconds=settings.crawler.backoff_seconds), morning_analyzer, market_analysis_repo)
    fupan_service = FupanReviewService(FupanReviewCrawler(timeout_seconds=settings.crawler.default_timeout_seconds, max_retries=settings.crawler.max_retries, backoff_seconds=settings.crawler.backoff_seconds), market_analysis_repo)
    kline_service = KlineSnapshotService(KlineSnapshotCrawler(timeout_seconds=settings.crawler.default_timeout_seconds, max_retries=settings.crawler.max_retries, backoff_seconds=settings.crawler.backoff_seconds), kline_repo)

    orchestration_service = TaskOrchestrationService(
        ingestion_service,
        aggregation_service,
        notification_service,
        morning_service,
        fupan_service,
        kline_service,
    )

    handlers = JobHandlers(orchestration_service)
    task_handlers = {
        "crawl_news": handlers.crawl_news,
        "aggregate_sector": handlers.aggregate_sector,
        "notify_digest": handlers.notify_digest,
        "morning_analysis": handlers.morning_analysis,
        "fupan_review": handlers.fupan_review,
        "kline_snapshot": handlers.kline_snapshot,
    }

    executor = TaskExecutor(
        scheduler_repo,
        RetryPolicy(max_retries=settings.scheduler.max_retry_count),
        task_handlers,
        lease_seconds=settings.scheduler.lease_seconds,
        heartbeat_interval_seconds=settings.scheduler.heartbeat_seconds,
    )
    dispatcher = TaskDispatcher(scheduler_repo)

    scheduled_jobs = [
        ScheduledJob(task_name="crawl_news", interval_seconds=300, catchup_window_seconds=900),
        ScheduledJob(task_name="aggregate_sector", interval_seconds=600, catchup_window_seconds=1800),
        ScheduledJob(task_name="morning_analysis", interval_seconds=86400, catchup_window_seconds=86400),
        ScheduledJob(task_name="fupan_review", interval_seconds=86400, catchup_window_seconds=86400),
        ScheduledJob(task_name="kline_snapshot", interval_seconds=86400, catchup_window_seconds=86400),
    ]

    scheduler_engine = SchedulerEngine(
        scheduler_repo,
        dispatcher,
        scheduled_jobs=scheduled_jobs,
        default_timeout_seconds=settings.scheduler.default_timeout_seconds,
        default_max_retry_count=settings.scheduler.max_retry_count,
    )

    worker_pool = WorkerPool(
        scheduler_repo,
        executor,
        worker_count=settings.scheduler.worker_count,
        lease_seconds=settings.scheduler.lease_seconds,
        poll_interval_seconds=1,
    )

    task_service = TaskService(
        scheduler_repo,
        max_retry_count=settings.scheduler.max_retry_count,
        default_timeout_seconds=settings.scheduler.default_timeout_seconds,
    )

    container.mongo = mongo
    container.news_repository = news_repo
    container.market_analysis_repository = market_analysis_repo
    container.kline_snapshot_repository = kline_repo
    container.scheduler_task_repository = scheduler_repo
    container.notification_repository = notification_repo
    container.scheduler_engine = scheduler_engine
    container.worker_pool = worker_pool
    container.task_service = task_service

    app.state.container = container

    await scheduler_engine.start()
    await worker_pool.start()

    try:
        yield
    finally:
        await scheduler_engine.stop()
        await worker_pool.stop()
        await mongo.close()


def create_app() -> FastAPI:
    app = FastAPI(title="news-analysis-platform", version="3.0.0", lifespan=lifespan)
    app.include_router(router)
    return app
