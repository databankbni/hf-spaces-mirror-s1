"""Small, dependency-free logging safeguards for credential-bearing HTTP logs."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit, urlunsplit


_BEARER_RE = re.compile(r"(\bBearer\s+)[^\s,;\"']+", re.IGNORECASE)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(\b(?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|bot[_-]?token|session(?:[_-]?string)?|"
    r"authorization)\b\s*[:=]\s*)[^\s,;&\"']+",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


class SecretRedactionFilter(logging.Filter):
    """Redact credentials from formatted log messages and exception traces."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            if record.exc_info:
                try:
                    traceback_text = logging.Formatter().formatException(record.exc_info)
                    message = f"{message}\n{traceback_text}"
                except Exception:
                    pass
                record.exc_info = None
            record.msg = sanitize_log_text(message)
            record.args = ()
            if record.stack_info:
                record.stack_info = sanitize_log_text(record.stack_info)
        except Exception:
            # Logging must never break application execution.
            pass
        return True


def safe_url_for_log(url: str) -> str:
    """Return a URL with userinfo, query, and fragment removed."""
    try:
        parts = urlsplit(str(url))
        if parts.scheme and parts.hostname:
            hostname = parts.hostname
            # IPv6 literals require brackets when reconstructed as a netloc.
            host = f"[{hostname}]" if ":" in hostname else hostname
            port = parts.port  # ValueError for an invalid port; handled below.
            if port is not None:
                host = f"{host}:{port}"
            return urlunsplit((parts.scheme, host, parts.path, "", ""))
    except Exception:
        pass
    return "[REDACTED_URL]"


def sanitize_log_text(text: object) -> str:
    """Remove credential-bearing URL, bearer, and assignment values from text."""
    value = str(text)
    value = _URL_RE.sub(lambda match: safe_url_for_log(match.group(0)), value)
    value = _BEARER_RE.sub(r"\1[REDACTED]", value)
    value = _SECRET_ASSIGNMENT_RE.sub(r"\1[REDACTED]", value)
    return value


def install_logging_safety() -> None:
    """Install defense-in-depth redaction and suppress verbose HTTP request logs."""
    redactor = SecretRedactionFilter()
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(redactor)

    # httpx/httpcore INFO request lines include complete URLs. Since Gemini puts
    # its key in the query string, do not emit those automatic request lines.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
