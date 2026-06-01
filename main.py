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
    1. Look up short code in DB
    2. Check if URL has expired
    3. Increment the hit counter
    4. Return HTTP 302 to the original URL

    Note: 301 is cached by browsers - the redirect never hits our server again, so we lose the ability to track clicks or update the destination. 302 keeps every request flowing through us.
    """
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            # 1. Fetch the URL record
            cur.execute(
                "SELECT long_url, expires_at FROM urls WHERE short_code = %s",
                (short_code,),
            )

            row = cur.fetchone()

            if row is None:
                raise HTTPException(status_code=404, detail="Short URL nto found.")
            
            long_url, expires_at = row

            # 2. Check expiry
            if expires_at and datetime.utcnow() > expires_at:
                raise HTTPException(status_code=410, detail="This short URL has expired")
            
            # 3. Increment hti count
            cur.execute(
                "UPDATE urls SET hit_count = hit_count + 1 WHERE short_code = %s",
                (short_code,),
            )

        conn.commit()

    finally:
        conn.close()

    # 4. Redirect
    return RedirectResponse(url=long_url, status_code=302)



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