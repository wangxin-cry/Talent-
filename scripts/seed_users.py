"""
预置演示账号（幂等）

用法（项目根目录）：
    python scripts/seed_users.py            # 缺哪个补哪个
    python scripts/seed_users.py --reset    # 强制把演示账号的密码与角色改回默认值

默认账号（密码统一为 Talent@2026，仅用于本地演示）：
    recruiter / recruiter@talentmatch.local
    manager   / manager@talentmatch.local
    admin     / admin@talentmatch.local
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from loguru import logger  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal, engine, init_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.base import utcnow  # noqa: E402
from app.models.user import (  # noqa: E402
    ROLE_ADMIN,
    ROLE_MANAGER,
    ROLE_RECRUITER,
    STATUS_ACTIVE,
    User,
)

DEMO_PASSWORD = "Talent@2026"
ACCOUNTS = [
    ("recruiter", "recruiter@talentmatch.local", ROLE_RECRUITER),
    ("manager", "manager@talentmatch.local", ROLE_MANAGER),
    ("admin", "admin@talentmatch.local", ROLE_ADMIN),
]


async def main(reset: bool) -> int:
    await init_db()

    async with SessionLocal() as db:
        for name, email, role in ACCOUNTS:
            existing = (
                await db.execute(select(User).where(User.name == name))
            ).scalar_one_or_none()

            if existing is not None and not reset:
                logger.info(f"跳过 {name}（已存在，role={existing.role}，密码未改动）")
                continue

            if existing is not None:
                existing.password = hash_password(DEMO_PASSWORD)
                existing.role = role
                existing.status = STATUS_ACTIVE
                existing.email_verified_at = existing.email_verified_at or utcnow()
                logger.success(f"已重置 {name}：role={role} 密码={DEMO_PASSWORD}")
            else:
                db.add(
                    User(
                        name=name,
                        email=email,
                        password=hash_password(DEMO_PASSWORD),
                        role=role,
                        status=STATUS_ACTIVE,
                        email_verified_at=utcnow(),
                    )
                )
                logger.success(f"已创建 {name}：role={role} 密码={DEMO_PASSWORD}")

        await db.commit()

    await engine.dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="预置演示账号")
    parser.add_argument("--reset", action="store_true", help="重置已存在账号的密码与角色")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.reset)))
