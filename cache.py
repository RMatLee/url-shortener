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
NOT_FOUND_SENTINEL = "__NOT_FOUND__"

def _get_client() -> redis.Redis:
    """
    Return a Redis client.
    """
    return redis.from_url(REDIS_URL, decode_responses=True)

def cache_get(short_code: str) -> Optional[dict]:
    """
    Look up a short code in Redis

    Return: dict with 'long_url' and 'expires_at' if found in cache
    None if if not in cache (called should fall back to DB)
    Raises LookupError if we cached a negative result (code DNE)

    Note: Without negative caching, anyone can spam random short codes
    and request punches through the DB.
    """
    client = _get_client()
    value = client.get(f"url:{short_code}")

    if value is None:
        return None # Cache miss
    
    if value == NOT_FOUND_SENTINEL:
        raise LookupError("Cached negative result -- URL Does not Exist.")
    
    return json.load(value)

def cache_set(short_code: str, long_url: str, expires_at=None):
    """
    Store a URL mapping in Redis
    TTL is the lesser of CACHE_TTL and the URL's own expiry if set
    """
    client = _get_client()

    payload = json.dump({
        "long_url": long_url,
        "expires_at": expires_at.isoformat() if expires_at else None,
    })

    # If URL has its own expiry, don't cache it longer that it
    ttl = CACHE_TTL

    if expires_at:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        expires_at_aware = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
        seconds_until_expiry = int((expires_at_aware - now).total_seconds())

        if seconds_until_expiry <= 0:
            return # Already expired
        
        ttl = min(ttl, seconds_until_expiry)

        client.setex(f"url:{short_code}", ttl, payload)

def cache_set_not_found(short_code: str):
    """
    Cache a negative result for a short code that doesn't exist in DB.
    """
    client = _get_client()
    client.setex(f"url:{short_code}", 300, NOT_FOUND_SENTINEL) # 5 Min

def cache_invalidate(short_code: str):
    """
    Remove a short code from cache
    Call this if URL is ever updated/deleted
    """
    client = _get_client()
    client.delete(f"url:{short_code}")

def cache_pint() -> bool:
    """
    Health check
    """
    try:
        return _get_client().ping()
    except redis.RedisError:
        return False