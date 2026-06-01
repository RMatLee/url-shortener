import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, HttpUrl
from dotenv import load_dotenv

from database import get_connection, init_db
from shortener import encode
from cache import cache_get, cache_set, cache_set_not_found, cache_ping

load_dotenv()

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

app = FastAPI(title="URL Shortener")

@app.on_event("startup")
def startup():
    """
    Initialize the database schema on startup
    """
    init_db()

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class ShortenRequest(BaseModel):
    long_url: HttpUrl
    expires_at: Optional[datetime] = None

class ShortenResponse(BaseModel):
    short_url: str
    short_code: str
    long_url: str

# ---------------------------------------------------------------------------
# POST /shorten  —  Create a short URL
# ---------------------------------------------------------------------------
@app.post("/shorten", response_model=ShortenResponse, status_code=201)
def shorten_url(body: ShortenRequest):
    """
    1. Insert long URL into DB to get an ID
    2. Encode that ID to Base62 for short code
    3. Update the row with short code
    4. Return the full short URL to the caller
    """
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            # 1. Insert row to get ID
            cur.execute(
                """
                INSERT INTO urls (long_url, expires_at)
                VALUES (%s, %s)
                RETURNING id
                """,
                (str(body.long_url, body.expires_at))
            )

            row_id = cur.fetchone()[0]

            # 2. Encode the ID to Base 62
            short_code = encode(row_id)

            # 3. Store code back on the row
            cur.execute(
                "UPDATE urls SET short_code = %s WHERE id = %s",
                (short_code, row_id)
            )

        conn.commit()
    finally:
        conn.close()

    # Pre-warm cache
    try:
        cache_set(short_code, str(body.long_url), body.expires_at)
    except Exception:
        pass # Cache failure is non fatal
    
    return ShortenResponse(
        short_url=f"{BASE_URL}/{short_code}",
        short_code=short_code,
        long_url=str(body.long_url)
    )

# ---------------------------------------------------------------------------
# GET /{short_code}  —  Redirect to original URL
# ---------------------------------------------------------------------------
@app.get("/{short_code}")
def redirecct(short_code: str):
    """
    1. Check Redis first
        - Cache hit means redirect immediately
        - Cached miss means return 404
        - Not in cache means fall through to DB
    2. DB lookup
        - Not found cache negative result, return 404
        - Found but expired, return 410
        - Found, write to cache and redirect
    3. Increment hit_count asynchronously (to avoid many writes we will do in 60s batches)
    """
    # 1. Cache Check
    try:
        cached = cache_get(short_code)

        if cached is not None:
            # Cache hit so check expiry
            expires_at_str = cached.get("expires_at")

            if expires_at_str:
                expires_at = datetime.fromisoformat(expires_at_str)

                if datetime.utcnow() > expires_at:
                    raise HTTPException(status_code=410, detail="This short URL has expired")
                
                _increment_hit_count(short_code)

                return RedirectResponse(url=cached[long_url], status_code=302)
    except LookupError:
        # Cached negative result
        raise HTTPException(status_code=404, detail="Short URL not found.")
    except HTTPException:
        raise
    except Exception:
        pass # Redis could be down so pass to DB

    # DB Fallback
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            # 1. Fetch the URL record
            cur.execute(
                "SELECT long_url, expires_at FROM urls WHERE short_code = %s",
                (short_code,),
            )

            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        try:
            cache_set_not_found(short_code)
        
        except Exception:
            pass

        raise HTTPException(status_code=404, detail="Short URL not found.")
    
    long_url, expires_at = row

    # 2. Check expiry
    if expires_at and datetime.utcnow() > expires_at:
        raise HTTPException(status_code=410, detail="This short URL has expired")
    
    # Write to cache for next time
    try:
        cache_set(short_code, long_url, expires_at)
    except Exception:
        pass

    # 3. Increment hit count
    _increment_hit_count(short_code)

    # 4. Redirect
    return RedirectResponse(url=long_url, status_code=302)

def _increment_hit_count(short_code: str):
    """
    Increment hit_count of DB. Non-fatal if it fails

    Note: This can become a write bottleneck
    """
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE urls SET hit_count = hit_count + 1 WHERE short_code = %s",
            )
        conn.commit()
        conn.close()
    except Exception:
        pass

# ---------------------------------------------------------------------------
# GET /stats/{short_code}  —  Bonus: inspect a URL's metadata
# ---------------------------------------------------------------------------

@app.get("/stats/{short_code}")
def stats(short_code: str):
    """
    Additional endpoint

    Shows the long URL, creation time, expiry, and hit count
    """
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT long_url, created_at, expires_at, hit_count
                FROM urls
                WHERE short_code = %s
                """,
                (short_code,),
            )

            row = cur.fetchone()

    finally:
        conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail="Short URL not found.")
    
    long_url, created_at, expires_at, hit_count = row

    return {
        "short_code": short_code,
        "short_url": f"{BASE_URL}/{short_code}",
        "long_url": long_url,
        "created_at": created_at,
        "expires_at": expires_at,
        "hit_count": hit_count,
    }

# ---------------------------------------------------------------------------
# GET /health  —  Health check
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "redis": cache_ping(),
    }
