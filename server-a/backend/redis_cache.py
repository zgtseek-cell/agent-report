"""
Redis cache layer for Server A
"""

import json
import logging
from typing import Any

from .config import (
    REDIS_ENABLED,
    REDIS_HOST,
    REDIS_PORT,
    REDIS_PASSWORD,
    REDIS_DB,
    REDIS_PRICE_TTL,
    REDIS_COMPANY_TTL,
)

logger = logging.getLogger(__name__)
_redis_client = None


def get_redis_client():
    """Get Redis client (lazy load)"""
    global _redis_client
    if not REDIS_ENABLED:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis
        _redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD or None,
            db=REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        _redis_client.ping()
        logger.info(f"Redis connected: {REDIS_HOST}:{REDIS_PORT}")
        return _redis_client
    except ImportError:
        logger.warning("Redis not installed, cache disabled")
        return None
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}, cache disabled")
        return None


def _make_price_key(market: str, symbol: str, trade_date: str) -> str:
    """Generate price cache key"""
    return f"price:{market.lower()}:{symbol.upper()}:{trade_date}"


def get_price_cache(market: str, symbol: str, trade_date: str) -> dict | None:
    """Get price cache from Redis"""
    r = get_redis_client()
    if not r:
        return None
    try:
        key = _make_price_key(market, symbol, trade_date)
        data = r.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.debug(f"Redis get price failed: {e}")
    return None


def set_price_cache(market: str, symbol: str, trade_date: str, data: dict) -> None:
    """Write price cache to Redis"""
    r = get_redis_client()
    if not r:
        return
    try:
        key = _make_price_key(market, symbol, trade_date)
        r.setex(key, REDIS_PRICE_TTL, json.dumps(data, ensure_ascii=False))
    except Exception as e:
        logger.debug(f"Redis set price failed: {e}")


def _make_company_key(company_name: str, market: str) -> str:
    """Generate company cache key"""
    return f"company:{market.strip().lower()}::{company_name.strip().lower()}"


def get_company_cache(company_name: str, market: str) -> dict | None:
    """Get company cache from Redis"""
    r = get_redis_client()
    if not r:
        return None
    try:
        key = _make_company_key(company_name, market)
        data = r.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.debug(f"Redis get company failed: {e}")
    return None


def set_company_cache(company_name: str, market: str, data: dict) -> None:
    """Write company cache to Redis"""
    r = get_redis_client()
    if not r:
        return
    try:
        key = _make_company_key(company_name, market)
        r.setex(key, REDIS_COMPANY_TTL, json.dumps(data, ensure_ascii=False))
    except Exception as e:
        logger.debug(f"Redis set company failed: {e}")
