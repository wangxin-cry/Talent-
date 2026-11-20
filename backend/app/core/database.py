"""
数据库连接

SQLAlchemy 2.0 异步引擎：
- 开发：SQLite（aiosqlite），免装数据库
- 生产/联调：PostgreSQL（asyncpg），只改 DATABASE_URL

建表策略：开发期用 create_all（阶段一~阶段四）；表结构稳定后引入 Alembic 迁移。
"""
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import DATA_DIR, settings


class Base(DeclarativeBase):
    """所有模型的基类"""


# SQLite 需要关闭 check_same_thread 语义上的限制（aiosqlite 已处理），
# 这里只针对 PostgreSQL 设置连接池参数
_engine_kwargs: dict = {"echo": settings.DB_ECHO, "pool_pre_ping": True}
if not settings.is_sqlite:
    _engine_kwargs.update(pool_size=10, max_overflow=20, pool_recycle=3600)
else:
    _engine_kwargs.update(connect_args={"timeout": 30})

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：获取数据库会话"""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """
    初始化数据库：导入全部模型后建表

    注意：必须显式 import app.models，否则模型未注册到 Base.metadata，
    create_all 不会建表。
    """
    import app.models  # noqa: F401

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def check_db() -> tuple[bool, str]:
    """健康检查：数据库是否可用"""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


async def close_db() -> None:
    """关闭连接池"""
    await engine.dispose()
