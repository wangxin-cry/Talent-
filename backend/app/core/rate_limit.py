"""
接口限流（PRD §8.3：每用户 100 次/分钟）

实现为进程内滑动窗口，按「用户身份 > API Key > 客户端 IP」计数：
- 已登录：JWT 的 sub（不查库，解析失败再退回 IP）
- API Key：Key 前缀哈希
- 匿名：客户端 IP（X-Forwarded-For 优先）

单实例够用；多实例部署需换成 Redis 计数器。超限返回 429。
"""
from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.security import decode_token

# 健康检查 / 文档不计数
EXEMPT_PATHS = {"/", "/docs", "/redoc", "/openapi.json"}
EXEMPT_PREFIXES = ("/api/v1/healthz", "/api/v1/auth/avatar/")


class SlidingWindowLimiter:
    """固定窗口 + 队列：每个 key 在 window 秒内最多 limit 次"""

    def __init__(self, limit: int, window_seconds: int = 60):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, now: float | None = None) -> tuple[bool, int, float]:
        """返回 (是否放行, 剩余次数, 需等待秒数)"""
        moment = time.monotonic() if now is None else now
        bucket = self._hits[key]
        while bucket and moment - bucket[0] >= self.window:
            bucket.popleft()
        if len(bucket) >= self.limit:
            wait = max(0.0, self.window - (moment - bucket[0]))
            return False, 0, wait
        bucket.append(moment)
        return True, self.limit - len(bucket), 0.0

    def reset(self) -> None:
        self._hits.clear()


def _identity(request: Request) -> str:
    """优先按用户，其次 API Key，最后按 IP"""
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        payload = decode_token(authorization.split(" ", 1)[1].strip())
        if payload and payload.get("sub"):
            return f"user:{payload['sub']}"

    api_key = request.headers.get("x-api-key", "").strip()
    if api_key:
        return "key:" + hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]

    forwarded = request.headers.get("x-forwarded-for", "")
    host = forwarded.split(",")[0].strip() if forwarded else ""
    if not host and request.client is not None:
        host = request.client.host or "unknown"
    return f"ip:{host or 'unknown'}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """全局限流中间件；测试环境默认关闭，避免用例互相影响"""

    def __init__(self, app):
        super().__init__(app)
        self.limiter = SlidingWindowLimiter(settings.RATE_LIMIT_PER_MINUTE, 60)

    async def dispatch(self, request: Request, call_next):
        if (
            not settings.RATE_LIMIT_ENABLED
            or settings.APP_ENV == "test"
            or request.method == "OPTIONS"
        ):
            return await call_next(request)

        path = request.url.path
        if path in EXEMPT_PATHS or path.startswith(EXEMPT_PREFIXES):
            return await call_next(request)

        allowed, remaining, wait = self.limiter.check(_identity(request))
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error": {
                        "code": 429,
                        "message": f"请求过于频繁，请 {int(wait) + 1} 秒后重试",
                    },
                },
                headers={
                    "Retry-After": str(int(wait) + 1),
                    "X-RateLimit-Limit": str(self.limiter.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.limiter.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
