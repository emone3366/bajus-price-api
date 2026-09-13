"""
Cache service with Redis support and an in-memory fallback.

Provides write-through caching for the latest prices and
rate limiting. If Redis is unavailable (e.g., local dev), it automatically
falls back to using Python dictionaries.
"""

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError

from src.config import settings

logger = logging.getLogger(__name__)

# --- State ---
_redis: aioredis.Redis | None = None
_use_memory_fallback = False

# --- In-Memory Fallback Storage ---
_mem_cache: dict[str, str] = {}
_mem_rate_limit: dict[str, int] = {}
_mem_usage: dict[str, int] = {}


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that converts Decimal to string for lossless serialization."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


async def init_redis() -> None:
    """Initialize the Redis connection pool. Fallback to memory if it fails."""
    global _redis, _use_memory_fallback

    if settings.redis_host.lower() == "memory":
        logger.info("Redis host set to 'memory'. Using in-memory fallback cache.")
        _use_memory_fallback = True
        return

    _redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=20,
        socket_timeout=2.0,
    )

    try:
        await _redis.ping()
        logger.info("Redis connection established.")
        _use_memory_fallback = False
    except ConnectionError:
        logger.warning(
            f"Failed to connect to Redis at {settings.redis_url}. "
            "Falling back to IN-MEMORY cache. (Not for production!)"
        )
        _use_memory_fallback = True
        await _redis.aclose()
        _redis = None


async def close_redis() -> None:
    """Close the Redis connection pool."""
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
        logger.info("Redis connection closed.")


# --- Price Cache ---


def _price_cache_key(metal: str, karat: str) -> str:
    return f"price:{metal}:{karat}"


async def cache_price(
    metal: str,
    karat: str,
    price_per_gram: Decimal,
    source_ts: datetime | None,
    fetched_at: datetime,
) -> None:
    key = _price_cache_key(metal, karat)
    data = {
        "metal": metal,
        "karat": karat,
        "price_per_gram": str(price_per_gram),
        "currency": "BDT",
        "source_ts": source_ts.isoformat() if source_ts else None,
        "fetched_at": fetched_at.isoformat(),
    }
    json_data = json.dumps(data, cls=DecimalEncoder)

    if _use_memory_fallback:
        _mem_cache[key] = json_data
    elif _redis:
        await _redis.set(key, json_data)

    logger.debug("Cached price: %s = %s", key, price_per_gram)


async def get_cached_price(metal: str, karat: str) -> dict | None:
    key = _price_cache_key(metal, karat)
    raw: str | bytes | None = None

    if _use_memory_fallback:
        raw = _mem_cache.get(key)
    elif _redis:
        raw = await _redis.get(key)
    else:
        return None

    if raw is None:
        return None
    return json.loads(raw)


async def get_all_cached_prices(metal: str) -> list[dict]:
    karats = ["22k", "21k", "18k", "sanaton"]
    results = []
    for karat in karats:
        data = await get_cached_price(metal, karat)
        if data:
            results.append(data)
    return results


async def is_cache_stale(metal: str, karat: str = "22k") -> bool:
    data = await get_cached_price(metal, karat)
    if data is None:
        return True
    try:
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        age_minutes = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 60
        return age_minutes > settings.stale_cache_minutes
    except (KeyError, ValueError):
        return True


# --- Rate Limiting ---


async def check_rate_limit(api_key_id: int, plan: str) -> bool:
    limit = settings.get_rate_limit(plan)

    # Minute-based key (ignores exact sliding window for simplicity in memory mode)
    now = datetime.now(timezone.utc)
    key = f"ratelimit:{api_key_id}:{now.minute}"

    if _use_memory_fallback:
        current = _mem_rate_limit.get(key, 0)
        if current >= limit:
            return False
        _mem_rate_limit[key] = current + 1
        # Simple cleanup of old keys (memory leak if running indefinitely, but fine for local dev)
        keys_to_delete = [
            k for k in _mem_rate_limit if not k.endswith(f":{now.minute}")
        ]
        for k in keys_to_delete:
            del _mem_rate_limit[k]
        return True

    if _redis:
        redis_current = await _redis.get(key)
        if redis_current is not None and int(redis_current) >= limit:
            return False

        pipe = _redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60)
        await pipe.execute()
        return True

    return True


async def get_monthly_usage(api_key_id: int) -> int:
    now = datetime.now(timezone.utc)
    key = f"usage:{api_key_id}:{now.year}:{now.month}"

    if _use_memory_fallback:
        return _mem_usage.get(key, 0)

    if _redis:
        count = await _redis.get(key)
        return int(count) if count else 0

    return 0


async def increment_monthly_usage(api_key_id: int) -> int:
    now = datetime.now(timezone.utc)
    key = f"usage:{api_key_id}:{now.year}:{now.month}"

    if _use_memory_fallback:
        current = _mem_usage.get(key, 0) + 1
        _mem_usage[key] = current
        return current

    if _redis:
        pipe = _redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60 * 60 * 24 * 35)
        results = await pipe.execute()
        return results[0]

    return 0
