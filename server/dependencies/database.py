from motor.motor_asyncio import AsyncIOMotorClient

from shared.config.settings import settings


class MongoManager:
    def __init__(self):
        self.client: AsyncIOMotorClient | None = None
        self.db = None

    async def connect(self):
        self.client = AsyncIOMotorClient(settings.database.mongo_uri)
        self.db = self.client[settings.database.mongo_db_name]

    async def close(self):
        if self.client:
            self.client.close()
            self.client = None
            self.db = None
