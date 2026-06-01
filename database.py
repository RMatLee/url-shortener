import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def get_connection():
    """Create and return a new database connection"""
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """
    Create the URLs table if it doesn't exist

    Note: In production, using a migration tool like Alembic is common practice instead of running a raw DDL on startup
    """
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS urls (
                        id          BIGSERIAL PRIMARY KEY,
                        short_code  VARCHAR(12) UNIQUE,
                        long_url    TEXT NOT NULL,
                        created_at  TIMESTAMP DEFAULT NOW(),
                        expires_at  TIMESTAMP,
                        hit_count   BIGINT DEFAULT 0
                );
                
                -- Index on short_code since every redirect lookup hits this column
                CREATE INDEX IF NOT EXISTS idx_short_code ON urls(short_code);
            """)
        
        conn.commit()
        
        print("Database initialized.")

    finally:
        conn.close()