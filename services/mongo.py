import os
import logging
from motor.motor_asyncio import AsyncIOMotorClient
import pymongo

logger = logging.getLogger(__name__)

class MongoService:
    def __init__(self):
        self.uri = os.getenv("MONGODB_URI")
        self.db_name = os.getenv("MONGODB_DB_NAME", "autoremediator")
        self.client = None
        self.db = None

    def connect(self):
        if not self.uri:
            raise ValueError("MONGODB_URI environment variable is not set.")
        self.client = AsyncIOMotorClient(self.uri)
        self.db = self.client[self.db_name]
        logger.info(f"Connected to MongoDB database: {self.db_name}")

    async def create_indexes(self):
        if self.db is None:
            self.connect()
        try:
            # Unique index on custom string 'id' field in incidents
            await self.db.incidents.create_index("id", unique=True)
            
            # Compound index on service, status, created_at
            await self.db.incidents.create_index([
                ("service", pymongo.ASCENDING),
                ("status", pymongo.ASCENDING),
                ("created_at", pymongo.DESCENDING)
            ])
            logger.info("MongoDB indexes verified/created successfully.")
        except Exception as e:
            logger.error(f"Error creating indexes: {e}")

    @property
    def incidents(self):
        if self.db is None:
            self.connect()
        return self.db.incidents

    @property
    def governance_events(self):
        if self.db is None:
            self.connect()
        return self.db.governance_events

_mongo_instance = None

def get_mongo_service() -> MongoService:
    global _mongo_instance
    if _mongo_instance is None:
        _mongo_instance = MongoService()
    return _mongo_instance
