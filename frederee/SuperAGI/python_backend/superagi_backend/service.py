import uuid

from .runner import DEFAULT_MODEL, PlaceholderModelRunner, build_prompt
from .storage import create_chat_repository_from_env


class ChatService:
    def __init__(self, database_path, model_runner=None, repository=None):
        self.model_runner = model_runner or PlaceholderModelRunner()
        self.repository = repository or create_chat_repository_from_env(database_path)

    def handle_chat(self, payload):
        if not isinstance(payload, dict):
            raise ChatValidationError("request body must be a JSON object")

        session_id = _clean_string(payload.get("session_id")) or str(uuid.uuid4())
        model = _clean_string(payload.get("model")) or DEFAULT_MODEL
        if not self._supports_model(model):
            raise ChatValidationError(
                f"model must be one of: {', '.join(self.model_runner.supported_models())}"
            )

        user_text = _clean_string(payload.get("message"))
        if not user_text:
            raise ChatValidationError("message must be a non-empty string")

        context_messages = self._get_context_messages(session_id, payload)
        next_messages_without_reply = [
            *context_messages,
            {
                "role": "visitor",
                "text": user_text
            }
        ]
        prompt = build_prompt(next_messages_without_reply)
        assistant_message = {
            "role": "assistant",
            "text": self.model_runner.generate(
                prompt=prompt,
                model=model
            )
        }
        next_messages = [
            *next_messages_without_reply,
            assistant_message
        ]

        self.repository.replace_session_messages(session_id, model, next_messages)
        self.repository.append_training_example(
            session_id=session_id,
            model=model,
            user_text=user_text,
            assistant_text=assistant_message["text"],
            prompt=prompt,
            context_messages=next_messages_without_reply
        )

        return {
            "session_id": session_id,
            "model": model,
            "message": assistant_message,
            "messages": next_messages
        }

    def get_session(self, session_id):
        session_id = _clean_string(session_id)
        if not session_id:
            raise ChatValidationError("session_id must be a non-empty string")

        return self.repository.get_session(session_id)

    def describe_active_model(self):
        return self.model_runner.describe()

    def _get_context_messages(self, session_id, payload):
        supplied_messages = payload.get("messages")
        if isinstance(supplied_messages, list) and supplied_messages:
            return [_normalize_message(message) for message in supplied_messages]

        session = self.get_session(session_id)
        if session is not None:
            return session["messages"]

        if isinstance(supplied_messages, list):
            return []

        return []

    def _supports_model(self, model):
        supports = getattr(self.model_runner, "supports", None)
        if supports is None:
            return True
        return supports(model)

class ChatValidationError(ValueError):
    pass


def _normalize_message(message):
    if not isinstance(message, dict):
        raise ChatValidationError("messages must contain JSON objects")

    role = _clean_string(message.get("role"))
    text = _clean_string(message.get("text") or message.get("content"))

    if role == "user":
        role = "visitor"

    if role not in {"assistant", "visitor"}:
        raise ChatValidationError("message roles must be assistant, visitor, or user")

    if not text:
        raise ChatValidationError("message text must be non-empty")

    return {
        "role": role,
        "text": text
    }


def _clean_string(value):
    if not isinstance(value, str):
        return ""
    return value.strip()
