"""Enhanced security middleware — rate limiting, CORS, request logging."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Rate limiting configuration."""

    requests_per_minute: int = 60
    burst_size: int = 10


class RateLimiter:
    """Simple token bucket rate limiter."""

    def __init__(self, config: RateLimitConfig | None = None):
        self._config = config or RateLimitConfig()
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        """Check if a request is allowed."""
        now = time.time()
        window = 60.0  # 1 minute

        # Clean old entries
        self._buckets[key] = [
            t for t in self._buckets[key] if now - t < window
        ]

        if len(self._buckets[key]) >= self._config.requests_per_minute:
            return False

        self._buckets[key].append(now)
        return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware."""

    def __init__(self, app, config: RateLimitConfig | None = None):
        super().__init__(app)
        self._limiter = RateLimiter(config)

    async def dispatch(self, request: Request, call_next):
        # Rate limit by client IP
        client_ip = request.client.host if request.client else "unknown"
        if not self._limiter.is_allowed(client_ip):
            return JSONResponse(
                {"error": "Rate limit exceeded", "detail": "Too many requests"},
                status_code=429,
            )
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs all API requests."""

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = (time.time() - start) * 1000

        logger.info(
            f"{request.method} {request.url.path} "
            f"→ {response.status_code} ({duration:.0f}ms)"
        )
        return response


class CORSMiddleware(BaseHTTPMiddleware):
    """Simple CORS middleware."""

    def __init__(self, app, origins: list[str] | None = None):
        super().__init__(app)
        self._origins = set(origins or ["*"])

    async def dispatch(self, request: Request, call_next):
        # Handle preflight
        if request.method == "OPTIONS":
            response = Response(status_code=200)
        else:
            response = await call_next(request)

        origin = request.headers.get("origin", "")
        if "*" in self._origins or origin in self._origins:
            response.headers["Access-Control-Allow-Origin"] = origin or "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response.headers["Access-Control-Max-Age"] = "86400"

        return response
