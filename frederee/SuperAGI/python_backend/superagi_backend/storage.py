import json
import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def create_chat_repository_from_env(database_path):
    database_url = os.environ.get("SUPABASE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if database_url:
        return ResilientChatRepository(
            PostgresChatRepository(_ensure_sslmode(database_url)),
            SQLiteChatRepository(database_path),
        )
    return SQLiteChatRepository(database_path)


class SQLiteChatRepository:
    def __init__(self, database_path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def get_session(self, session_id):
        with closing(sqlite3.connect(self.database_path)) as connection:
            session = connection.execute(
                "select session_id, model from chat_sessions where session_id = ?",
                (session_id,)
            ).fetchone()
            if session is None:
                return None
            rows = connection.execute(
                """
                select role, text
                from chat_messages
                where session_id = ?
                order by id
                """,
                (session_id,)
            ).fetchall()

        return _session_from_rows(session, rows)

    def replace_session_messages(self, session_id, model, messages):
        timestamp = _now_iso()
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    insert into chat_sessions (session_id, model, updated_at)
                    values (?, ?, ?)
                    on conflict(session_id) do update set
                      model = excluded.model,
                      updated_at = excluded.updated_at
                    """,
                    (session_id, model, timestamp)
                )
                connection.execute("delete from chat_messages where session_id = ?", (session_id,))
                connection.executemany(
                    """
                    insert into chat_messages (session_id, role, model, text, created_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            session_id,
                            message["role"],
                            model,
                            message["text"],
                            timestamp
                        )
                        for message in messages
                    ]
                )

    def append_training_example(
        self,
        *,
        session_id,
        model,
        user_text,
        assistant_text,
        prompt,
        context_messages
    ):
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    insert into training_examples (
                      session_id,
                      model,
                      user_text,
                      assistant_text,
                      prompt,
                      context_json,
                      created_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        model,
                        user_text,
                        assistant_text,
                        prompt,
                        json.dumps(context_messages),
                        _now_iso()
                    )
                )

    def _initialize(self):
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    create table if not exists chat_sessions (
                      session_id text primary key,
                      model text not null,
                      updated_at text not null
                    )
                    """
                )
                connection.execute(
                    """
                    create table if not exists chat_messages (
                      id integer primary key autoincrement,
                      session_id text not null,
                      role text not null,
                      model text not null,
                      text text not null,
                      created_at text not null,
                      foreign key (session_id) references chat_sessions(session_id)
                    )
                    """
                )
                connection.execute(
                    """
                    create table if not exists training_examples (
                      id integer primary key autoincrement,
                      session_id text not null,
                      model text not null,
                      user_text text not null,
                      assistant_text text not null,
                      prompt text not null,
                      context_json text not null,
                      created_at text not null,
                      foreign key (session_id) references chat_sessions(session_id)
                    )
                    """
                )


class ResilientChatRepository:
    def __init__(self, primary, fallback, logger=None):
        self.primary = primary
        self.fallback = fallback
        self.logger = logger or logging.getLogger(__name__)

    def get_session(self, session_id):
        try:
            session = self.primary.get_session(session_id)
        except Exception as error:
            self._warn_unavailable("read", error)
        else:
            if session is not None:
                return session

        return self.fallback.get_session(session_id)

    def replace_session_messages(self, session_id, model, messages):
        primary_error = self._try_primary(
            "session write",
            self.primary.replace_session_messages,
            session_id,
            model,
            messages,
        )
        fallback_error = self._try_fallback(
            "session write",
            self.fallback.replace_session_messages,
            session_id,
            model,
            messages,
        )

        if primary_error is not None and fallback_error is not None:
            raise primary_error

    def append_training_example(
        self,
        *,
        session_id,
        model,
        user_text,
        assistant_text,
        prompt,
        context_messages
    ):
        primary_error = self._try_primary(
            "training example write",
            self.primary.append_training_example,
            session_id=session_id,
            model=model,
            user_text=user_text,
            assistant_text=assistant_text,
            prompt=prompt,
            context_messages=context_messages,
        )
        fallback_error = self._try_fallback(
            "training example write",
            self.fallback.append_training_example,
            session_id=session_id,
            model=model,
            user_text=user_text,
            assistant_text=assistant_text,
            prompt=prompt,
            context_messages=context_messages,
        )

        if primary_error is not None and fallback_error is not None:
            raise primary_error

    def _try_primary(self, operation, function, *args, **kwargs):
        try:
            function(*args, **kwargs)
        except Exception as error:
            self._warn_unavailable(operation, error)
            return error
        return None

    def _try_fallback(self, operation, function, *args, **kwargs):
        try:
            function(*args, **kwargs)
        except Exception as error:
            self.logger.warning(
                "Local fallback %s failed: %s",
                operation,
                type(error).__name__,
            )
            return error
        return None

    def _warn_unavailable(self, operation, error):
        self.logger.warning(
            "Primary chat storage %s unavailable; using local fallback: %s",
            operation,
            type(error).__name__,
        )


class PostgresChatRepository:
    def __init__(self, database_url):
        self.database_url = database_url
        self._initialized = False

    def get_session(self, session_id):
        self._ensure_initialized()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "select session_id, model from chat_sessions where session_id = %s",
                    (session_id,)
                )
                session = cursor.fetchone()
                if session is None:
                    return None
                cursor.execute(
                    """
                    select role, text
                    from chat_messages
                    where session_id = %s
                    order by id
                    """,
                    (session_id,)
                )
                rows = cursor.fetchall()

        return _session_from_rows(session, rows)

    def replace_session_messages(self, session_id, model, messages):
        self._ensure_initialized()
        timestamp = _now_iso()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into chat_sessions (session_id, model, updated_at)
                    values (%s, %s, %s)
                    on conflict(session_id) do update set
                      model = excluded.model,
                      updated_at = excluded.updated_at
                    """,
                    (session_id, model, timestamp)
                )
                cursor.execute("delete from chat_messages where session_id = %s", (session_id,))
                cursor.executemany(
                    """
                    insert into chat_messages (session_id, role, model, text, created_at)
                    values (%s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            session_id,
                            message["role"],
                            model,
                            message["text"],
                            timestamp
                        )
                        for message in messages
                    ]
                )

    def append_training_example(
        self,
        *,
        session_id,
        model,
        user_text,
        assistant_text,
        prompt,
        context_messages
    ):
        self._ensure_initialized()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into training_examples (
                      session_id,
                      model,
                      user_text,
                      assistant_text,
                      prompt,
                      context_json,
                      created_at
                    )
                    values (%s, %s, %s, %s, %s, %s::jsonb, %s)
                    """,
                    (
                        session_id,
                        model,
                        user_text,
                        assistant_text,
                        prompt,
                        json.dumps(context_messages),
                        _now_iso()
                    )
                )

    def _ensure_initialized(self):
        if self._initialized:
            return
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for statement in POSTGRES_SCHEMA:
                    cursor.execute(statement)
        self._initialized = True

    def _connect(self):
        import psycopg

        return psycopg.connect(self.database_url)


