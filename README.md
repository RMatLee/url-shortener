# URL Shortener

A system design interview implementation of a URL shortener service built with FastAPI, PostgreSQL, and Redis.

## Architecture Overview

```
Client → FastAPI → Redis Cache → PostgreSQL
```

- **FastAPI** handles HTTP requests and routing
- **Redis** serves as a read-through cache with negative caching to protect the database
- **PostgreSQL** is the source of truth for all URL mappings

## How It Works

### Short Code Generation

Short codes are generated using a **Base62 encoding** of the database row ID (`shortener.py`):

- Character set: `0-9`, `a-z`, `A-Z` (62 characters)
- 6 characters → 62⁶ ≈ 56 billion unique codes
- The row ID is inserted first to obtain an auto-incremented primary key, then encoded to Base62 and written back — guaranteeing uniqueness without a separate counter service

### Redirect Flow (`GET /{short_code}`)

1. **Cache check (Redis)** — cache hit redirects immediately; a cached negative result returns 404 without touching the DB
2. **DB fallback** — if not in cache, query PostgreSQL
3. **Expiry check** — expired URLs return `410 Gone`
4. **Cache warm** — found URLs are written to Redis for subsequent requests
5. **Hit count increment** — `hit_count` is incremented in the DB (noted as a potential write bottleneck at scale)

### URL Creation Flow (`POST /shorten`)

1. Insert the long URL into PostgreSQL to get an auto-incremented `id`
2. Encode that `id` to a Base62 short code
3. Write the short code back to the row
4. Pre-warm Redis so the first redirect is a cache hit

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/shorten` | Create a short URL (supports optional `expires_at`) |
| `GET` | `/{short_code}` | Redirect to the original URL |
| `GET` | `/stats/{short_code}` | View URL metadata (long URL, hit count, expiry) |
| `GET` | `/health` | Health check including Redis connectivity |

### Example

```bash
# Shorten a URL
curl -X POST http://localhost:8000/shorten \
  -H "Content-Type: application/json" \
  -d '{"long_url": "https://example.com/some/very/long/path"}'

# Response
{
  "short_url": "http://localhost:8000/aB3xYz",
  "short_code": "aB3xYz",
  "long_url": "https://example.com/some/very/long/path"
}
```

## Database Schema

```sql
CREATE TABLE urls (
    id          BIGSERIAL PRIMARY KEY,
    short_code  VARCHAR(12) UNIQUE NOT NULL,
    long_url    TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    expires_at  TIMESTAMP,
    hit_count   BIGINT DEFAULT 0
);

CREATE INDEX idx_short_code ON urls(short_code);
```

## Caching Strategy

Implemented in `cache.py`:

- **Cache key**: `url:{short_code}`
- **TTL**: 24 hours by default (`CACHE_TTL_SECONDS`), capped at the URL's own `expires_at` if set
- **Negative caching**: Non-existent short codes are cached for 5 minutes using a sentinel value (`__NOT_FOUND__`) to prevent DB spam from invalid lookups
- Redis failures are non-fatal — the service degrades gracefully to DB-only mode

## Project Structure

```
url-shortener/
├── main.py          # FastAPI app, route handlers
├── shortener.py     # Base62 encode/decode logic
├── database.py      # PostgreSQL connection and schema init
├── cache.py         # Redis read/write helpers
├── requirements.txt
└── .env             # DATABASE_URL, REDIS_URL, BASE_URL, CACHE_TTL_SECONDS
```

## Setup

**Prerequisites**: Python 3.9+, PostgreSQL, Redis

```bash
pip install -r requirements.txt

# Configure environment
cp .env .env.local
# Set DATABASE_URL and REDIS_URL in .env

uvicorn main:app --reload
```

The database schema is auto-created on startup via `init_db()`.

## Design Decisions & Trade-offs

| Decision | Reasoning |
|----------|-----------|
| Base62 over random hash | Deterministic, no collision risk, short codes stay short as traffic grows |
| ID-then-encode approach | Leverages DB auto-increment as a global counter — simple and collision-free |
| Redis as cache (not source of truth) | PostgreSQL remains authoritative; Redis failures don't cause data loss |
| Negative caching | Prevents cache-bypass DoS via random short code enumeration |
| Hit count incremented inline | Simple to implement; noted as a bottleneck — a production system would batch writes (e.g., 60s flush intervals or a queue) |
| No connection pooling | Each request opens/closes a connection — a production deployment would use `psycopg2.pool` or PgBouncer |
