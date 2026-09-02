import os
from dotenv import load_dotenv
from prisma import Prisma

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("Missing DATABASE_URL in environment")

client = Prisma()

async def connect():
    await client.connect()

async def disconnect():
    await client.disconnect()
