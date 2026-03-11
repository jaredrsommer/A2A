"""Authentication middleware for the mesh API."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Paths that don't require authentication
PUBLIC_PATHS = frozenset({
    "/",
    "/health",
    "/.well-known/agent.json",
})

# Path prefixes that don't require auth
PUBLIC_PREFIXES = (
    "/static/",
)


@dataclass
class AuthContext:
    """Authentication context attached to request state."""

    identity: str = "anonymous"
    scopes: list[str] = field(default_factory=lambda: ["*"])


class AuthMiddleware(BaseHTTPMiddleware):
    """Bearer token authentication middleware.

    Checks Authorization header on protected routes.
    Designed for easy upgrade to JWT later.
    """

    def __init__(self, app, api_keys: Sequence[str] | None = None):
        super().__init__(app)
        self._api_keys: set[str] = set(api_keys or [])

    @property
    def enabled(self) -> bool:
        return len(self._api_keys) > 0

    async def dispatch(self, request: Request, call_next):
        # Skip auth if no keys configured
        if not self.enabled:
            request.state.auth = AuthContext()
            return await call_next(request)

        path = request.url.path

        # Public endpoints don't need auth
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            request.state.auth = AuthContext()
            return await call_next(request)

        # WebSocket upgrade — check query param or header
        if request.headers.get("upgrade", "").lower() == "websocket":
            token = request.query_params.get("token", "")
            if token in self._api_keys:
                request.state.auth = AuthContext(identity="api_key")
                return await call_next(request)

        # Check Authorization header
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            # Check API key
            if token in self._api_keys:
                request.state.auth = AuthContext(identity="api_key")
                return await call_next(request)
            # JWT check will be added in Phase 8
            try:
                from mesh.security.jwt_handler import verify_token

                claims = verify_token(token)
                if claims:
                    request.state.auth = AuthContext(
                        identity=claims.get("sub", "jwt_user"),
                        scopes=claims.get("scopes", ["*"]),
                    )
                    return await call_next(request)
            except (ImportError, Exception):
                pass

        logger.debug(f"Auth failed for {request.method} {path}")
        return JSONResponse(
            {"error": "Unauthorized", "detail": "Valid API key required"},
            status_code=401,
        )
