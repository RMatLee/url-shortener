import os
import json
import redis

from typing import Optional
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# TTL for cached URLS (seconds)
# Note: TTL is a key tuning nob (Too short causes cache thrash and too long stale data). Long TTL is fine since URL is immutable
CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", 86400)) # One Day

# Sentinel value stored in Redis when a code is confirmed not to exist, preventing negative lookups
NOT_FOUND_SSENTINEL = "__NOT_FOUND__"

def _get_client() -> redis.Redis:
    """
    Return a Redis client.
    """
    return redis.from_url(REDIS_URL, decode_responses=True)

def cache_get(short_code: str) -> Optional[dict]:
    