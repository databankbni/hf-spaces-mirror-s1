# logging_config.py

import logging
import sys
import os

def setup_logging():
    """
    Configures the root logger to use a clean, human-readable text format.
    Uses LOG_VERBOSE to toggle noisy third-party HTTP/network logs.
    """
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    # The toggle: if true, we keep the noisy logs. If false, we mute them.
    log_verbose = os.getenv("LOG_VERBOSE", "false").lower() == "true"

    # Clean, human-readable format
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(module)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    
    root_logger = logging.getLogger()
    
    # Avoid adding duplicate handlers
    if not root_logger.hasHandlers():
        root_logger.addHandler(handler)
        
    root_logger.setLevel(log_level)

    # --- THE TOGGLE LOGIC ---
    # If LOG_VERBOSE is false, mute the massive HTTP request/response dumps
    # by forcing third-party libraries to WARNING level.
    if not log_verbose:
        logging.getLogger("uvicorn").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("gunicorn").setLevel(logging.WARNING)
        logging.getLogger("gunicorn.access").setLevel(logging.WARNING)
        logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
        
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("openai").setLevel(logging.WARNING)
        logging.getLogger("openai._base_client").setLevel(logging.WARNING)
    
    logger = logging.getLogger(__name__)
    logger.info(
        f"Logging initialized in human-readable mode. "
        f"Level: {log_level_str} | Verbose Network Logs: {'ON' if log_verbose else 'OFF'}"
    )