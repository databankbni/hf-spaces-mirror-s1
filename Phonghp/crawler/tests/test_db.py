#!/usr/bin/env python3
import asyncio
import os
from dotenv import load_dotenv
from prisma import Prisma

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("Error: DATABASE_URL not found in .env")
    exit(1)

client = Prisma()

async def main():
    try:
        print("Connecting to database...")
        await client.connect()
        print("Connected successfully!")
        
        # Test a simple query
        book_count = await client.book.count()
        chapter_count = await client.chapter.count()
        
        print(f"Books in database: {book_count}")
        print(f"Chapters in database: {chapter_count}")
        
        await client.disconnect()
        print("Disconnected successfully!")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
