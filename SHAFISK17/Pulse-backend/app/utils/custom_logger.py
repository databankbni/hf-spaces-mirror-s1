"""
backend/app/utils/custom_logger.py
────────────────────────────────────────────────────────────────────────────────
Phase 23: The Log UI/UX Upgrade — Custom ANSI-Colored Logger

Why this file exists:
    When an async pipeline runs, log lines from 22 categories interleave
    and become a wall of unreadable text. This formatter gives every line a
    strict visual structure — like a table — so the human eye can scan it
    instantly without any external tool.

What it produces (each log line looks like this):
    2026-03-04 13:45:00 | INFO     | [💾 DB      ] | [ai] Saved 7 articles.
    2026-03-04 13:45:00 | ERROR    | [🛑 ERROR   ] | Appwrite returned HTTP 429.

Design rules:
    1. Aligned columns — timestamp | level | tag | message form perfect verticals.
    2. LEVEL is padded to 8 characters (INFO    , WARNING , ERROR   ).
    3. TAG is padded to 12 characters so the message column starts at the same offset.
    4. Color is applied per level — INFO green, WARNING yellow, ERROR red.
    5. Uses ONLY the built-in logging module + ANSI codes — zero new dependencies.

Usage:
    from app.utils.custom_logger import get_logger
    logger = get_logger(__name__)
    logger.info("[📡 NET     ] [ai] Fetched 12 articles from GNews.")
"""

import logging
import sys
from datetime import datetime

# ── ANSI Escape Codes ────────────────────────────────────────────────────────
# These are simple text codes that the terminal interprets as colors.
# They work on every Linux/macOS terminal and on Windows 10+ terminals.
# On older Windows terminals they show as plain text — no harm done.
#
# RESET must be placed at the end of every colored string so the next line
# does not accidentally inherit the previous line's color.

RESET   = '\033[0m'
BOLD    = '\033[1m'
DIM     = '\033[2m'

# Text colors
GREEN   = '\033[92m'   # INFO  — calm and healthy
YELLOW  = '\033[93m'   # WARNING — attention needed
RED     = '\033[91m'   # ERROR — stop and look
CYAN    = '\033[96m'   # Timestamp — neutral, cold
WHITE   = '\033[97m'   # Level label
MAGENTA = '\033[95m'   # Tag bracket


# ── Visual Tags (pre-padded to 12 chars so the message column aligns) ────────
# Rules for tag padding:
#   - The total visible width of the text inside the brackets must be 10 chars.
#   - Emoji counts as 2 chars on most terminals, so a 1-emoji tag needs 8 spaces.
#   - Use spaces to pad shorter labels out to 10 visible characters.
#
# You can use these constants when building your log messages:
TAG_START   = "[🚀 START   ]"   # Pipeline job begins
TAG_DONE    = "[🚀 DONE    ]"   # Pipeline job ends
TAG_NET     = "[📡 NET     ]"   # External API call / provider fetch
TAG_GATE    = "[🛡️ GATE    ]"   # Regex validation, freshness check, dedup
TAG_ENRICH  = "[✨ ENRICH  ]"   # Image enrichment
TAG_DB      = "[💾 DB      ]"   # Appwrite save or Redis read/write
TAG_REDIS   = "[🔑 REDIS   ]"   # Redis-specific operations
TAG_ERROR   = "[🛑 ERROR   ]"   # Any caught exception or failure


# ── Color map per log level ────────────────────────────────────────────────────
_LEVEL_COLORS = {
    "DEBUG":    DIM + WHITE,
    "INFO":     GREEN,
    "WARNING":  YELLOW,
    "ERROR":    RED,
    "CRITICAL": BOLD + RED,
}

_LEVEL_LABELS = {
    "DEBUG":    "DEBUG   ",
    "INFO":     "INFO    ",
    "WARNING":  "WARNING ",
    "ERROR":    "ERROR   ",
    "CRITICAL": "CRITICAL",
}


class AlignedColorFormatter(logging.Formatter):
    """
    Custom log formatter that produces perfectly aligned, ANSI-colored output.

    Output format (one line per log call):
        YYYY-MM-DD HH:MM:SS | LEVEL    | [TAG...    ] | Message text here
        ───────────────────   ────────   ────────────   ──────────────────
        Column 1 (19 chars)  Col 2(8)  Col 3 (14ch)   Col 4 (free text)

    The vertical bars | act as column separators — like a spreadsheet grid
    drawn in ASCII. This makes it trivial to scan an async log and follow
    a single category's execution path down the left-most column.
    """

    def format(self, record: logging.LogRecord) -> str:
        # ── Column 1: Timestamp ───────────────────────────────────────────────
        ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        col_ts = f"{CYAN}{ts}{RESET}"

        # ── Column 2: Level label (padded to 8 chars) ─────────────────────────
        level_name  = record.levelname
        level_color = _LEVEL_COLORS.get(level_name, WHITE)
        level_label = _LEVEL_LABELS.get(level_name, level_name.ljust(8))
        col_level   = f"{level_color}{level_label}{RESET}"

        # ── Column 3: Logger name (module) padded to 30 chars ─────────────────
        # We use the logger name (e.g. "app.services.scheduler") instead of a
        # fixed tag. The tag is embedded IN the message itself by the caller
        # (e.g., "[📡 NET     ]"). This is more flexible — different parts of
        # the code declare their own tags, and the formatter just makes sure
        # they all land in the same horizontal column.
        module = record.name
        if len(module) > 30:
            # Trim from the left: "app.services.providers.gnews.client" → "..ers.gnews.client"
            module = ".." + module[-28:]
        col_module = f"{DIM}{WHITE}{module:<30}{RESET}"

        # ── Column 4: The actual log message ──────────────────────────────────
        msg = record.getMessage()

        # If there is an exception attached, append it after the message.
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            msg = f"{msg}\n{RED}{exc_text}{RESET}"

        # ── Assemble the full line ─────────────────────────────────────────────
        return f"{col_ts} | {col_level} | {col_module} | {msg}"


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger that flows into the root logger configured in main.py.

    How to use this in any module:
        from app.utils.custom_logger import get_logger
        logger = get_logger(__name__)

    Why we use propagate=True here (and NOT add our own handler):
        Uvicorn calls logging.config.dictConfig() at startup, which can
        silently orphan any handlers we attach to individual module loggers.
        Instead, we configure ONE root handler in main.py (before uvicorn
        starts), and let every module logger propagate its messages up to it.
        This is the standard production pattern for FastAPI + uvicorn.

    Why we do NOT call addHandler() here:
        If a module logger has its own handler AND propagate=True, every
        log call would print TWICE — once from the module handler and once
        from the root handler. No handlers here = no duplicates.

    Args:
        name: Normally pass __name__ (the module's full dotted path).

    Returns:
        A configured Logger instance ready to use.
    """
    log = logging.getLogger(name)

    # Set to DEBUG so all levels pass through to the root logger.
    # The root logger's level and handler decide what is actually printed.
    log.setLevel(logging.DEBUG)

    # Propagate to root: root handler (set up in main.py) does the printing.
    # DO NOT add a handler here — that would cause duplicate log lines.
    log.propagate = True

    return log
