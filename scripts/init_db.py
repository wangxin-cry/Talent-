"""
初始化数据库（建表）

用法（项目根目录）：
    python scripts/init_db.py

行为：
1. 按 .env 的 DATABASE_URL 连接（默认 SQLite）
2. 导入全部模型并 create_all
3. 打印实际建成的表清单

说明：开发期用 create_all；表结构稳定后改为 Alembic 迁移。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from loguru import logger  # noqa: E402
from sqlalchemy import inspect  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import engine, init_db  # noqa: E402


async def main() -> int:
    logger.info(f"数据库: {'SQLite' if settings.is_sqlite else 'PostgreSQL'}")
    logger.info(f"DATABASE_URL = {settings.DATABASE_URL}")

    await init_db()
    logger.success("建表完成")

    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())

    logger.info(f"共 {len(tables)} 张表：")
    for name in tables:
        logger.info(f"  - {name}")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
