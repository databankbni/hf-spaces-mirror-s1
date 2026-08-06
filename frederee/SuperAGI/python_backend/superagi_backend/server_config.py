import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[1] / "data" / "chat.sqlite3"


@dataclass(frozen=True)
class ServerSettings:
    host: str
    port: int
    database_path: Path


def get_server_settings(*, default_host="127.0.0.1", default_port=5001):
    return ServerSettings(
        host=os.environ.get("SUPERAGI_HOST", default_host),
        port=_read_port(default_port),
        database_path=Path(os.environ.get("SUPERAGI_CHAT_DB", str(DEFAULT_DATABASE_PATH)))
    )


def _read_port(default_port):
    port = os.environ.get("SUPERAGI_PORT") or os.environ.get("PORT") or str(default_port)
    return int(port)
