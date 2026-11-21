"""
pytest 全局配置

要点：
1. 在导入应用前设置环境变量，保证测试使用独立的临时数据库与存储目录；
2. 路径按项目结构计算，不依赖启动目录。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ---- 必须在 import app.* 之前设置 ----
_TMP = Path(tempfile.mkdtemp(prefix="talentmatch_test_"))
os.environ["APP_ENV"] = "test"
os.environ["DEBUG"] = "true"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP / 'test.db'}"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["LOCAL_STORAGE_DIR"] = str(_TMP / "uploads")
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["LLM_MOCK"] = "true"
# RAG 默认关闭：测试不应联网调用真实 embedding；需要时由 test_rag 自行打开
os.environ["RAG_ENABLED"] = "false"
os.environ["RAG_INDEX_ENABLED"] = "false"
os.environ["VECTOR_BACKEND"] = "numpy"
os.environ["FAISS_DIR"] = str(_TMP / "faiss")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    """带 lifespan 的测试客户端（会建表并初始化存储）"""
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def email_capture(monkeypatch):
    """
    打开 SMTP 并拦截发信，捕获验证 / 重置链接

    返回 {"verify": [link, ...], "reset": [link, ...]}
    """
    from app.core.config import settings
    from app.services import auth as auth_service

    sent: dict[str, list[str]] = {"verify": [], "reset": []}

    async def fake_verify(to: str, name: str, link: str) -> bool:
        sent["verify"].append(link)
        return True

    async def fake_reset(to: str, name: str, link: str) -> bool:
        sent["reset"].append(link)
        return True

    monkeypatch.setattr(auth_service, "send_verification_email", fake_verify)
    monkeypatch.setattr(auth_service, "send_reset_password_email", fake_reset)
    monkeypatch.setattr(settings, "EMAIL_HOST", "smtp.test")
    return sent
