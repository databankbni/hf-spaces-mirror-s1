import os
import psycopg2
import logging

logger = logging.getLogger("customercore.db.migrations")

def run_db_migrations():
    """
    Checks if tickets table has missing columns and updates it.
    Also notifies PostgREST to reload its schema cache.
    Fails gracefully if the database is unreachable (e.g., in IPv6-unsupported environments).
    """
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        logger.warning("SUPABASE_DB_URL is not set. Skipping DDL migrations.")
        return

    import urllib.parse
    if "://" in db_url and "@" in db_url:
        try:
            prefix, rest = db_url.split("://", 1)
            creds_part, host_part = rest.rsplit("@", 1)
            if ":" in creds_part:
                user, password = creds_part.split(":", 1)
                unquoted_password = urllib.parse.unquote(password)
                encoded_password = urllib.parse.quote_plus(unquoted_password)
                db_url = f"{prefix}://{user}:{encoded_password}@{host_part}"
        except Exception as parse_err:
            logger.warning(f"Failed to pre-parse SUPABASE_DB_URL: {parse_err}")

    logger.info("Running database migration checks...")
    try:
        # Connect to Postgres
        conn = psycopg2.connect(db_url, connect_timeout=5)
        conn.autocommit = True
        cursor = conn.cursor()
        
        # Add columns if not present
        cursor.execute("""
            ALTER TABLE tickets 
            ADD COLUMN IF NOT EXISTS customer_tier TEXT NOT NULL DEFAULT 'free' 
            CHECK (customer_tier IN ('free','starter','growth','enterprise','vip'));
        """)
        
        cursor.execute("""
            ALTER TABLE tickets 
            ADD COLUMN IF NOT EXISTS masked_text TEXT;
        """)
        
        # Reload PostgREST schema cache
        cursor.execute("SELECT pg_notify('pgrst', 'reload schema');")
        logger.info("Database migration check completed successfully. PostgREST schema reloaded.")
        
        cursor.close()
        conn.close()
    except psycopg2.OperationalError as oe:
        # Graceful fallback: log warning and continue so local app startup does not crash
        logger.warning(
            "Database connection timed out or unreachable (normal in local environments without IPv6 routing). "
            f"Details: {oe}"
        )
    except Exception as e:
        logger.error(f"Failed to execute database migrations: {e}")
