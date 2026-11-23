"""初始化平台超级管理员

用法（在 backend 目录下）：
    python scripts/create_superadmin.py --email boss@example.com --name boss --password 'Passw0rd!'

行为：
- 邮箱不存在则创建；已存在则升级为 superadmin（company_id 置空、邮箱标记已验证、状态启用）
- 超管不隶属于任何公司，只能访问 /platform 公司管理，不能进入业务数据
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import or_, select

from app.core.database import SessionLocal, init_db
from app.core.security import hash_password
from app.models.user import ROLE_SUPERADMIN, STATUS_ACTIVE, User


async def main(email: str, name: str, password: str | None) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # 库中为无时区时间
    await init_db()
    async with SessionLocal() as db:
        user = (
            await db.execute(
                select(User).where(or_(User.email == email.lower(), User.name == name))
            )
        ).scalars().first()
        if user is None:
            if not password:
                raise SystemExit("新建超管必须提供 --password")
            user = User(
                name=name,
                email=email.lower(),
                password=hash_password(password),
                role=ROLE_SUPERADMIN,
                status=STATUS_ACTIVE,
                company_id=None,
                email_verified_at=now,
            )
            db.add(user)
            print(f"已创建平台超管：{name} <{email}>")
        else:
            user.role = ROLE_SUPERADMIN
            user.company_id = None
            user.status = STATUS_ACTIVE
            user.email_verified_at = user.email_verified_at or now
            if password:
                user.password = hash_password(password)
            print(f"已升级为平台超管：{user.name} <{user.email}>")
        await db.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="创建 / 升级平台超级管理员")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--password", default=None, help="已有账号可省略，保留原密码")
    args = parser.parse_args()
    asyncio.run(main(args.email, args.name, args.password))
