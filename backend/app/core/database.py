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
        await conn.run_sync(_ensure_compat_columns)


def _ensure_compat_columns(sync_conn) -> None:
    """create_all 不会给已有表补列；这里做最小的兼容迁移"""
    from sqlalchemy import inspect

    inspector = inspect(sync_conn)
    tables = inspector.get_table_names()
    if "user" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("user")}
    for column, ddl in {
        "department": "department VARCHAR(100)",
        "nickname": "nickname VARCHAR(50)",
        "bio": "bio VARCHAR(255)",
        "avatar_key": "avatar_key VARCHAR(500)",
        "company_id": "company_id BIGINT",
    }.items():
        if column not in columns:
            sync_conn.execute(text(f'ALTER TABLE "user" ADD COLUMN {ddl}'))

    # 多租户改造：存量普通用户归入默认公司；平台超管不隶属任何公司
    sync_conn.execute(
        text(
            "UPDATE \"user\" SET company_id = 1 "
            "WHERE company_id IS NULL AND role <> 'superadmin'"
        )
    )
    sync_conn.execute(
        text("UPDATE \"user\" SET company_id = NULL WHERE role = 'superadmin'")
    )
    if sync_conn.dialect.name == "postgresql":
        sync_conn.execute(
            text('ALTER TABLE "user" ALTER COLUMN company_id DROP NOT NULL')
        )
    sync_conn.execute(text('CREATE INDEX IF NOT EXISTS ix_user_department ON "user" (department)'))
    sync_conn.execute(
        text('CREATE INDEX IF NOT EXISTS ix_user_company_role ON "user" (company_id, role)')
    )

    # 简历文件判重改为「公司内唯一」：同一份文件允许被不同公司各自收录
    if "resume_file" in tables and sync_conn.dialect.name == "postgresql":
        sync_conn.execute(
            text('ALTER TABLE resume_file DROP CONSTRAINT IF EXISTS uq_resume_file_sha256')
        )
        sync_conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_resume_file_company_sha "
                "ON resume_file (company_id, sha256)"
            )
        )


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
