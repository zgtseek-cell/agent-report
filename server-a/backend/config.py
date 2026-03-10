"""
Server A Configuration - For price and financial APIs
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_BACKEND_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _BACKEND_DIR.parent

# Redis cache
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "false").lower() in ("true", "1")
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PRICE_TTL = int(os.getenv("REDIS_PRICE_TTL", "3600"))
REDIS_COMPANY_TTL = int(os.getenv("REDIS_COMPANY_TTL", "604800"))

# SQLite cache
PRICE_CACHE_DB_PATH = os.getenv("PRICE_CACHE_DB_PATH", str(_BACKEND_DIR / "price_cache.db"))

# Proxy timeout
PROXY_EXTERN_TIMEOUT = int(os.getenv("PROXY_EXTERN_TIMEOUT", "30"))

# FMP / FinanceToolkit
FMP_API_KEY = os.getenv("FMP_API_KEY", "")

# AkShare adjust parameter
AKSHARE_ADJUST = os.getenv("AKSHARE_ADJUST", "")

# CORS origins
if os.getenv("CORS_ORIGINS"):
    CORS_ORIGINS = [x.strip() for x in os.getenv("CORS_ORIGINS").split(",")]
else:
    CORS_ORIGINS = ["*"]
