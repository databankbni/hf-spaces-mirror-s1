# ---------------------------------------------------------------------------
# config.py — shared paths and constants for the Bhagwad Gita Reading Agent.
#
# Every module resolves paths relative to THIS file so the app works the
# same whether launched locally (`python app.py`) or on a Hugging Face
# Space (where the repo root is the working directory).
# ---------------------------------------------------------------------------

from pathlib import Path

# Repo root (this file lives at the root).
ROOT = Path(__file__).resolve().parent

# --- Data locations ---------------------------------------------------------
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "gita.sqlite"
# User profiles + bookmarks live in their OWN database, separate from the
# read-only verse corpus. This way a deploy (which re-uploads gita.sqlite)
# never overwrites real users' profiles and reading positions.
USERS_DB_PATH = DATA_DIR / "users.sqlite"
CHROMA_DIR = DATA_DIR / ".chroma"
AUDIO_DIR = DATA_DIR / "audio_cache"
AUDIO_SANSKRIT_DIR = AUDIO_DIR / "sanskrit"
AUDIO_ENGLISH_DIR = AUDIO_DIR / "english"
AUDIO_HINDI_DIR = AUDIO_DIR / "hindi"

# Public URL of the running app, embedded in calendar invites and reminders.
# On a Hugging Face Space set SPACE_URL; locally it defaults to localhost.
import os as _os

APP_URL = _os.environ.get("SPACE_URL", "http://localhost:7860")

# --- Source dataset ---------------------------------------------------------
HF_DATASET_ID = "OEvortex/Bhagavad_Gita"

# --- Durable user-data store (HF Dataset write-through) ---------------------
# HF free Spaces have an EPHEMERAL disk: anything written at runtime (profiles,
# bookmarks) is lost on restart/rebuild. To make user data survive, we mirror
# users.sqlite to a private HF *dataset* repo — pulled on startup, pushed after
# each meaningful change. Sync runs on the Space (SPACE_ID is set) or when a
# developer exports GITA_USERDATA_SYNC=1 locally.
USERDATA_REPO_ID = "kanika23oct/gita-userdata"
USERDATA_FILE = "users.sqlite"

# AI reflections are generated ONCE per (verse, language) by the LLM. They are
# stored in their own database and mirrored to the SAME durable dataset, so a
# reflection is never regenerated after a restart — saving tokens/credits.
REFLECTIONS_DB_PATH = DATA_DIR / "reflections.sqlite"
REFLECTIONS_FILE = "reflections.sqlite"

# --- Vector store -----------------------------------------------------------
COLLECTION_NAME = "gita_verses"
EMBED_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"

# --- Chat LLM (used ONLY by the optional "Ask the Sage" panel) --------------
# 8B is plenty for explaining the English translation of retrieved verses,
# and ~10x cheaper than 70B. Indic-tuned models are a v2 option.
CHAT_MODEL_ID = "meta-llama/Llama-3.1-8B-Instruct"

# --- Reading session defaults ----------------------------------------------
MIN_SESSION_MINUTES = 10
DEFAULT_SESSION_MINUTES = 10
MAX_SESSION_MINUTES = 60

# First verse of the book — the resume point for a brand-new user.
FIRST_VERSE_ID = "BG1.1"
