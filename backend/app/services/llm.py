from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass

import httpx

from app.core.config import settings

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
class LLMError(RuntimeError):
    """LLM 未配置、请求失败或输出无法解析"""

@dataclass
class ChatResult:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0

def is_configured() -> bool:
    """具备真实调用条件"""
    return bool(
        settings.SILICONFLOW_BASE_URL.strip()
        and settings.SILICONFLOW_API_KEY.strip()
        and settings.MODEL_AGENT.strip()
        and not settings.LLM_MOCK
    )

async def chat_json(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str | None = None,
    temperature: float = 0.4,
    feature: str = "unknown",
    user_id: int | None = None,
    job_id: int | None = None,
    candidate_id: int | None = None,
    agent: str | None = None,
    trace_id: str | None = None,
) -> ChatResult:
    """调用一次 LLM 并返回 JSON 文本；真实调用会写入 ai_call 台账"""
    if not is_configured():
        raise LLMError("LLM 未配置（SILICONFLOW_API_KEY 为空或 LLM_MOCK=true）")

    model_name = model or settings.MODEL_AGENT
    url = settings.SILICONFLOW_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {settings.SILICONFLOW_API_KEY}",
        "Content-Type": "application/json",
    }

    attempts = max(1, settings.SILICONFLOW_MAX_RETRIES)
    last_error: Exception | None = None
    started = time.perf_counter()

    try:
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                    resp = await client.post(url, json=payload, headers=headers)

                if resp.status_code in RETRYABLE_STATUS and attempt + 1 < attempts:
                    last_error = LLMError(f"HTTP {resp.status_code}")
                    await asyncio.sleep(0.8 * (2**attempt))
                    continue

                if resp.status_code >= 400:
                    raise LLMError(f"HTTP {resp.status_code}：{resp.text[:300]}")

                try:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    raise LLMError("模型响应格式异常") from exc

                usage = data.get("usage") or {}
                result = ChatResult(
                    text=content,
                    model=data.get("model") or model_name,
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                )
                await _record(
                    feature=feature,
                    model=result.model,
                    input_tokens=result.prompt_tokens,
                    output_tokens=result.completion_tokens,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    status="success",
                    user_id=user_id,
                    job_id=job_id,
                    candidate_id=candidate_id,
                    agent=agent,
                    trace_id=trace_id,
                )
                return result

            except httpx.HTTPError as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    raise LLMError(f"请求失败：{exc}") from exc
                await asyncio.sleep(0.8 * (2**attempt))

        raise LLMError(f"请求失败：{last_error}")
    except LLMError as exc:
        await _record(
            feature=feature,
            model=model_name,
            input_tokens=0,
            output_tokens=0,
            duration_ms=int((time.perf_counter() - started) * 1000),
            status="failed",
            error_reason=str(exc),
            user_id=user_id,
            job_id=job_id,
            candidate_id=candidate_id,
            agent=agent,
            trace_id=trace_id,
        )
        raise


async def _record(**kwargs) -> None:
    """记账（SessionLocal 独立会话，内部已兜底异常）"""
    from app.services import costs

    await costs.record_ai_call(**kwargs)

def loads_json(text: str) -> dict:
    """容错解析：去掉 ```json 围栏，截取首尾大括号"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMError("模型输出不是 JSON 对象")

    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"JSON 解析失败：{exc}") from exc
