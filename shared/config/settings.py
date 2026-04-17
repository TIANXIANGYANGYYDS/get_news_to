from dataclasses import dataclass
import os


@dataclass
class DatabaseSettings:
    mongo_uri: str
    mongo_db_name: str


@dataclass
class LLMSettings:
    provider: str
    base_url: str
    api_key: str
    model_name: str
    timeout_seconds: int
    max_retries: int


@dataclass
class SchedulerSettings:
    worker_count: int
    lease_seconds: int
    heartbeat_seconds: int
    default_timeout_seconds: int
    max_retry_count: int


@dataclass
class NotifierSettings:
    feishu_app_id: str
    feishu_app_secret: str
    feishu_chat_id: str
    feishu_bot_name: str


@dataclass
class CrawlerSettings:
    default_timeout_seconds: int
    max_retries: int
    backoff_seconds: float


@dataclass
class AppSettings:
    env: str
    timezone: str
    run_on_startup: bool
    database: DatabaseSettings
    llm: LLMSettings
    scheduler: SchedulerSettings
    notifier: NotifierSettings
    crawler: CrawlerSettings


def _bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> AppSettings:
    return AppSettings(
        env=os.getenv("APP_ENV", "dev"),
        timezone=os.getenv("APP_TIMEZONE", "Asia/Shanghai"),
        run_on_startup=_bool(os.getenv("APP_RUN_ON_STARTUP", "false")),
        database=DatabaseSettings(
            mongo_uri=os.getenv("DB_MONGO_URI", "mongodb://localhost:27017"),
            mongo_db_name=os.getenv("DB_MONGO_NAME", "daily_pe_reporter"),
        ),
        llm=LLMSettings(
            provider=os.getenv("LLM_PROVIDER", "dashscope"),
            base_url=os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            api_key=os.getenv("LLM_API_KEY", os.getenv("API_KEY", "")),
            model_name=os.getenv("LLM_MODEL_NAME", "qwen-plus"),
            timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
        ),
        scheduler=SchedulerSettings(
            worker_count=int(os.getenv("SCHED_WORKER_COUNT", "3")),
            lease_seconds=int(os.getenv("SCHED_LEASE_SECONDS", "120")),
            heartbeat_seconds=int(os.getenv("SCHED_HEARTBEAT_SECONDS", "15")),
            default_timeout_seconds=int(os.getenv("SCHED_DEFAULT_TIMEOUT_SECONDS", "120")),
            max_retry_count=int(os.getenv("SCHED_MAX_RETRY_COUNT", "3")),
        ),
        notifier=NotifierSettings(
            feishu_app_id=os.getenv("NOTIFIER_FEISHU_APP_ID", os.getenv("FEISHU_APP_ID", "")),
            feishu_app_secret=os.getenv("NOTIFIER_FEISHU_APP_SECRET", os.getenv("FEISHU_APP_SECRET", "")),
            feishu_chat_id=os.getenv("NOTIFIER_FEISHU_CHAT_ID", os.getenv("FEISHU_CHAT_ID", "")),
            feishu_bot_name=os.getenv("NOTIFIER_FEISHU_BOT_NAME", os.getenv("FEISHU_BOT_NAME", "daily_pe_reporter")),
        ),
        crawler=CrawlerSettings(
            default_timeout_seconds=int(os.getenv("CRAWLER_TIMEOUT_SECONDS", "15")),
            max_retries=int(os.getenv("CRAWLER_MAX_RETRIES", "2")),
            backoff_seconds=float(os.getenv("CRAWLER_BACKOFF_SECONDS", "0.5")),
        ),
    )


settings = load_settings()
