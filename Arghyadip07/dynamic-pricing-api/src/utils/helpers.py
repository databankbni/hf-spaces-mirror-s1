import os
import datetime
import uuid
from typing import Any, List

def get_project_root() -> str:
    """
    Returns the absolute path to the project root directory.
    """
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def ensure_dir(path: str):
    """
    Ensures that a directory exists, creating it if necessary.
    """
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)

def get_timestamp() -> str:
    """
    Returns a current timestamp string for filenames.
    """
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

def generate_id() -> str:
    """
    Generates a unique short ID.
    """
    return str(uuid.uuid4())[:8]

def chunk_list(data: List[Any], size: int):
    """
    Splits a list into chunks of a specific size.
    """
    for i in range(0, len(data), size):
        yield data[i:i + size]

def format_currency(value: float, currency_symbol: str = "$") -> str:
    """
    Formats a numeric value as a currency string.
    """
    return f"{currency_symbol}{value:,.2f}"
