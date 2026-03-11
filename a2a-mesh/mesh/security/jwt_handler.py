"""JWT token creation and verification."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Module-level secret — set during server initialization
_jwt_secret: str = ""


def configure(secret: str) -> None:
    """Set the JWT secret key."""
    global _jwt_secret
    _jwt_secret = secret


def create_token(
    subject: str,
    scopes: list[str] | None = None,
    expires_in: int = 86400,
) -> str | None:
    """Create a JWT token."""
    try:
        import jwt

        payload = {
            "sub": subject,
            "scopes": scopes or ["*"],
            "iat": int(time.time()),
            "exp": int(time.time()) + expires_in,
        }
        return jwt.encode(payload, _jwt_secret, algorithm="HS256")
    except ImportError:
        logger.warning("PyJWT not installed, JWT tokens unavailable")
        return None
    except Exception as e:
        logger.error(f"Failed to create JWT: {e}")
        return None


def verify_token(token: str) -> dict[str, Any] | None:
    """Verify and decode a JWT token."""
    if not _jwt_secret:
        return None

    try:
        import jwt

        payload = jwt.decode(token, _jwt_secret, algorithms=["HS256"])
        return payload
    except ImportError:
        return None
    except Exception:
        return None
