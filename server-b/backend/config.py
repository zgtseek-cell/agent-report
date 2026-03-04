"""
从 config.yaml 加载配置，环境变量可覆盖。
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
_CONFIG_PATH = _PROJECT_ROOT / "config.yaml"


def _load_config() -> dict:
    """从 config.yaml 加载配置"""
    if not _CONFIG_PATH.exists():
        return {}
    try:
        import yaml
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (ImportError, Exception):
        return {}


def _get(key_path: str, default=None, env_key: str | None = None):
    """从配置文件读取，环境变量优先。key_path 如 'deepseek.api_key'"""
    cfg = _load_config()
    for k in key_path.split("."):
        cfg = (cfg or {}).get(k)
        if cfg is None:
            break
    val = cfg if cfg is not None else default
    if env_key and os.getenv(env_key) not in (None, ""):
        return os.getenv(env_key)
    return val


# ----- DeepSeek / LLM -----
DEEPSEEK_API_KEY = _get("deepseek.api_key", "", "DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = _get("deepseek.base_url", "https://api.deepseek.com", "DEEPSEEK_BASE_URL")
DEEPSEEK_TIMEOUT = int(_get("deepseek.timeout", 60) or 60)
DEEPSEEK_MODEL = _get("deepseek.model", "deepseek-reasoner", "DEEPSEEK_MODEL")

# ----- 日志 -----
LOG_PATH = _get("log.path", "logs/requests.log", "LOG_PATH")

# ----- 意见反馈存储 -----
FEEDBACK_DIR = Path(_get("feedback.dir", "feedback", "FEEDBACK_DIR") or "feedback")
if not FEEDBACK_DIR.is_absolute():
    FEEDBACK_DIR = _PROJECT_ROOT / FEEDBACK_DIR
_raw_debug = _get("log.debug_path", "", "DEBUG_LOG_PATH")
if _raw_debug and Path(_raw_debug).is_absolute():
    DEBUG_LOG_PATH = _raw_debug
elif _raw_debug:
    DEBUG_LOG_PATH = str(_PROJECT_ROOT / _raw_debug)
else:
    DEBUG_LOG_PATH = str(_PROJECT_ROOT / "logs" / "debug.log")  # 默认

# ----- 服务端 -----
TIMEOUT_KEEP_ALIVE = int(_get("server.timeout_keep_alive", 120) or 120)# ----- CORS -----
if os.getenv("CORS_ORIGINS"):
    CORS_ORIGINS = [x.strip() for x in os.getenv("CORS_ORIGINS").split(",")]
else:
    _origins = _get("cors.origins", ["*"])
    CORS_ORIGINS = _origins if isinstance(_origins, list) else ["*"]# ----- 股票价格缓存 -----
_pcp = _get("price_cache.db_path", "", "PRICE_CACHE_DB_PATH")
PRICE_CACHE_DB_PATH = _pcp if _pcp else str(_BACKEND_DIR / "price_cache.db")# ----- 股票价格接口（从指定 IP:端口请求）-----
PRICE_API_ENABLED = _get("price_api.enabled", False) in (True, "true", "1")
PRICE_API_HOST = _get("price_api.host", "127.0.0.1", "PRICE_API_HOST")
PRICE_API_PORT = int(_get("price_api.port", 8000) or 8000)
PRICE_API_BASE_URL = _get("price_api.base_url", "", "PRICE_API_BASE_URL")# ----- 行情数据源 -----
AKSHARE_ADJUST = _get("akshare.adjust", "", "AKSHARE_ADJUST")

# ========== 价格服务拆分配置 ==========
PRICE_SPLIT_ENABLED = _get("price_split.enabled", False, "PRICE_SPLIT_ENABLED") in (True, "true", "1")

# ----- Redis 缓存 -----
REDIS_ENABLED = _get("redis.enabled", False) in (True, "true", "1")
REDIS_HOST = _get("redis.host", "127.0.0.1", "REDIS_HOST")
REDIS_PORT = int(_get("redis.port", 6379) or 6379)
REDIS_PASSWORD = _get("redis.password", "", "REDIS_PASSWORD")
REDIS_DB = int(_get("redis.db", 0) or 0)
REDIS_PRICE_TTL = int(_get("redis.price_ttl", 3600) or 3600)
REDIS_COMPANY_TTL = int(_get("redis.company_ttl", 604800) or 604800)

# ----- 海外价格服务（Server A）-----
OVERSEA_PRICE_API_ENABLED = _get("oversea_price_api.enabled", True) in (True, "true", "1")
OVERSEA_PRICE_API_HOST = _get("oversea_price_api.host", _get("server_a.host", "127.0.0.1", "SERVER_A_HOST"), "OVERSEA_PRICE_API_HOST")
OVERSEA_PRICE_API_PORT = int(_get("oversea_price_api.port", _get("server_a.port", 8000, "SERVER_A_PORT")) or 8000)
OVERSEA_PRICE_API_BASE_URL = _get("oversea_price_api.base_url", _get("server_a.base_url", "", "SERVER_A_BASE_URL"), "OVERSEA_PRICE_API_BASE_URL")

# Server A 代理配置
SERVER_A_HOST = _get("server_a.host", "127.0.0.1", "SERVER_A_HOST")
SERVER_A_PORT = int(_get("server_a.port", 8000, "SERVER_A_PORT"))
SERVER_A_BASE_URL = _get("server_a.base_url", "", "SERVER_A_BASE_URL")
SERVER_A_API_TOKEN = _get("server_a.api_token", "", "SERVER_A_API_TOKEN")
# 端口代理模式：A 开启 PROXY_PORT 时，B 可设 USE_HTTP_PROXY=true 和 SERVER_A_PROXY_PORT，通过 HTTP_PROXY 走 A，无需逐请求 /api/proxy/extern
USE_HTTP_PROXY = _get("server_a.use_http_proxy", False, "USE_HTTP_PROXY") in (True, "true", "1")
SERVER_A_PROXY_PORT = int(_get("server_a.proxy_port", 0, "SERVER_A_PROXY_PORT") or 0)

# 代理请求超时和重试配置
PROXY_TIMEOUT = int(_get("proxy.timeout", 30, "PROXY_TIMEOUT"))
PROXY_RETRY = int(_get("proxy.retry", 3, "PROXY_RETRY"))