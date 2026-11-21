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

    # ---------- 邮件（注册验证 / 找回密码） ----------
    # EMAIL_HOST 为空即开发模式：注册用户直接标记已验证，找回密码链接只写日志
    EMAIL_HOST: str = ""
    EMAIL_PORT: int = 465
    EMAIL_USERNAME: str = ""
    EMAIL_PASSWORD: str = ""
    EMAIL_USE_TLS: bool = False
    EMAIL_USE_SSL: bool = True
    EMAIL_FROM_ADDRESS: str = ""
    EMAIL_FROM_NAME: str = "TalentMatch"
    EMAIL_VERIFY_EXPIRE_HOURS: int = 24
    RESET_TOKEN_EXPIRE_MINUTES: int = 30

    # 前端地址（拼验证 / 重置链接）
    FRONTEND_BASE_URL: str = "http://localhost:5173"

    # ---------- 上传限制 ----------
    MAX_UPLOAD_MB: int = 20
    ALLOWED_UPLOAD_EXTS: str = ".pdf,.doc,.docx,.jpg,.jpeg,.png"

    # ---------- 大模型（硅基流动，OpenAI 兼容） ----------
    SILICONFLOW_BASE_URL: str = "https://api.siliconflow.cn/v1"
    SILICONFLOW_API_KEY: str = ""
    SILICONFLOW_MAX_RETRIES: int = 3

    # 模型
    MODEL_AGENT: str = "deepseek-ai/DeepSeek-V4-Flash"
    MODEL_OCR: str = "deepseek-ai/DeepSeek-OCR"
    MODEL_NORMALIZE: str = "deepseek-ai/DeepSeek-V4-Flash"

    # 文档转 Markdown（阶段四 OCR 用）
    OCR_PROMPT: str = "<image>\n<|grounding|>Convert the document to markdown."
    OCR_DETAIL: str = "high"  # low | high
    OCR_MAX_TOKENS: int = 4096
    OCR_TEMPERATURE: float = 0.0

    # ---------- 简历解析（阶段四） ----------
    RESUME_MAX_CHARS: int = 12000      # 送进模型的简历文本上限，控制单次成本
    RESUME_MAX_FILES: int = 10         # 单次最多上传文件数
    LOW_CONFIDENCE_THRESHOLD: float = 0.7  # 低于此值前端标黄

    # 通用开关与超时
    LLM_MOCK: bool = False  # true 强制走模板（测试用）；正常调用保持 false
    LLM_TIMEOUT_SECONDS: int = 60

    # ---------- RAG 知识增强（阶段八） ----------
    RAG_ENABLED: bool = True                # 检索总开关
    RAG_INDEX_ENABLED: bool = True          # 写入开关（关掉可只读省钱）
    VECTOR_BACKEND: str = "faiss"           # faiss | numpy | auto
    FAISS_DIR: str = str(DATA_DIR / "faiss")
    EMBEDDING_PROVIDER: str = "siliconflow"  # siliconflow | mock（测试）
    MODEL_EMBEDDING: str = "BAAI/bge-m3"
    EMBEDDING_DIM: int = 1024
    EMBEDDING_BATCH_SIZE: int = 32
    EMBEDDING_MAX_CHARS: int = 2000
    RAG_TOP_K: int = 5
    RAG_MIN_SCORE: float = 0.25
    RAG_SIMILAR_RESUMES: int = 3
    RAG_SIMILAR_QUESTIONS: int = 4

    # 兼容旧字段：阶段三旧模板代码仍引用；接完新 jd_writer 后可删
    LLM_API_KEY: str = ""

    # ---------- 成本 ----------
    MONTHLY_BUDGET_CNY: float = 500.0
    # 未在 app/core/pricing.py 收录的模型，按此默认单价计费（元 / 1K token）
    LLM_PRICE_INPUT_PER_1K: float = 0.002
    LLM_PRICE_OUTPUT_PER_1K: float = 0.008

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

    @property
    def email_enabled(self) -> bool:
        """是否配置了 SMTP（为空即开发模式）"""
        return bool(self.EMAIL_HOST.strip())

    @property
    def email_from(self) -> str:
        """发件地址：未单独配置时回落到登录账号"""
        return self.EMAIL_FROM_ADDRESS.strip() or self.EMAIL_USERNAME.strip()

    @property
    def ocr_prompt_text(self) -> str:
        """把 .env 里的字面量 \\n 转成真实换行"""
        return self.OCR_PROMPT.replace("\\n", "\n")

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
