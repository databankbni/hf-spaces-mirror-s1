"""Utility script to remove non-user data for testing.

Deletes rows from: CrawlJob, Chapter, Book, ReadingHistory, UserLibrary.
Keeps user-related tables (User, Account, Session, VerificationToken).

Run from project root with venv activated:

    source ./venv/bin/activate
    python3 backend/scripts/clear_nonuser_data.py

Use with caution — this is destructive.
"""
import asyncio
import sys
import os

# Compute backend and project root
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(script_dir, ".."))
proj_root = os.path.abspath(os.path.join(backend_dir, ".."))

# Add backend to path so we can import db modules
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Import database module
import database as db_mod


async def main():
    try:
        import backend.logging_config as _lc
    except Exception:
        pass
    import logging
    logger = logging.getLogger(__name__)

    logger.info("Connecting to DB...")
    await db_mod.connect()
    client = db_mod.client

    logger.info("Deleting CrawlJob rows...")
    try:
        await client.crawljob.delete_many()
        logger.info("Deleted CrawlJob rows.")
    except Exception as e:
        logger.exception(f"Warning: failed to delete CrawlJob rows: {e}")

    logger.info("Deleting Chapter rows...")
    try:
        await client.chapter.delete_many()
        logger.info("Deleted Chapter rows.")
    except Exception as e:
        logger.exception(f"Warning: failed to delete Chapter rows: {e}")

    logger.info("Deleting Book rows...")
    try:
        await client.book.delete_many()
        logger.info("Deleted Book rows.")
    except Exception as e:
        logger.exception(f"Warning: failed to delete Book rows: {e}")

    logger.info("Deleting ReadingHistory rows...")
    try:
        await client.readinghistory.delete_many()
        logger.info("Deleted ReadingHistory rows.")
    except Exception as e:
        logger.exception(f"Warning: failed to delete ReadingHistory rows: {e}")

    logger.info("Deleting UserLibrary rows...")
    try:
        await client.userlibrary.delete_many()
        logger.info("Deleted UserLibrary rows.")
    except Exception as e:
        logger.exception(f"Warning: failed to delete UserLibrary rows: {e}")

    logger.info("Disconnecting...")
    await db_mod.disconnect()
    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
