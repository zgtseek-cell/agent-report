"""
Redis 缓存层
- 价格数据缓存
- 公司名解析缓存
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
    """获取 Redis 客户端（懒加载）"""
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
        # 测试连接
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
    """生成价格缓存键"""
    return f"price:{market.lower()}:{symbol.upper()}:{trade_date}"


def get_price_cache(market: str, symbol: str, trade_date: str) -> dict | None:
    """从 Redis 获取价格缓存"""
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
    """写入价格缓存到 Redis"""
    r = get_redis_client()
    if not r:
        return
    try:
        key = _make_price_key(market, symbol, trade_date)
        r.setex(key, REDIS_PRICE_TTL, json.dumps(data, ensure_ascii=False))
    except Exception as e:
        logger.debug(f"Redis set price failed: {e}")


def _make_company_key(company_name: str, market: str) -> str:
    """生成公司解析缓存键"""
    return f"company:{market.lower()}:{company_name.strip().lower()}"


def get_company_cache(company_name: str, market: str) -> dict | None:
    """从 Redis 获取公司解析缓存"""
    r = get_redis_client()
    if not r:
        return None
    try:
        key = _make_company_key(company_name, market)
        data = r.get(key)
        if data:
            result = json.loads(data)
            result["source"] = "redis"
            return result
    except Exception as e:
        logger.debug(f"Redis get company failed: {e}")
    return None


def set_company_cache(company_name: str, market: str, data: dict) -> None:
    """写入公司解析缓存到 Redis"""
    r = get_redis_client()
    if not r:
        return
    try:
        key = _make_company_key(company_name, market)
        # 移除 source 字段再缓存
        cached_data = {k: v for k, v in data.items() if k != "source"}
        r.setex(key, REDIS_COMPANY_TTL, json.dumps(cached_data, ensure_ascii=False))
    except Exception as e:
        logger.debug(f"Redis set company failed: {e}")
