"""图片 / 扫描件识别（硅基流动视觉模型，OpenAI 兼容接口）"""
from __future__ import annotations

import asyncio
import base64

import httpx
from loguru import logger

from app.core.config import settings

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# MODEL_OCR 不支持图片输入时，尝试一个通用视觉模型
FALLBACK_MODELS = ("Qwen/Qwen2.5-VL-72B-Instruct",)


class VisionError(RuntimeError):
    """视觉模型不可用或识别失败"""


def _models() -> list[str]:
    result: list[str] = []
    for model in (settings.MODEL_OCR.strip(), *FALLBACK_MODELS):
        if model and model not in result:
            result.append(model)
    return result


async def image_to_text(data: bytes, mime: str = "image/png") -> str:
    if settings.LLM_MOCK:
        raise VisionError("LLM_MOCK=true，跳过视觉识别")
    if not settings.SILICONFLOW_API_KEY.strip():
        raise VisionError("未配置 SILICONFLOW_API_KEY")

    encoded = base64.b64encode(data).decode()
    image_url = f"data:{mime or 'image/png'};base64,{encoded}"
    url = settings.SILICONFLOW_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.SILICONFLOW_API_KEY}",
        "Content-Type": "application/json",
    }

    last_error: Exception | None = None
    for model in _models():
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": settings.ocr_prompt_text},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url, "detail": settings.OCR_DETAIL},
                        },
                    ],
                }
            ],
            "temperature": settings.OCR_TEMPERATURE,
            "max_tokens": settings.OCR_MAX_TOKENS,
        }

        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                    resp = await client.post(url, json=payload, headers=headers)

                if resp.status_code in RETRYABLE_STATUS and attempt == 0:
                    await asyncio.sleep(1.0)
                    continue
                if resp.status_code in {400, 404, 422}:
                    last_error = VisionError(f"{model} 不支持图片输入（HTTP {resp.status_code}）")
                    logger.warning(str(last_error))
                    break
                if resp.status_code >= 400:
                    raise VisionError(f"HTTP {resp.status_code}：{resp.text[:200]}")

                content = resp.json()["choices"][0]["message"]["content"]
                if isinstance(content, list):
                    content = "".join(
                        part.get("text", "") for part in content if isinstance(part, dict)
                    )
                text = (content or "").strip()
                if not text:
                    raise VisionError("视觉模型返回空内容")
                return text

            except VisionError:
                raise
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(1.0)
                    continue
                break

    raise VisionError(str(last_error) if last_error else "视觉模型调用失败")
