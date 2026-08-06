import json
from pathlib import Path

from .service import ChatService, ChatValidationError
from .runner import create_model_runner_from_env


DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[1] / "data" / "chat.sqlite3"
MAX_BODY_BYTES = 2 * 1024 * 1024


def create_wsgi_app(database_path=DEFAULT_DATABASE_PATH, model_runner=None):
    service = ChatService(database_path, model_runner=model_runner or create_model_runner_from_env())

    def app(environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")

        if method == "OPTIONS":
            return _json_response(start_response, "204 No Content", None)

        if method == "GET" and path == "/":
            return _json_response(
                start_response,
                "200 OK",
                {
                    "name": "SuperAGI Chat API",
                    "endpoints": [
                        "/health",
                        "/api/models/active",
                        "/api/chat",
                        "/api/chat/sessions/<session_id>"
                    ]
                }
            )

        if method == "GET" and path == "/health":
            return _json_response(start_response, "200 OK", {"ok": True})

        if method == "GET" and path == "/api/models/active":
            return _json_response(start_response, "200 OK", service.describe_active_model())

        if method == "GET" and path.startswith("/api/chat/sessions/"):
            session_id = path.removeprefix("/api/chat/sessions/")
            session = service.get_session(session_id)
            if session is None:
                return _json_response(
                    start_response,
                    "404 Not Found",
                    {
                        "error": "session_not_found"
                    }
                )
            return _json_response(start_response, "200 OK", session)

        if method == "POST" and path == "/api/chat":
            try:
                payload = _read_json_body(environ)
                response = service.handle_chat(payload)
            except ChatValidationError as error:
                return _json_response(
                    start_response,
                    "422 Unprocessable Entity",
                    {
                        "error": "invalid_request",
                        "message": str(error)
                    }
                )
            except json.JSONDecodeError:
                return _json_response(
                    start_response,
                    "400 Bad Request",
                    {
                        "error": "invalid_json",
                        "message": "request body must be valid JSON"
                    }
                )
            except RuntimeError as error:
                return _json_response(
                    start_response,
                    "503 Service Unavailable",
                    {
                        "error": "model_unavailable",
                        "message": str(error)
                    }
                )

            return _json_response(start_response, "200 OK", response)

        return _json_response(
            start_response,
            "404 Not Found",
            {
                "error": "not_found"
            }
        )

    return app


def _read_json_body(environ):
    content_length = int(environ.get("CONTENT_LENGTH") or "0")
    if content_length > MAX_BODY_BYTES:
        raise ChatValidationError("request body is too large")

    body = environ["wsgi.input"].read(content_length)
    return json.loads(body.decode("utf-8") or "{}")


def _json_response(start_response, status, body):
    headers = [
        ("Access-Control-Allow-Headers", "Content-Type"),
        ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
        ("Access-Control-Allow-Origin", "*"),
        ("Content-Type", "application/json; charset=utf-8")
    ]
    start_response(status, headers)
    if body is None:
        return [b""]
    return [f"{json.dumps(body)}\n".encode("utf-8")]
