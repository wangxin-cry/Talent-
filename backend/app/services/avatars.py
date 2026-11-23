"""用户头像：格式校验、缩放、写入对象存储、旧图清理"""
from __future__ import annotations

import io
import uuid

from fastapi import HTTPException, UploadFile, status
from loguru import logger
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import build_object_key, get_storage
from app.models.user import User
from app.services import audit

MAX_AVATAR_BYTES = 2 * 1024 * 1024
AVATAR_SIZE = 256
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}
MAX_PIXELS = 40_000_000


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def normalize_avatar(raw: bytes) -> tuple[bytes, str, str]:
    """校验图片并统一裁剪成 256×256 JPEG，返回（字节, content_type, 扩展名）"""
    if not raw:
        raise _bad_request("请选择头像图片")
    if len(raw) > MAX_AVATAR_BYTES:
        raise _bad_request("头像不能超过 2MB")

    try:
        with Image.open(io.BytesIO(raw)) as source:
            image_format = (source.format or "").upper()
            if image_format not in ALLOWED_FORMATS:
                raise _bad_request("仅支持 PNG / JPEG / WebP 图片")
            if source.is_animated:
                raise _bad_request("不支持动图，请上传静态图片")
            if source.width * source.height > MAX_PIXELS:
                raise _bad_request("图片尺寸过大，请压缩后重试")

            image = ImageOps.exif_transpose(source)
            image = ImageOps.fit(
                image, (AVATAR_SIZE, AVATAR_SIZE), method=Image.Resampling.LANCZOS
            )
            if image.mode in ("RGBA", "LA"):
                background = Image.new("RGB", image.size, (255, 255, 255))
                alpha = image.convert("RGBA")
                background.paste(alpha, mask=alpha.split()[-1])
                image = background
            else:
                image = image.convert("RGB")

            output = io.BytesIO()
            # 重新绘制会丢弃 EXIF 等元数据
            image.save(output, format="JPEG", quality=88, optimize=True, progressive=True)
            return output.getvalue(), "image/jpeg", ".jpg"
    except UnidentifiedImageError as exc:
        raise _bad_request("无法识别该图片，请上传 PNG / JPEG / WebP") from exc
    except Image.DecompressionBombError as exc:
        raise _bad_request("图片尺寸过大，请压缩后重试") from exc


async def update_avatar(db: AsyncSession, user: User, upload: UploadFile) -> User:
    raw = await upload.read(MAX_AVATAR_BYTES + 1)
    normalized, content_type, ext = normalize_avatar(raw)

    storage = get_storage()
    new_key = build_object_key(user.company_id or 1, "avatar", f"{uuid.uuid4().hex}{ext}")
    storage.put(new_key, normalized, content_type)

    old_key = user.avatar_key
    user.avatar_key = new_key
    await audit.write_audit(
        db,
        action="user.avatar.update",
        target_type="user",
        target_id=user.id,
        user_id=user.id,
        detail={"old_key": old_key, "new_key": new_key},
    )
    try:
        await db.commit()
    except Exception:
        # 数据库失败时清掉刚写入的对象，避免孤儿文件
        try:
            storage.delete(new_key)
        except Exception:  # noqa: BLE001
            logger.warning(f"头像回滚清理失败 | key={new_key}")
        raise
    await db.refresh(user)

    if old_key and old_key != new_key:
        try:
            storage.delete(old_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"旧头像清理失败 | key={old_key} | {exc}")
    return user


async def remove_avatar(db: AsyncSession, user: User) -> User:
    old_key = user.avatar_key
    if old_key:
        user.avatar_key = None
        await audit.write_audit(
            db,
            action="user.avatar.delete",
            target_type="user",
            target_id=user.id,
            user_id=user.id,
            detail={"old_key": old_key},
        )
        await db.commit()
        await db.refresh(user)
        try:
            get_storage().delete(old_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"头像删除失败 | key={old_key} | {exc}")
    return user


def read_avatar(user: User) -> bytes:
    if not user.avatar_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="头像不存在")
    try:
        return get_storage().get(user.avatar_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"头像读取失败 | key={user.avatar_key} | {exc}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="头像不存在") from exc
