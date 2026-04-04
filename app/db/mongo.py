from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings


MONGO_URI = settings.mongo_uri
MONGO_DB_NAME = settings.mongo_db_name

client = AsyncIOMotorClient(MONGO_URI)
db = client[MONGO_DB_NAME]