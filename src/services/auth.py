"""
API key authentication and authorization service.

Handles key verification (SHA-256 hash lookup), rate limiting,
quota enforcement, and API key generation.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import ApiKey, ApiUsageLog
from src.services.cache import (
    check_rate_limit,
    get_monthly_usage,
    increment_monthly_usage,
)

logger = logging.getLogger(__name__)

security_scheme = HTTPBearer()


def hash_api_key(raw_key: str) -> str:
    """
    Compute the SHA-256 hash of a raw API key.

    Args:
        raw_key: The plain-text API key.

    Returns:
        Hex-encoded SHA-256 hash string.
    """
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key with prefix and hash.

    Returns:
        Tuple of (raw_key, key_prefix, key_hash).
        The raw_key should be shown once to the user, never stored.
    """
    random_part = secrets.token_hex(16)  # 32 chars
    raw_key = f"{settings.api_key_prefix}{random_part}"
    key_prefix = raw_key[:16]
    key_hash = hash_api_key(raw_key)
    return raw_key, key_prefix, key_hash


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials,
    db: AsyncSession,
) -> ApiKey:
    """
    Verify an API key from the Authorization header.

    Checks:
        1. Key exists in the database (by hash).
        2. Key is active.
        3. Key has not expired.
        4. Per-minute rate limit not exceeded.
        5. Monthly quota not exceeded.

    Args:
        credentials: The Bearer token from the request header.
        db: Async database session.

    Returns:
        The verified ApiKey ORM object.

    Raises:
        HTTPException: If verification fails at any step.
    """
    raw_key = credentials.credentials
    key_hash = hash_api_key(raw_key)

    # Look up the key
    result = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )

    if not api_key.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key has been deactivated.",
        )

    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key has expired.",
        )

    # Check per-minute rate limit
    allowed = await check_rate_limit(api_key.id, api_key.plan)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
        )

    # Check monthly quota
    usage = await get_monthly_usage(api_key.id)
    if usage >= api_key.monthly_quota:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Monthly quota exceeded. Upgrade your plan for more requests.",
        )

    return api_key


async def log_usage(
    db: AsyncSession,
    api_key: ApiKey,
    endpoint: str,
    status_code: int,
) -> None:
    """
    Log an API request for metering and analytics.

    Writes to both PostgreSQL (api_usage_log) and Redis (monthly counter).

    Args:
        db: Async database session.
        api_key: The authenticated API key.
        endpoint: The request path.
        status_code: The HTTP response status code.
    """
    log_entry = ApiUsageLog(
        api_key_id=api_key.id,
        endpoint=endpoint,
        status_code=status_code,
    )
    db.add(log_entry)

    await increment_monthly_usage(api_key.id)


def verify_admin(credentials: HTTPAuthorizationCredentials) -> None:
    """
    Verify admin access using the ADMIN_SECRET.

    Args:
        credentials: The Bearer token from the request header.

    Raises:
        HTTPException: If the token doesn't match the admin secret.
    """
    if credentials.credentials != settings.admin_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
