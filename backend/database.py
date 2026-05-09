"""Conexão MongoDB compartilhada por server.py e pelos route modules."""
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Carrega .env antes de qualquer import depender de env vars
load_dotenv(Path(__file__).parent / ".env")

mongo_client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = mongo_client[os.environ["DB_NAME"]]
