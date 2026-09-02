import logging
from pathlib import Path

# Configure root logger for the backend
LOG_LEVEL = logging.INFO
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)

# Optional file logging for debug (disabled by default)
log_file = Path("debug_logs/backend.log")
try:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    # Example: enable file handler if needed by uncommenting next lines
    # fh = logging.FileHandler(log_file)
    # fh.setLevel(LOG_LEVEL)
    # fh.setFormatter(logging.Formatter(LOG_FORMAT))
    # logging.getLogger().addHandler(fh)
    pass
except Exception:
    pass

logger = logging.getLogger("webtruyen")
