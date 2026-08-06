import os
import logging
import sqlite3
from contextlib import contextmanager
from typing import Optional, Dict, List, Any
from datetime import datetime

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class DatabaseConnection:
    """Manages database connection and operations (PostgreSQL or SQLite fallback)."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.db_type = "postgres" if os.getenv("DATABASE_HOST") else "sqlite"
        self.sqlite_path = os.getenv("SQLITE_PATH", "/tmp/research.db")
        
        self.host = host or os.getenv("DATABASE_HOST", "localhost")
        self.port = port or int(os.getenv("DATABASE_PORT", 5432))
        self.database = database or os.getenv("DATABASE_NAME", "research_db")
        self.user = user or os.getenv("DATABASE_USER", "postgres")
        self.password = password or os.getenv("DATABASE_PASSWORD", "")
        
        self._connection = None

    def get_connection(self):
        """Get or create a database connection."""
        if self.db_type == "postgres":
            if not PSYCOPG2_AVAILABLE:
                logger.warning("psycopg2 not installed. Falling back to SQLite.")
                self.db_type = "sqlite"
                return self.get_connection()
            
            if self._connection is None or self._connection.closed:
                try:
                    self._connection = psycopg2.connect(
                        host=self.host,
                        port=self.port,
                        database=self.database,
                        user=self.user,
                        password=self.password,
                        cursor_factory=RealDictCursor,
                    )
                    logger.info("Successfully connected to PostgreSQL database")
                except Exception as e:
                    logger.error(f"Failed to connect to Postgres: {e}. Falling back to SQLite.")
                    self.db_type = "sqlite"
                    return self.get_connection()
        else:
            if self._connection is None:
                self._connection = sqlite3.connect(self.sqlite_path, check_same_thread=False)
                self._connection.row_factory = sqlite3.Row
                logger.info(f"Successfully connected to SQLite database at {self.sqlite_path}")
        
        return self._connection

    def close(self):
        """Close the database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
            logger.info("Database connection closed")

    @contextmanager
    def get_cursor(self):
        """Get a database cursor with automatic commit/rollback."""
        conn = self.get_connection()
        if self.db_type == "postgres":
            cursor = conn.cursor()
        else:
            cursor = conn.cursor()
            
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database operation failed: {e}")
            raise
        finally:
            cursor.close()

    def initialize_schema(self):
        """Create necessary tables if they don't exist."""
        # Use generic SQL that works for both
        queries_sql = """
        CREATE TABLE IF NOT EXISTS research_queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status VARCHAR(50) DEFAULT 'pending',
            result_summary TEXT,
            report_path TEXT
        )"""
        
        if self.db_type == "postgres":
            queries_sql = queries_sql.replace("AUTOINCREMENT", "SERIAL")
            
        findings_sql = """
        CREATE TABLE IF NOT EXISTS research_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id INTEGER REFERENCES research_queries(id) ON DELETE CASCADE,
            source_url TEXT,
            title TEXT,
            content TEXT,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
        
        if self.db_type == "postgres":
            findings_sql = findings_sql.replace("AUTOINCREMENT", "SERIAL")

        reports_sql = """
        CREATE TABLE IF NOT EXISTS research_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id INTEGER REFERENCES research_queries(id) ON DELETE CASCADE,
            report_content TEXT NOT NULL,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            report_format VARCHAR(50) DEFAULT 'markdown'
        )"""
        
        if self.db_type == "postgres":
            reports_sql = reports_sql.replace("AUTOINCREMENT", "SERIAL")

        with self.get_cursor() as cursor:
            cursor.execute(queries_sql)
            cursor.execute(findings_sql)
            cursor.execute(reports_sql)
            
            if self.db_type == "postgres":
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_query_created ON research_queries(created_at DESC)")
            
            logger.info("Database schema initialized successfully")

    def store_query(self, query: str) -> int:
        """Store a new research query and return its ID."""
        with self.get_cursor() as cursor:
            if self.db_type == "postgres":
                cursor.execute(
                    "INSERT INTO research_queries (query, status) VALUES (%s, %s) RETURNING id",
                    (query, "in_progress"),
                )
                return cursor.fetchone()["id"]
            else:
                cursor.execute(
                    "INSERT INTO research_queries (query, status) VALUES (?, ?)",
                    (query, "in_progress"),
                )
                return cursor.lastrowid

    def update_query_status(self, query_id: int, status: str, result_summary: Optional[str] = None, report_path: Optional[str] = None):
        """Update the status of a research query."""
        with self.get_cursor() as cursor:
            placeholder = "%s" if self.db_type == "postgres" else "?"
            cursor.execute(
                f"UPDATE research_queries SET status = {placeholder}, result_summary = {placeholder}, report_path = {placeholder} WHERE id = {placeholder}",
                (status, result_summary, report_path, query_id),
            )

    def store_finding(self, query_id: int, source_url: str, title: str, content: str):
        """Store a research finding."""
        with self.get_cursor() as cursor:
            placeholder = "%s" if self.db_type == "postgres" else "?"
            cursor.execute(
                f"INSERT INTO research_findings (query_id, source_url, title, content) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})",
                (query_id, source_url, title, content),
            )

    def store_report(self, query_id: int, report_content: str, report_format: str = "markdown"):
        """Store a generated report."""
        with self.get_cursor() as cursor:
            placeholder = "%s" if self.db_type == "postgres" else "?"
            cursor.execute(
                f"INSERT INTO research_reports (query_id, report_content, report_format) VALUES ({placeholder}, {placeholder}, {placeholder})",
                (query_id, report_content, report_format),
            )

    def get_historical_queries(self, limit: int = 10) -> list:
        """Retrieve historical research queries."""
        with self.get_cursor() as cursor:
            placeholder = "%s" if self.db_type == "postgres" else "?"
            cursor.execute(
                f"SELECT id, query, created_at, status, result_summary FROM research_queries ORDER BY created_at DESC LIMIT {placeholder}",
                (limit,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

