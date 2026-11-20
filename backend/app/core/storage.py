"""
对象存储抽象（MinIO 默认实现 + 本地磁盘降级实现）

设计要点：
1. 简历等文件一律存对象存储，数据库只存 bucket + object_key；
2. 统一接口 StorageProvider，切换后端只改 STORAGE_BACKEND；
3. 对象键不含 PII：{company_id}/{category}/{yyyy}/{mm}/{uuid}.{ext}；
4. 下载用预签名 URL（默认 10 分钟），桶不公开。
"""
from __future__ import annotations

import io
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from loguru import logger

from app.core.config import settings


class StorageProvider(Protocol):
    """对象存储统一接口"""

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> dict: ...
    def get(self, key: str) -> bytes: ...
    def presign_get(self, key: str, expires: int | None = None) -> str: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def health_check(self) -> tuple[bool, str]: ...


def build_object_key(company_id: int | str, category: str, filename: str) -> str:
    """
    生成对象键（不含任何个人信息）

    Args:
        company_id: 公司 id
        category: 业务分类，如 resume / attachment
        filename: 原始文件名（只用于取扩展名）

    Returns:
        如 1/resume/2026/11/6f2c1a9e4b7d4c2a9e8f3d5b1a0c7e21.pdf
    """
    ext = Path(filename).suffix.lower()
    now = datetime.now()
    return f"{company_id}/{category}/{now:%Y/%m}/{uuid.uuid4().hex}{ext}"


class LocalStorage:
    """本地磁盘实现：MinIO 不可用时的降级方案，也用于单元测试"""

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or settings.LOCAL_STORAGE_DIR)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # 防止 ../ 越权读写
        target = (self.root / key).resolve()
        if not str(target).startswith(str(self.root.resolve())):
            raise ValueError(f"非法对象键: {key}")
        return target

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        logger.debug(f"本地存储写入 | key={key} | size={len(data)}")
        return {"etag": uuid.uuid4().hex, "size": len(data)}

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def presign_get(self, key: str, expires: int | None = None) -> str:
        # 本地模式没有签名概念，返回后端下载接口地址
        return f"{settings.API_PREFIX}/files/local/{key}"

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def health_check(self) -> tuple[bool, str]:
        try:
            probe = self.root / ".healthcheck"
            probe.write_bytes(b"ok")
            probe.unlink()
            return True, "ok"
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"


class MinIOStorage:
    """MinIO（S3 兼容）实现"""

    def __init__(self) -> None:
        from minio import Minio  # 延迟导入：未用 MinIO 时不强依赖

        self.bucket = settings.MINIO_BUCKET
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
            logger.info(f"MinIO 桶已创建 | bucket={self.bucket}")

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
        result = self.client.put_object(
            self.bucket, key, io.BytesIO(data), length=len(data), content_type=content_type
        )
        logger.debug(f"MinIO 写入 | bucket={self.bucket} | key={key} | size={len(data)}")
        return {"etag": result.etag, "size": len(data)}

    def get(self, key: str) -> bytes:
        resp = self.client.get_object(self.bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def presign_get(self, key: str, expires: int | None = None) -> str:
        seconds = expires or settings.PRESIGN_EXPIRE_SECONDS
        return self.client.presigned_get_object(
            self.bucket, key, expires=timedelta(seconds=seconds)
        )

    def delete(self, key: str) -> None:
        self.client.remove_object(self.bucket, key)

    def exists(self, key: str) -> bool:
        try:
            self.client.stat_object(self.bucket, key)
            return True
        except Exception:  # noqa: BLE001
            return False

    def health_check(self) -> tuple[bool, str]:
        try:
            if not self.client.bucket_exists(self.bucket):
                return False, f"桶不存在: {self.bucket}"
            return True, "ok"
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"


_storage_instance: StorageProvider | None = None


def get_storage() -> StorageProvider:
    """
    获取存储实例（单例）

    STORAGE_BACKEND=minio 但连不上时降级为本地磁盘，保证开发不被环境卡住。
    """
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance

    if settings.STORAGE_BACKEND.lower() == "minio":
        try:
            _storage_instance = MinIOStorage()
            logger.info(f"对象存储: MinIO | bucket={settings.MINIO_BUCKET}")
            return _storage_instance
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"MinIO 初始化失败，降级为本地磁盘: {exc}")

    _storage_instance = LocalStorage()
    logger.info(f"对象存储: 本地磁盘 | dir={settings.LOCAL_STORAGE_DIR}")
    return _storage_instance


def reset_storage() -> None:
    """重置单例（测试用）"""
    global _storage_instance
    _storage_instance = None


def copy_local_to_minio() -> int:
    """
    把本地降级存储里的文件迁移到 MinIO（切换环境时用）

    Returns:
        迁移文件数
    """
    from minio import Minio

    local = LocalStorage()
    client = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )
    if not client.bucket_exists(settings.MINIO_BUCKET):
        client.make_bucket(settings.MINIO_BUCKET)

    count = 0
    for path in local.root.rglob("*"):
        if not path.is_file():
            continue
        key = path.relative_to(local.root).as_posix()
        client.put_object(settings.MINIO_BUCKET, key, io.BytesIO(path.read_bytes()),
                          length=path.stat().st_size)
        count += 1
    logger.info(f"本地 -> MinIO 迁移完成 | {count} 个文件")
    return count


def disk_usage(root: str | None = None) -> dict:
    """统计本地存储占用（仅 local 模式有意义）"""
    p = Path(root or settings.LOCAL_STORAGE_DIR)
    if not p.exists():
        return {"files": 0, "bytes": 0}
    files = [f for f in p.rglob("*") if f.is_file()]
    return {"files": len(files), "bytes": sum(f.stat().st_size for f in files)}