POSTGRES_SCHEMA = [
    """
    create table if not exists chat_sessions (
      session_id text primary key,
      model text not null,
      updated_at timestamptz not null
    )
    """,
    """
    create table if not exists chat_messages (
      id bigserial primary key,
      session_id text not null references chat_sessions(session_id) on delete cascade,
      role text not null,
      model text not null,
      text text not null,
      created_at timestamptz not null
    )
    """,
    """
    create index if not exists chat_messages_session_id_id_idx
    on chat_messages(session_id, id)
    """,
    """
    create table if not exists training_examples (
      id bigserial primary key,
      session_id text not null references chat_sessions(session_id) on delete cascade,
      model text not null,
      user_text text not null,
      assistant_text text not null,
      prompt text not null,
      context_json jsonb not null,
      created_at timestamptz not null
    )
    """,
    """
    create index if not exists training_examples_session_id_id_idx
    on training_examples(session_id, id)
    """
]


def _session_from_rows(session, rows):
    return {
        "session_id": session[0],
        "model": session[1],
        "messages": [
            {
                "role": role,
                "text": text
            }
            for role, text in rows
        ]
    }


def _ensure_sslmode(database_url):
    parts = urlsplit(database_url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    if any(key == "sslmode" for key, _value in query):
        return database_url

    query.append(("sslmode", "require"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _now_iso():
    return datetime.now(timezone.utc).isoformat()
