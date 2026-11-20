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

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    """带 lifespan 的测试客户端（会建表并初始化存储）"""
    from app.main import app

    with TestClient(app) as c:
        yield c
