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

    mongo_uri: str = os.getenv("MONGO_URI", "").strip()
    mongo_db_name: str = os.getenv("MONGO_DB_NAME", "").strip()

    proxy_api_key : str = os.getenv("PROXY_API_KEY", "").strip()


    def validate(self):
        required_fields = {
            "FEISHU_APP_ID": self.feishu_app_id,
            "FEISHU_APP_SECRET": self.feishu_app_secret,
            "FEISHU_CHAT_ID": self.feishu_chat_id,
            "API_KEY": self.api_key,
            "MONGO_URI": self.mongo_uri,
            "MONGO_DB_NAME": self.mongo_db_name,
        }

        missing = [k for k, v in required_fields.items() if not v]
        if missing:
            raise ValueError(f"Missing required env: {', '.join(missing)}")


settings = Settings()
settings.validate()