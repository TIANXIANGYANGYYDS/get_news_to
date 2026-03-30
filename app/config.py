import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")


@dataclass
class Settings:
    feishu_app_id: str = os.getenv("FEISHU_APP_ID", "").strip()
    feishu_app_secret: str = os.getenv("FEISHU_APP_SECRET", "").strip()
    feishu_chat_id: str = os.getenv("FEISHU_CHAT_ID", "").strip()
    feishu_bot_name: str = os.getenv("FEISHU_BOT_NAME", "daily_pe_reporter").strip()

    schedule_hour: int = int(os.getenv("SCHEDULE_HOUR", "9"))
    schedule_minute: int = int(os.getenv("SCHEDULE_MINUTE", "0"))
    timezone: str = os.getenv("TIMEZONE", "Asia/Shanghai")
    run_on_startup: bool = os.getenv("RUN_ON_STARTUP", "true").lower() == "true"
    api_key :str =  os.getenv("API_KEY")


settings = Settings()