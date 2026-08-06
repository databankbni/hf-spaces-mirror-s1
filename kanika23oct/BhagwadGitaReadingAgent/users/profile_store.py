# ---------------------------------------------------------------------------
# users/profile_store.py — Phase C1.
#
# Per-user settings keyed by email (the only identity in v1 — no password).
# Stored in their OWN SQLite database file (users.sqlite), kept separate from
# the read-only verse corpus so a deploy never overwrites real users.
#
#   email               TEXT PRIMARY KEY
#   name                TEXT      display name (optional)
#   max_minutes         INTEGER   session length cap (>= MIN_SESSION_MINUTES)
#   reminder_opt_in     INTEGER   0/1
#   reminder_time_local TEXT      "HH:MM" or NULL
#   created_at          TEXT
#   updated_at          TEXT
# ---------------------------------------------------------------------------

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from config import (
    DEFAULT_SESSION_MINUTES,
    MAX_SESSION_MINUTES,
    MIN_SESSION_MINUTES,
    USERS_DB_PATH,
)
from users.migrate import migrate_user_tables

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    email               TEXT PRIMARY KEY,
    name                TEXT,
    max_minutes         INTEGER NOT NULL DEFAULT 10,
    reminder_opt_in     INTEGER NOT NULL DEFAULT 0,
    reminder_time_local TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
"""


@dataclass
class UserProfile:
    email: str
    name: str | None
    max_minutes: int
    reminder_opt_in: bool
    reminder_time_local: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp_minutes(minutes: int) -> int:
    return max(MIN_SESSION_MINUTES, min(MAX_SESSION_MINUTES, int(minutes)))


class ProfileStore:
    """CRUD for user profiles, keyed by email."""

    def __init__(self, db_path=USERS_DB_PATH):
        migrate_user_tables(db_path)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after the first release (idempotent)."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(users)")}
        if "name" not in cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN name TEXT")

    def get(self, email: str) -> UserProfile | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
        if row is None:
            return None
        return UserProfile(
            email=row["email"],
            name=row["name"],
            max_minutes=row["max_minutes"],
            reminder_opt_in=bool(row["reminder_opt_in"]),
            reminder_time_local=row["reminder_time_local"],
        )

    def get_or_create(self, email: str) -> UserProfile:
        email = email.strip().lower()
        existing = self.get(email)
        if existing is not None:
            return existing
        now = _now()
        self._conn.execute(
            """
            INSERT INTO users
                (email, name, max_minutes, reminder_opt_in, reminder_time_local,
                 created_at, updated_at)
            VALUES (?, NULL, ?, 0, NULL, ?, ?)
            """,
            (email, DEFAULT_SESSION_MINUTES, now, now),
        )
        self._conn.commit()
        return UserProfile(
            email=email,
            name=None,
            max_minutes=DEFAULT_SESSION_MINUTES,
            reminder_opt_in=False,
            reminder_time_local=None,
        )

    def register(
        self,
        email: str,
        name: str | None = None,
        max_minutes: int | None = None,
        reminder_opt_in: bool | None = None,
        reminder_time_local: str | None = None,
    ) -> tuple[UserProfile, bool]:
        """Create a profile (or update an existing one) from the sign-up form.

        Returns (profile, created) where `created` is True if this email had
        no profile before this call.
        """
        email = email.strip().lower()
        created = self.get(email) is None
        self.get_or_create(email)
        profile = self.update_settings(
            email,
            name=name,
            max_minutes=max_minutes,
            reminder_opt_in=reminder_opt_in,
            reminder_time_local=reminder_time_local,
        )
        return profile, created

    def update_settings(
        self,
        email: str,
        name: str | None = None,
        max_minutes: int | None = None,
        reminder_opt_in: bool | None = None,
        reminder_time_local: str | None = None,
    ) -> UserProfile:
        """Update one or more settings. Creates the user if absent."""
        profile = self.get_or_create(email)
        if name is not None:
            profile.name = name.strip() or None
        if max_minutes is not None:
            profile.max_minutes = _clamp_minutes(max_minutes)
        if reminder_opt_in is not None:
            profile.reminder_opt_in = bool(reminder_opt_in)
        if reminder_time_local is not None:
            profile.reminder_time_local = reminder_time_local or None

        self._conn.execute(
            """
            UPDATE users SET
                name = ?,
                max_minutes = ?,
                reminder_opt_in = ?,
                reminder_time_local = ?,
                updated_at = ?
            WHERE email = ?
            """,
            (
                profile.name,
                profile.max_minutes,
                int(profile.reminder_opt_in),
                profile.reminder_time_local,
                _now(),
                profile.email,
            ),
        )
        self._conn.commit()
        return profile

    def list_subscribers(self) -> list[UserProfile]:
        """All users who opted into reminders and set a time."""
        rows = self._conn.execute(
            "SELECT * FROM users WHERE reminder_opt_in = 1 "
            "AND reminder_time_local IS NOT NULL"
        ).fetchall()
        return [
            UserProfile(
                email=r["email"],
                name=r["name"],
                max_minutes=r["max_minutes"],
                reminder_opt_in=True,
                reminder_time_local=r["reminder_time_local"],
            )
            for r in rows
        ]

    def close(self) -> None:
        self._conn.close()
