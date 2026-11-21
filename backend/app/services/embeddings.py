"""
文本向量化客户端（阶段八）

- 生产：SiliconFlow OpenAI 兼容 /embeddings，默认 BAAI/bge-m3（1024 维）
- 测试：EMBEDDING_PROVIDER=mock，用确定性哈希向量，不产生网络与费用
- 向量统一 L2 归一化，FAISS 内积即余弦相似度
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time

import httpx

from app.core.config import settings
from app.models.ai_call import AI_STATUS_FAILED
from app.services import costs


class EmbeddingError(RuntimeError):
    """未配置、请求失败或返回维度不符"""


def is_configured() -> bool:
    if settings.EMBEDDING_PROVIDER == "mock":
        return True
    return bool(
        settings.SILICONFLOW_BASE_URL.strip()
        and settings.SILICONFLOW_API_KEY.strip()
        and settings.MODEL_EMBEDDING.strip()
    )


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 1e-12:
        return vec
    return [v / norm for v in vec]


def _mock_vector(text: str) -> list[float]:
    """确定性词袋向量：相同词越多越相似，供离线测试使用"""
    dim = max(8, settings.EMBEDDING_DIM)
    vec = [0.0] * dim
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9+#.]{2,}", lowered)
    chinese = re.findall(r"[\u4e00-\u9fff]", lowered)
    tokens.extend(chinese)
    tokens.extend("".join(pair) for pair in zip(chinese, chinese[1:]))
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[index] += sign
    return _normalize(vec)


async def _request_batch(texts: list[str]) -> list[list[float]]:
    url = settings.SILICONFLOW_BASE_URL.rstrip("/") + "/embeddings"
    payload = {
        "model": settings.MODEL_EMBEDDING,
        "input": texts,
        "encoding_format": "float",
    }
    headers = {
        "Authorization": f"Bearer {settings.SILICONFLOW_API_KEY}",
        "Content-Type": "application/json",
    }
    attempts = max(1, settings.SILICONFLOW_MAX_RETRIES)
    last_error: Exception | None = None

    for attempt in range(attempts):
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                raise EmbeddingError(f"HTTP {resp.status_code}：{resp.text[:200]}")
            data = resp.json()
            rows = sorted(data["data"], key=lambda item: item.get("index", 0))
            vectors = [row["embedding"] for row in rows]
            if len(vectors) != len(texts):
                raise EmbeddingError("向量数量与输入不一致")

            usage = data.get("usage") or {}
            tokens = int(usage.get("prompt_tokens") or usage.get("total_tokens") or 0)
            await costs.record_ai_call(
                feature="embedding",
                model=settings.MODEL_EMBEDDING,
                provider="siliconflow",
                input_tokens=tokens,
                output_tokens=0,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return vectors
        except (httpx.HTTPError, ValueError, KeyError, TypeError, EmbeddingError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(0.8 * (2**attempt))
                continue

    await costs.record_ai_call(
        feature="embedding",
        model=settings.MODEL_EMBEDDING,
        provider="siliconflow",
        status=AI_STATUS_FAILED,
        error_reason=str(last_error)[:300],
    )
    raise EmbeddingError(str(last_error))


async def embed_texts(
    texts: list[str],
    *,
    feature: str = "embedding",
    user_id: int | None = None,
    job_id: int | None = None,
    candidate_id: int | None = None,
) -> list[list[float]]:
    """批量向量化；失败抛 EmbeddingError，由调用方决定降级"""
    if not texts:
        return []
    if not is_configured():
        raise EmbeddingError("Embedding 未配置（SILICONFLOW_API_KEY 为空）")

    prepared = [text[: settings.EMBEDDING_MAX_CHARS] for text in texts]

    if settings.EMBEDDING_PROVIDER == "mock":
        return [_mock_vector(text) for text in prepared]

    result: list[list[float]] = []
    batch_size = max(1, settings.EMBEDDING_BATCH_SIZE)
    for start in range(0, len(prepared), batch_size):
        batch = prepared[start: start + batch_size]
        vectors = await _request_batch(batch)
        result.extend(vectors)

    dim = settings.EMBEDDING_DIM
    for vec in result:
        if len(vec) != dim:
            raise EmbeddingError(f"向量维度 {len(vec)} 与配置 {dim} 不一致，请重建索引")
    return [_normalize(vec) for vec in result]


async def embed_query(text: str, **kwargs) -> list[float]:
    vectors = await embed_texts([text], **kwargs)
    return vectors[0]
