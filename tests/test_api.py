import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from fastapi.testclient import TestClient


def make_conn(fetchone=None):
    """Build a mock psycopg2 connection whose cursor returns the given row."""
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = fetchone
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn


@pytest.fixture(scope="module")
def client():
    with patch("main.init_db"):
        from main import app
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# POST /shorten
# ---------------------------------------------------------------------------

class TestShortenEndpoint:
    def test_returns_201_and_short_url(self, client):
        conn = make_conn(fetchone=(1,))
        with patch("main.get_connection", return_value=conn), patch("main.cache_set"):
            resp = client.post("/shorten", json={"long_url": "https://example.com/path"})
        assert resp.status_code == 201
        data = resp.json()
        assert "short_url" in data
        assert "short_code" in data
        assert data["long_url"] == "https://example.com/path"

    def test_short_code_is_base62(self, client):
        conn = make_conn(fetchone=(999,))
        with patch("main.get_connection", return_value=conn), patch("main.cache_set"):
            resp = client.post("/shorten", json={"long_url": "https://example.com"})
        code = resp.json()["short_code"]
        valid = set("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
        assert all(c in valid for c in code)

    def test_invalid_url_returns_422(self, client):
        resp = client.post("/shorten", json={"long_url": "not-a-url"})
        assert resp.status_code == 422

    def test_missing_body_returns_422(self, client):
        resp = client.post("/shorten", json={})
        assert resp.status_code == 422

    def test_accepts_optional_expires_at(self, client):
        conn = make_conn(fetchone=(1,))
        future = (datetime.utcnow() + timedelta(days=7)).isoformat()
        with patch("main.get_connection", return_value=conn), patch("main.cache_set"):
            resp = client.post("/shorten", json={
                "long_url": "https://example.com",
                "expires_at": future,
            })
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# GET /{short_code}
# ---------------------------------------------------------------------------

class TestRedirectEndpoint:
    def test_cache_hit_redirects(self, client):
        cached = {"long_url": "https://example.com", "expires_at": None}
        with patch("main.cache_get", return_value=cached), \
             patch("main._increment_hit_count"):
            resp = client.get("/abc123", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "https://example.com"

    def test_cache_hit_with_valid_expiry_redirects(self, client):
        future = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        cached = {"long_url": "https://example.com", "expires_at": future}
        with patch("main.cache_get", return_value=cached), \
             patch("main._increment_hit_count"):
            resp = client.get("/abc123", follow_redirects=False)
        assert resp.status_code == 302

    def test_cache_hit_expired_returns_410(self, client):
        past = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        cached = {"long_url": "https://example.com", "expires_at": past}
        with patch("main.cache_get", return_value=cached):
            resp = client.get("/abc123", follow_redirects=False)
        assert resp.status_code == 410

    def test_negative_cache_returns_404(self, client):
        with patch("main.cache_get", side_effect=LookupError):
            resp = client.get("/missing", follow_redirects=False)
        assert resp.status_code == 404

    def test_cache_miss_db_hit_redirects(self, client):
        conn = make_conn(fetchone=("https://example.com", None))
        with patch("main.cache_get", return_value=None), \
             patch("main.get_connection", return_value=conn), \
             patch("main.cache_set"), \
             patch("main._increment_hit_count"):
            resp = client.get("/abc123", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "https://example.com"

    def test_cache_miss_db_miss_returns_404(self, client):
        conn = make_conn(fetchone=None)
        with patch("main.cache_get", return_value=None), \
             patch("main.get_connection", return_value=conn), \
             patch("main.cache_set_not_found"):
            resp = client.get("/missing", follow_redirects=False)
        assert resp.status_code == 404

    def test_cache_miss_db_expired_returns_410(self, client):
        past = datetime.utcnow() - timedelta(hours=1)
        conn = make_conn(fetchone=("https://example.com", past))
        with patch("main.cache_get", return_value=None), \
             patch("main.get_connection", return_value=conn):
            resp = client.get("/abc123", follow_redirects=False)
        assert resp.status_code == 410


# ---------------------------------------------------------------------------
# GET /stats/{short_code}
# ---------------------------------------------------------------------------

class TestStatsEndpoint:
    def test_returns_url_metadata(self, client):
        now = datetime.utcnow()
        conn = make_conn(fetchone=("https://example.com", now, None, 42))
        with patch("main.get_connection", return_value=conn):
            resp = client.get("/stats/abc123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["long_url"] == "https://example.com"
        assert data["hit_count"] == 42
        assert data["short_code"] == "abc123"

    def test_unknown_code_returns_404(self, client):
        conn = make_conn(fetchone=None)
        with patch("main.get_connection", return_value=conn):
            resp = client.get("/stats/unknown")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_returns_ok_with_redis_up(self, client):
        with patch("main.cache_ping", return_value=True):
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "redis": True}

    def test_reports_redis_down(self, client):
        with patch("main.cache_ping", return_value=False):
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["redis"] is False
