"""
数据库连接管理模块

提供异步数据库引擎、会话工厂和依赖注入。
统一使用 SQLite。
"""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import event
from sqlalchemy.orm import DeclarativeBase

from .config import settings

# assemble_db_url 保证 DATABASE_URL 一定有值
assert settings.DATABASE_URL, "DATABASE_URL must be set by config validator"

# SQLite 异步引擎
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args={"check_same_thread": False},
)


# 启用 WAL 模式: 写入不阻塞读取, 减少 fsync 开销
# synchronous=NORMAL: WAL 模式下安全, 减少 fsync 频率
# busy_timeout: 写锁冲突时等待 30s 而非立即报错
@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA synchronous = NORMAL")
    cursor.execute("PRAGMA busy_timeout = 30000")
    cursor.close()

# 创建异步会话工厂
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """SQLAlchemy声明式基类"""
    pass


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话的依赖注入函数"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """初始化数据库，创建所有表结构"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """关闭数据库连接"""
    await engine.dispose()
