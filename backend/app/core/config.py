"""
全局配置

所有配置统一从环境变量 / .env 读取（pydantic-settings）。
路径类配置默认基于项目根目录计算，不受启动时工作目录影响。
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> backend/app/core -> backend/app -> backend -> 项目根
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 应用 ----------
    APP_NAME: str = "TalentMatch"
    APP_ENV: str = "dev"          # dev / test / prod
    DEBUG: bool = True
    APP_VERSION: str = "0.1.0"
    API_PREFIX: str = "/api/v1"

    # 安全
    SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # 独立的配置加密密钥（Fernet，用于 PII / API Key）；留空则从 SECRET_KEY 派生
    CONFIG_SECRET: str = ""

    # 跨域
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ---------- 数据库 ----------
    # 开发默认 SQLite（绝对路径，不受启动目录影响）；生产/联调用 PostgreSQL：
    #   postgresql+asyncpg://talentmatch:talentmatch@127.0.0.1:5432/talentmatch
    DATABASE_URL: str = f"sqlite+aiosqlite:///{(DATA_DIR / 'talentmatch.db').as_posix()}"
    DB_ECHO: bool = False

    # ---------- 对象存储（简历文件） ----------
    STORAGE_BACKEND: str = "local"          # minio | local
    LOCAL_STORAGE_DIR: str = str(DATA_DIR / "uploads")
    MINIO_ENDPOINT: str = "127.0.0.1:9000"
    MINIO_ACCESS_KEY: str = "talentmatch"
    MINIO_SECRET_KEY: str = "change-me"
    MINIO_BUCKET: str = "talentmatch-resume"
    MINIO_SECURE: bool = False
    PRESIGN_EXPIRE_SECONDS: int = 600       # 预签名下载 URL 有效期（10 分钟）

    # ---------- 上传限制 ----------
    MAX_UPLOAD_MB: int = 20
    ALLOWED_UPLOAD_EXTS: str = ".pdf,.doc,.docx,.jpg,.jpeg,.png"

    # ---------- LLM ----------
    LLM_PROVIDER: str = "zhipu"
    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_CHAT_MODEL: str = ""
    LLM_EMBEDDING_MODEL: str = ""
    LLM_MOCK: bool = True                   # 无 Key 时走 Mock，保证链路可跑
    LLM_TIMEOUT_SECONDS: int = 60

    # ---------- 成本 ----------
    MONTHLY_BUDGET_CNY: float = 500.0

    # ---------- 助手属性 ----------
    @property
    def cors_origin_list(self) -> list[str]:
        """把逗号分隔的 CORS 配置转成列表"""
        return [x.strip() for x in self.CORS_ORIGINS.split(",") if x.strip()]

    @property
    def allowed_ext_list(self) -> list[str]:
        """允许上传的扩展名列表（小写，带点）"""
        return [x.strip().lower() for x in self.ALLOWED_UPLOAD_EXTS.split(",") if x.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
