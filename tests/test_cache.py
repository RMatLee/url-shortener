import json
import pytest
import redis
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone

from cache import cache_get, cache_set, cache_set_not_found, cache_ping, NOT_FOUND_SENTINEL


def make_redis(get_return=None):
    r = MagicMock()
    r.get.return_value = get_return
    r.ping.return_value = True
    return r


class TestCacheGet:
    def test_miss_returns_none(self):
        with patch("cache._get_client", return_value=make_redis(get_return=None)):
            assert cache_get("xyz") is None

    def test_hit_returns_parsed_dict(self):
        payload = json.dumps({"long_url": "https://example.com", "expires_at": None})
        with patch("cache._get_client", return_value=make_redis(get_return=payload)):
            result = cache_get("abc")
        assert result["long_url"] == "https://example.com"
        assert result["expires_at"] is None

    def test_negative_sentinel_raises_lookup_error(self):
        with patch("cache._get_client", return_value=make_redis(get_return=NOT_FOUND_SENTINEL)):
            with pytest.raises(LookupError):
                cache_get("abc")


class TestCacheSet:
    def test_stores_with_default_ttl(self):
        r = make_redis()
        with patch("cache._get_client", return_value=r), patch("cache.CACHE_TTL", 86400):
            cache_set("abc", "https://example.com")
        r.setex.assert_called_once()
        key, ttl, payload = r.setex.call_args[0]
        assert key == "url:abc"
        assert ttl == 86400
        assert json.loads(payload)["long_url"] == "https://example.com"

    def test_caps_ttl_at_url_expiry(self):
        r = make_redis()
        soon = datetime.now(timezone.utc) + timedelta(seconds=300)
        with patch("cache._get_client", return_value=r), patch("cache.CACHE_TTL", 86400):
            cache_set("abc", "https://example.com", expires_at=soon)
        _, ttl, _ = r.setex.call_args[0]
        assert ttl <= 300

    def test_skips_already_expired_url(self):
        r = make_redis()
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        with patch("cache._get_client", return_value=r):
            cache_set("abc", "https://example.com", expires_at=past)
        r.setex.assert_not_called()

    def test_stores_expires_at_in_payload(self):
        r = make_redis()
        future = datetime.now(timezone.utc) + timedelta(days=1)
        with patch("cache._get_client", return_value=r), patch("cache.CACHE_TTL", 86400):
            cache_set("abc", "https://example.com", expires_at=future)
        _, _, payload = r.setex.call_args[0]
        assert json.loads(payload)["expires_at"] is not None


class TestCacheSetNotFound:
    def test_stores_sentinel_with_5_minute_ttl(self):
        r = make_redis()
        with patch("cache._get_client", return_value=r):
            cache_set_not_found("missing")
        r.setex.assert_called_once_with("url:missing", 300, NOT_FOUND_SENTINEL)


class TestCachePing:
    def test_returns_true_when_redis_up(self):
        with patch("cache._get_client", return_value=make_redis()):
            assert cache_ping() is True

    def test_returns_false_when_redis_down(self):
        r = MagicMock()
        r.ping.side_effect = redis.RedisError("Connection refused")
        with patch("cache._get_client", return_value=r):
            assert cache_ping() is False
