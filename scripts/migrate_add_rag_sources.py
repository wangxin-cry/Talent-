"""
轻量迁移：给 interview_question 增加 rag_sources 列（阶段八）

背景：项目未引入 Alembic，create_all 不会给已存在的表加列。
本脚本幂等执行：列已存在则跳过。

用法（项目根目录）：
    python scripts/migrate_add_rag_sources.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from loguru import logger  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import engine  # noqa: E402


async def main() -> int:
    async with engine.begin() as conn:
        has_table = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table("interview_question")
        )
        if not has_table:
            logger.info("interview_question 表不存在，无需迁移（首次启动会自动建表）")
            await engine.dispose()
            return 0

        columns = await conn.run_sync(
            lambda sync_conn: [c["name"] for c in inspect(sync_conn).get_columns("interview_question")]
        )
        if "rag_sources" in columns:
            logger.info("列已存在，跳过：interview_question.rag_sources")
            await engine.dispose()
            return 0

        if settings.is_sqlite:
            await conn.execute(
                text("ALTER TABLE interview_question ADD COLUMN rag_sources JSON DEFAULT '[]'")
            )
        else:
            await conn.execute(
                text(
                    "ALTER TABLE interview_question "
                    "ADD COLUMN rag_sources JSONB NOT NULL DEFAULT '[]'::jsonb"
                )
            )
        logger.success("已新增列：interview_question.rag_sources")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
