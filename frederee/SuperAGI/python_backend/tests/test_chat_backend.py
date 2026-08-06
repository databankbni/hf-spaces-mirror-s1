import json
import sqlite3
import tempfile
import unittest

from superagi_backend.app import create_wsgi_app
from superagi_backend.runner import ModelRouter
from superagi_backend.service import ChatService, ChatValidationError


class ChatServiceTest(unittest.TestCase):
    def test_chat_request_persists_session_and_returns_model_reply(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = RecordingRunner("runner reply")
            service = ChatService(f"{directory}/chat.sqlite3", model_runner=runner)

            response = service.handle_chat(
                {
                    "session_id": "browser-session-1",
                    "model": "superagi-dev",
                    "messages": [
                        {
                            "role": "assistant",
                            "text": "Hi. This chat window is ready for the AI backend."
                        }
                    ],
                    "message": "What can you do?"
                }
            )

            self.assertEqual(response["session_id"], "browser-session-1")
            self.assertEqual(response["model"], "superagi-dev")
            self.assertEqual(response["message"]["role"], "assistant")
            self.assertEqual(response["message"]["text"], "runner reply")
            self.assertEqual(len(response["messages"]), 3)
            self.assertEqual(runner.calls[0]["model"], "superagi-dev")
            self.assertIn("What can you do?", runner.calls[0]["prompt"])

            with sqlite3.connect(f"{directory}/chat.sqlite3") as connection:
                rows = connection.execute(
                    "select role, model, text from chat_messages order by id"
                ).fetchall()

            self.assertEqual(
                rows,
                [
                    ("assistant", "superagi-dev", "Hi. This chat window is ready for the AI backend."),
                    ("visitor", "superagi-dev", "What can you do?"),
                    ("assistant", "superagi-dev", "runner reply")
                ]
            )

    def test_chat_request_uses_persisted_context_when_browser_does_not_send_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = RecordingRunner("first reply", "second reply")
            service = ChatService(f"{directory}/chat.sqlite3", model_runner=runner)

            service.handle_chat(
                {
                    "session_id": "browser-session-1",
                    "model": "superagi-dev",
                    "messages": [],
                    "message": "First message"
                }
            )
            response = service.handle_chat(
                {
                    "session_id": "browser-session-1",
                    "model": "superagi-dev",
                    "message": "Second message"
                }
            )

            self.assertEqual(
                [message["text"] for message in response["messages"]],
                ["First message", "first reply", "Second message", "second reply"]
            )
            self.assertIn("First message", runner.calls[1]["prompt"])
            self.assertIn("Second message", runner.calls[1]["prompt"])

    def test_chat_request_appends_training_examples_for_every_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = RecordingRunner("first reply", "second reply")
            service = ChatService(f"{directory}/chat.sqlite3", model_runner=runner)

            service.handle_chat(
                {
                    "session_id": "training-session-1",
                    "model": "superagi-dev",
                    "messages": [],
                    "message": "First message"
                }
            )
            service.handle_chat(
                {
                    "session_id": "training-session-1",
                    "model": "superagi-dev",
                    "message": "Second message"
                }
            )

            with sqlite3.connect(f"{directory}/chat.sqlite3") as connection:
                try:
                    rows = connection.execute(
                        """
                        select session_id, model, user_text, assistant_text, prompt, context_json
                        from training_examples
                        order by id
                        """
                    ).fetchall()
                except sqlite3.OperationalError as error:
                    self.fail(f"training_examples table missing or invalid: {error}")

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][0], "training-session-1")
            self.assertEqual(rows[0][1], "superagi-dev")
            self.assertEqual(rows[0][2], "First message")
            self.assertEqual(rows[0][3], "first reply")
            self.assertIn("User: First message", rows[0][4])
            self.assertEqual(json.loads(rows[0][5]), [{"role": "visitor", "text": "First message"}])
            self.assertEqual(rows[1][2], "Second message")
            self.assertEqual(rows[1][3], "second reply")
            self.assertIn("first reply", rows[1][4])
            self.assertEqual(
                [message["text"] for message in json.loads(rows[1][5])],
                ["First message", "first reply", "Second message"]
            )

    def test_get_session_returns_persisted_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ChatService(
                f"{directory}/chat.sqlite3",
                model_runner=RecordingRunner("session reply")
            )
            service.handle_chat(
                {
                    "session_id": "browser-session-1",
                    "model": "superagi-dev",
                    "message": "Hello"
                }
            )

            session = service.get_session("browser-session-1")

            self.assertEqual(session["session_id"], "browser-session-1")
            self.assertEqual(session["model"], "superagi-dev")
            self.assertEqual(
                [message["text"] for message in session["messages"]],
                ["Hello", "session reply"]
            )

    def test_chat_request_rejects_unsupported_models_when_runner_declares_options(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ChatService(
                f"{directory}/chat.sqlite3",
                model_runner=ModelRouter(
                    runners={"SuperAGI 0.2": RecordingRunner("model reply")},
                    default_model="SuperAGI 0.2",
                )
            )

            with self.assertRaises(ChatValidationError) as context:
                service.handle_chat(
                    {
                        "session_id": "browser-session-1",
                        "model": "Not a model",
                        "message": "Hello",
                    }
                )

            self.assertIn("model must be one of", str(context.exception))

    def test_chat_request_routes_current_superagi_model(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = RecordingRunner("0.2 reply")
            service = ChatService(
                f"{directory}/chat.sqlite3",
                model_runner=ModelRouter(
                    runners={"SuperAGI 0.2": runner},
                    default_model="SuperAGI 0.2",
                )
            )

            response = service.handle_chat(
                {
                    "session_id": "browser-session-1",
                    "model": "SuperAGI 0.2",
                    "message": "Hello",
                }
            )

            self.assertEqual(response["model"], "SuperAGI 0.2")
            self.assertEqual(response["message"]["text"], "0.2 reply")
            self.assertEqual(runner.calls[0]["model"], "SuperAGI 0.2")


class ChatApiTest(unittest.TestCase):
    def test_wsgi_api_returns_root_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_wsgi_app(
                f"{directory}/chat.sqlite3",
                model_runner=RecordingRunner("api reply")
            )

            status, _headers, body = _request(app, "GET", "/")
            response = json.loads(body.decode("utf-8"))

            self.assertEqual(status, "200 OK")
            self.assertEqual(response["name"], "SuperAGI Chat API")
            self.assertIn("/api/chat", response["endpoints"])

    def test_wsgi_api_accepts_chat_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_wsgi_app(
                f"{directory}/chat.sqlite3",
                model_runner=RecordingRunner("api reply")
            )
            payload = json.dumps(
                {
                    "session_id": "api-session-1",
                    "model": "superagi-dev",
                    "messages": [],
                    "message": "Hello"
                }
            ).encode("utf-8")
            response_status = []
            response_headers = []

            body = b"".join(
                app(
                    {
                        "REQUEST_METHOD": "POST",
                        "PATH_INFO": "/api/chat",
                        "CONTENT_LENGTH": str(len(payload)),
                        "wsgi.input": _Body(payload)
                    },
                    lambda status, headers: (
                        response_status.append(status),
                        response_headers.extend(headers)
                    )
                    and None
                )
            )

            response = json.loads(body.decode("utf-8"))

            self.assertEqual(response_status, ["200 OK"])
            self.assertIn(("Content-Type", "application/json; charset=utf-8"), response_headers)
            self.assertEqual(response["session_id"], "api-session-1")
            self.assertEqual(response["model"], "superagi-dev")
            self.assertEqual(response["message"]["role"], "assistant")
            self.assertEqual(response["message"]["text"], "api reply")

    def test_wsgi_api_returns_model_error_as_json(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_wsgi_app(
                f"{directory}/chat.sqlite3",
                model_runner=FailingRunner()
            )

            try:
                status, _headers, body = _post_json(
                    app,
                    "/api/chat",
                    {
                        "session_id": "api-session-1",
                        "model": "superagi-dev",
                        "message": "Hello"
                    }
                )
            except RuntimeError as error:
                self.fail(f"API raised instead of returning JSON: {error}")
            response = json.loads(body.decode("utf-8"))

            self.assertEqual(status, "503 Service Unavailable")
            self.assertEqual(response["error"], "model_unavailable")
            self.assertIn("checkpoint failed", response["message"])

    def test_wsgi_api_returns_chat_session(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_wsgi_app(
                f"{directory}/chat.sqlite3",
                model_runner=RecordingRunner("api reply")
            )
            _post_json(
                app,
                "/api/chat",
                {
                    "session_id": "api-session-1",
                    "model": "superagi-dev",
                    "message": "Hello"
                }
            )

            status, _headers, body = _request(app, "GET", "/api/chat/sessions/api-session-1")
            response = json.loads(body.decode("utf-8"))

            self.assertEqual(status, "200 OK")
            self.assertEqual(response["session_id"], "api-session-1")
            self.assertEqual([message["text"] for message in response["messages"]], ["Hello", "api reply"])

    def test_wsgi_api_returns_active_model_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_wsgi_app(
                f"{directory}/chat.sqlite3",
                model_runner=RecordingRunner("api reply")
            )

            status, _headers, body = _request(app, "GET", "/api/models/active")
            response = json.loads(body.decode("utf-8"))

            self.assertEqual(status, "200 OK")
            self.assertEqual(
                response,
                {
                    "model": "superagi-dev",
                    "runner": "recording",
                    "ready": True
                }
            )


class _Body:
    def __init__(self, body):
        self.body = body

    def read(self, _size=-1):
        return self.body


class RecordingRunner:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def generate(self, *, prompt, model):
        self.calls.append({"prompt": prompt, "model": model})
        return self.replies.pop(0)

    def describe(self):
        return {
            "model": "superagi-dev",
            "runner": "recording",
            "ready": True
        }


class FailingRunner:
    def generate(self, *, prompt, model):
        raise RuntimeError("checkpoint failed to load")

    def describe(self):
        return {
            "model": "superagi-dev",
            "runner": "failing",
            "ready": False
        }


def _post_json(app, path, payload):
    return _request(app, "POST", path, json.dumps(payload).encode("utf-8"))


def _request(app, method, path, payload=b""):
    response_status = []
    response_headers = []
    body = b"".join(
        app(
            {
                "REQUEST_METHOD": method,
                "PATH_INFO": path,
                "CONTENT_LENGTH": str(len(payload)),
                "wsgi.input": _Body(payload)
            },
            lambda status, headers: (
                response_status.append(status),
                response_headers.extend(headers)
            )
            and None
        )
    )
    return response_status[0], response_headers, body


if __name__ == "__main__":
    unittest.main()
