import logging
from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.core.config import settings

logger = logging.getLogger(__name__)

Base = declarative_base()

sqlite_url = "sqlite+aiosqlite:///./rri_data.db"

active_engine = create_async_engine(sqlite_url, echo=False, future=True)
active_session_maker = async_sessionmaker(
    active_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

async def init_db():
    global active_engine, active_session_maker
    
    # Try PostgreSQL first if configured
    if settings.DATABASE_URL and ("postgresql" in settings.DATABASE_URL or "postgres" in settings.DATABASE_URL):
        try:
            clean = settings.DATABASE_URL
            if clean.startswith("postgresql://"):
                clean = clean.replace("postgresql://", "postgresql+asyncpg://", 1)
            elif clean.startswith("postgres://"):
                clean = clean.replace("postgres://", "postgresql+asyncpg://", 1)
                
            if "sslmode=require" in clean:
                clean = clean.replace("sslmode=require", "ssl=require")
            if "channel_binding=require&" in clean:
                clean = clean.replace("channel_binding=require&", "")
            elif "&channel_binding=require" in clean:
                clean = clean.replace("&channel_binding=require", "")
                
            test_engine = create_async_engine(
                clean,
                echo=False,
                future=True,
                pool_pre_ping=True,
                pool_recycle=300,
                pool_size=5,
                max_overflow=10,
            )
            async with test_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await conn.execute(text("SELECT 1"))
                
            active_engine = test_engine
            active_session_maker = async_sessionmaker(
                active_engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autocommit=False,
                autoflush=False,
            )
            logger.info("Successfully connected and initialized Neon PostgreSQL database.")
            return
        except Exception as e:
            logger.warning(f"PostgreSQL connection failed ({e}). Falling back to resilient SQLite database.")

    # Resilient SQLite fallback
    active_engine = create_async_engine(sqlite_url, echo=False, future=True)
    active_session_maker = async_sessionmaker(
        active_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with active_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Resilient SQLite database initialized successfully.")

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with active_session_maker() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            raise
        finally:
            await session.close()
