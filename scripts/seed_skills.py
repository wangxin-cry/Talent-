"""
技能词表种子数据（幂等）

用法（项目根目录）：
    python scripts/seed_skills.py
    python scripts/seed_skills.py --reset   # 已存在的技能也更新别名/分类

覆盖常见语言、框架、数据库、中间件、工具与软技能，别名用于归一（K8s → Kubernetes）。
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
from app.models.skill import Skill  # noqa: E402

# (name, display_name, aliases, category)
SKILLS: list[tuple[str, str | None, list[str], str]] = [
    # 编程语言
    ("Python", "Python", ["py"], "language"),
    ("Java", "Java", [], "language"),
    ("Go", "Go", ["Golang"], "language"),
    ("JavaScript", "JavaScript", ["JS"], "language"),
    ("TypeScript", "TypeScript", ["TS"], "language"),
    ("SQL", "SQL", [], "language"),
    ("C++", "C++", ["CPP"], "language"),
    ("Rust", "Rust", [], "language"),
    # 框架
    ("FastAPI", "FastAPI", [], "framework"),
    ("Django", "Django", [], "framework"),
    ("Flask", "Flask", [], "framework"),
    ("Spring Boot", "Spring Boot", ["SpringBoot", "Spring"], "framework"),
    ("Vue", "Vue", ["Vue.js", "Vue3"], "framework"),
    ("React", "React", ["React.js"], "framework"),
    ("Node.js", "Node.js", ["Node", "NodeJS"], "framework"),
    ("LangChain", "LangChain", [], "framework"),
    ("LangGraph", "LangGraph", [], "framework"),
    # 数据库
    ("PostgreSQL", "PostgreSQL", ["Postgres", "PG"], "database"),
    ("MySQL", "MySQL", [], "database"),
    ("Redis", "Redis", [], "database"),
    ("MongoDB", "MongoDB", ["Mongo"], "database"),
    ("Elasticsearch", "Elasticsearch", ["ES"], "database"),
    ("SQLite", "SQLite", [], "database"),
    # 中间件 / 基础设施
    ("Kafka", "Kafka", ["Apache Kafka"], "middleware"),
    ("RabbitMQ", "RabbitMQ", ["Rabbit"], "middleware"),
    ("Nginx", "Nginx", [], "middleware"),
    ("Docker", "Docker", ["容器"], "middleware"),
    ("Kubernetes", "Kubernetes", ["K8s", "k8s", "kube"], "middleware"),
    ("CI/CD", "持续集成", ["CICD", "持续集成"], "middleware"),
    # 工具
    ("Git", "Git", [], "tool"),
    ("Linux", "Linux", [], "tool"),
    ("Prometheus", "Prometheus", ["Prom"], "tool"),
    ("Grafana", "Grafana", [], "tool"),
    ("Jenkins", "Jenkins", [], "tool"),
    ("Vite", "Vite", [], "tool"),
    ("Element Plus", "Element Plus", ["ElementPlus"], "tool"),
    # AI
    ("PyTorch", "PyTorch", ["Torch"], "framework"),
    ("TensorFlow", "TensorFlow", ["TF"], "framework"),
    ("RAG", "检索增强生成", ["检索增强"], "framework"),
    ("LLM", "大语言模型", ["大模型"], "framework"),
    # 软技能
    ("沟通协作", "沟通协作", ["沟通能力", "团队协作"], "soft"),
    ("需求分析", "需求分析", ["业务分析"], "soft"),
    ("项目管理", "项目管理", ["项目推进"], "soft"),
    ("问题解决", "问题解决", ["问题排查"], "soft"),
]


async def main(reset: bool) -> int:
    await init_db()

    created = 0
    updated = 0
    async with SessionLocal() as db:
        for name, display_name, aliases, category in SKILLS:
            existing = (
                await db.execute(select(Skill).where(Skill.name == name))
            ).scalar_one_or_none()

            if existing is None:
                db.add(
                    Skill(
                        name=name,
                        display_name=display_name,
                        aliases=aliases,
                        category=category,
                    )
                )
                created += 1
                continue

            if reset:
                existing.display_name = display_name
                existing.aliases = aliases
                existing.category = category
                existing.is_active = True
                updated += 1

        await db.commit()

    logger.success(f"技能词表就绪：新增 {created}，更新 {updated}（共 {len(SKILLS)} 条）")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="初始化技能词表")
    parser.add_argument("--reset", action="store_true", help="更新已存在技能的别名与分类")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.reset)))
