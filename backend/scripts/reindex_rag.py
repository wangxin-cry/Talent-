"""
重建 RAG 向量索引（阶段八）

用法（在 backend 目录执行）：
    python scripts/reindex_rag.py --scope all --rebuild
    python scripts/reindex_rag.py --scope resumes
    python scripts/reindex_rag.py --scope jobs
    python scripts/reindex_rag.py --scope questions
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import SessionLocal, init_db  # noqa: E402
from app.services import rag  # noqa: E402


async def _run(scope: str, rebuild: bool) -> None:
    await init_db()  # 首次运行时补齐 rag_chunk 表
    async with SessionLocal() as db:
        counts = await rag.reindex_all(db, scope=scope, rebuild=rebuild)
    print(
        f"完成：scope={scope} rebuild={rebuild} "
        f"resume_chunks={counts['resume']} job_chunks={counts['job']} "
        f"question_chunks={counts['question']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="重建 RAG 向量索引")
    parser.add_argument(
        "--scope",
        default="all",
        choices=["all", "resumes", "jobs", "questions"],
        help="重建范围",
    )
    parser.add_argument("--rebuild", action="store_true", help="先清空再重建")
    args = parser.parse_args()
    asyncio.run(_run(args.scope, args.rebuild))


if __name__ == "__main__":
    main()
