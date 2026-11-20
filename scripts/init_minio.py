"""
初始化 MinIO（幂等）

用法（项目根目录）：
    python scripts/init_minio.py

行为：
1. 连接 MinIO（读 .env 中的 MINIO_* 配置）
2. 桶不存在则创建
3. 打印桶状态与访问方式

说明：MinIO 新建桶默认即为 private（不允许匿名访问），
      符合"桶不公开、下载走预签名 URL"的设计。
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from loguru import logger  # noqa: E402
from minio import Minio  # noqa: E402

from app.core.config import settings  # noqa: E402


def main() -> int:
    logger.info(f"连接 MinIO | endpoint={settings.MINIO_ENDPOINT} | bucket={settings.MINIO_BUCKET}")

    client = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )

    try:
        exists = client.bucket_exists(settings.MINIO_BUCKET)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"连接 MinIO 失败：{exc}")
        logger.error("请先启动：docker compose up -d minio minio-init")
        return 1

    if exists:
        logger.info(f"桶已存在，跳过创建 | {settings.MINIO_BUCKET}")
    else:
        client.make_bucket(settings.MINIO_BUCKET)
        logger.success(f"桶已创建 | {settings.MINIO_BUCKET}")

    logger.info(f"S3 API   : http://{settings.MINIO_ENDPOINT}")
    logger.info("控制台    : http://127.0.0.1:9001")
    logger.info(f"桶策略    : private（默认，不允许匿名读）")

    # 自检：写入并删除一个探针对象
    probe = "__healthcheck__/probe.txt"
    try:
        import io

        client.put_object(settings.MINIO_BUCKET, probe, io.BytesIO(b"ok"), length=2)
        client.remove_object(settings.MINIO_BUCKET, probe)
        logger.success("读写自检通过")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"读写自检失败：{exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
