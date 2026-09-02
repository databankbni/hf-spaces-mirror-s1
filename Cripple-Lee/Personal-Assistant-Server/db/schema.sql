-- ============================================================================
-- Personal Assistant — authentication schema
-- ============================================================================
-- Run against your Postgres database, e.g.:
--   psql "$DATABASE_URL" -f db/schema.sql
--
-- The matching server code lives in:
--   src/web/auth.py      (langgraph_sdk.Auth JWT verification)
--   src/web/login.py     (/auth/signup, /auth/login custom routes)
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- users
-- ----------------------------------------------------------------------------
-- One row per account. Passwords are stored as bcrypt hashes only — the
-- plaintext password never leaves the /auth/signup handler.
CREATE TABLE IF NOT EXISTS users (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    username        TEXT        NOT NULL,
    email           TEXT,
    password_hash   TEXT        NOT NULL,
    display_name    TEXT,
    role            TEXT        NOT NULL DEFAULT 'user',
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Case-insensitive uniqueness for usernames and emails.
CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_idx
    ON users (lower(username));

CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_idx
    ON users (lower(email))
    WHERE email IS NOT NULL;

-- ----------------------------------------------------------------------------
-- updated_at trigger
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS users_set_updated_at ON users;
CREATE TRIGGER users_set_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- ----------------------------------------------------------------------------
-- token_usage
-- ----------------------------------------------------------------------------
-- One row per user per calendar month. ``period_start`` is always the first
-- day of the month (UTC); a new month simply gets a fresh row, which is how
-- the allowance "refreshes" on the first day of every month.
CREATE TABLE IF NOT EXISTS token_usage (
    user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    period_start    DATE        NOT NULL,
    tokens_used     BIGINT      NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, period_start)
);

DROP TRIGGER IF EXISTS token_usage_set_updated_at ON token_usage;
CREATE TRIGGER token_usage_set_updated_at
    BEFORE UPDATE ON token_usage
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

COMMIT;

-- ============================================================================
-- Notes
-- ============================================================================
-- * Requires the pgcrypto extension for gen_random_uuid(). On Postgres 13+
--   it is built in; on older versions run:
--       CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- * The application connects with the DATABASE_URL environment variable,
--   e.g.:  postgresql://user:password@localhost:5432/personal_assistant
-- * JWT signing uses the JWT_SECRET environment variable (HS256).
-- ============================================================================
