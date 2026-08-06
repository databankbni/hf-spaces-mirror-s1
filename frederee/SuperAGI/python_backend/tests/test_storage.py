import gc
import os
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from superagi_backend.runner import DEFAULT_MODEL
from superagi_backend.service import ChatService


REPO_ROOT = Path(__file__).resolve().parents[2]


class StorageSelectionTest(unittest.TestCase):
    def test_repository_factory_uses_supabase_database_url(self):
        from superagi_backend.storage import (
            PostgresChatRepository,
            ResilientChatRepository,
            SQLiteChatRepository,
            create_chat_repository_from_env,
        )

        with patch.dict(
            os.environ,
            {
                "SUPABASE_DATABASE_URL": (
                    "postgresql://postgres:secret@db.jscgykqjejcfdfnihizw.supabase.co:5432/postgres"
                )
            },
            clear=True
        ):
            repository = create_chat_repository_from_env("unused.sqlite3")

        self.assertIsInstance(repository, ResilientChatRepository)
        self.assertIsInstance(repository.primary, PostgresChatRepository)
        self.assertIsInstance(repository.fallback, SQLiteChatRepository)
        self.assertEqual(
            repository.primary.database_url,
            "postgresql://postgres:secret@db.jscgykqjejcfdfnihizw.supabase.co:5432/postgres?sslmode=require"
        )

    def test_repository_factory_keeps_explicit_sslmode(self):
        from superagi_backend.storage import PostgresChatRepository, create_chat_repository_from_env

        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": (
                    "postgresql://postgres:secret@db.jscgykqjejcfdfnihizw.supabase.co:5432/postgres"
                    "?sslmode=verify-full"
                )
            },
            clear=True
        ):
            repository = create_chat_repository_from_env("unused.sqlite3")

        self.assertIsInstance(repository.primary, PostgresChatRepository)
        self.assertTrue(repository.primary.database_url.endswith("?sslmode=verify-full"))

    def test_resilient_repository_falls_back_when_primary_storage_fails(self):
        from superagi_backend.storage import ResilientChatRepository

        primary = FailingRepository()
        fallback = RecordingRepository()
        fallback.sessions["fallback-session-1"] = {
            "session_id": "fallback-session-1",
            "model": "superagi-dev",
            "messages": [{"role": "visitor", "text": "Stored locally"}],
        }
        repository = ResilientChatRepository(primary, fallback, logger=SilentLogger())

        session = repository.get_session("fallback-session-1")
        repository.replace_session_messages(
            "fallback-session-2",
            "superagi-dev",
            [{"role": "visitor", "text": "Persist this locally"}],
        )
        repository.append_training_example(
            session_id="fallback-session-2",
            model="superagi-dev",
            user_text="Persist this locally",
            assistant_text="Stored reply",
            prompt="User: Persist this locally\nAGI:",
            context_messages=[{"role": "visitor", "text": "Persist this locally"}],
        )

        self.assertEqual(session["messages"][0]["text"], "Stored locally")
        self.assertEqual(fallback.replaced_sessions[0]["session_id"], "fallback-session-2")
        self.assertEqual(fallback.training_examples[0]["assistant_text"], "Stored reply")

    def test_sqlite_repository_closes_connections(self):
        from superagi_backend.storage import SQLiteChatRepository

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            gc.collect()
        with warnings.catch_warnings(record=True) as captured_warnings:
            warnings.simplefilter("always", ResourceWarning)
            with tempfile.TemporaryDirectory() as directory:
                repository = SQLiteChatRepository(f"{directory}/chat.sqlite3")
                repository.replace_session_messages(
                    "sqlite-session-1",
                    "superagi-dev",
                    [{"role": "visitor", "text": "Hello"}],
                )
                repository.get_session("sqlite-session-1")
                repository.append_training_example(
                    session_id="sqlite-session-1",
                    model="superagi-dev",
                    user_text="Hello",
                    assistant_text="Hi",
                    prompt="User: Hello\nAGI:",
                    context_messages=[{"role": "visitor", "text": "Hello"}],
                )
                del repository
            gc.collect()

        resource_warnings = [
            warning for warning in captured_warnings
            if issubclass(warning.category, ResourceWarning)
        ]
        self.assertEqual(resource_warnings, [])

    def test_chat_service_uses_supplied_repository(self):
        repository = RecordingRepository()
        runner = RecordingRunner("stored reply")
        service = ChatService("unused.sqlite3", model_runner=runner, repository=repository)

        response = service.handle_chat(
            {
                "session_id": "repo-session-1",
                "model": "superagi-dev",
                "message": "Persist this"
            }
        )

        self.assertEqual(response["message"]["text"], "stored reply")
        self.assertEqual(repository.replaced_sessions[0]["session_id"], "repo-session-1")
        self.assertEqual(
            [message["text"] for message in repository.replaced_sessions[0]["messages"]],
            ["Persist this", "stored reply"]
        )
        self.assertEqual(repository.training_examples[0]["user_text"], "Persist this")
        self.assertEqual(repository.training_examples[0]["assistant_text"], "stored reply")
        self.assertEqual(
            [message["text"] for message in repository.training_examples[0]["context_messages"]],
            ["Persist this"]
        )

    def test_backend_requirements_include_postgres_driver(self):
        requirements = (REPO_ROOT / "python_backend" / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("psycopg", requirements)

    def test_supabase_migration_defines_required_tables(self):
        migration = (
            REPO_ROOT / "python_backend" / "migrations" / "001_chat_storage.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("create table if not exists chat_sessions", migration)
        self.assertIn("create table if not exists chat_messages", migration)
        self.assertIn("create table if not exists training_examples", migration)


class RecordingRepository:
    def __init__(self):
        self.sessions = {}
        self.replaced_sessions = []
        self.training_examples = []

    def get_session(self, session_id):
        return self.sessions.get(session_id)

    def replace_session_messages(self, session_id, model, messages):
        self.replaced_sessions.append(
            {
                "session_id": session_id,
                "model": model,
                "messages": messages
            }
        )
        self.sessions[session_id] = {
            "session_id": session_id,
            "model": model,
            "messages": messages
        }

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
        self.training_examples.append(
            {
                "session_id": session_id,
                "model": model,
                "user_text": user_text,
                "assistant_text": assistant_text,
                "prompt": prompt,
                "context_messages": context_messages
            }
        )


class FailingRepository:
    def get_session(self, session_id):
        raise RuntimeError("primary storage unavailable")

    def replace_session_messages(self, session_id, model, messages):
        raise RuntimeError("primary storage unavailable")

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
        raise RuntimeError("primary storage unavailable")


class SilentLogger:
    def warning(self, *args, **kwargs):
        pass


class RecordingRunner:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def generate(self, *, prompt, model):
        self.calls.append({"prompt": prompt, "model": model})
        return self.replies.pop(0)

    def describe(self):
        return {
            "model": DEFAULT_MODEL,
            "runner": "recording",
            "ready": True
        }


if __name__ == "__main__":
    unittest.main()
