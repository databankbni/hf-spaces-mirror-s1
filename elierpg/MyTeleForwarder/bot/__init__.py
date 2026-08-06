import json
import logging
import os
import sys
from os import environ
import toml

from pyrogram import Client
from .helper.validator import validate_config
from jsonschema import ValidationError
from .helper.utils import parse_chats

log_level = environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format="[%(levelname)s]\t%(message)s",
    handlers=[logging.FileHandler("log.txt"), logging.StreamHandler()],
    level=log_level,
)
logging.getLogger("pyrogram").setLevel(logging.ERROR)

# ─── Credentials (override via env vars API_ID / API_HASH) ──
HARD_API_ID = int(environ.get("API_ID", 6426614))
HARD_API_HASH = environ.get("API_HASH", "056b8c463e160604f53a38bfe65d0d0e")
if environ.get("API_ID") or environ.get("API_HASH"):
    logging.info(f"Using API_ID/HASH from environment")
else:
    logging.info(f"Using hardcoded API_ID/HASH (set API_ID/API_HASH env vars to override)")

config = None
if os.path.exists("config.toml"):
    config = toml.load("config.toml")
    logging.info(f"Loaded config.toml")
elif os.environ.get("CONFIG"):
    config = toml.loads(environ["CONFIG"])
    logging.info(f"Loaded config from environment variable")
elif os.environ.get("BOT_TOKEN") or os.environ.get("SESSION_STRING"):
    config = {
        "pyrogram": {
            "api_id": HARD_API_ID,
            "api_hash": HARD_API_HASH,
        },
        "chats": json.loads(environ.get("CHATS", "[]")),
    }
    if environ.get("BOT_TOKEN"):
        config["pyrogram"]["bot_token"] = environ["BOT_TOKEN"]
    if environ.get("SESSION_STRING"):
        config["pyrogram"]["session_string"] = environ["SESSION_STRING"]
    logging.info(f"Loaded config from individual environment variables")
else:
    logging.error(f"No configuration found. Set BOT_TOKEN or SESSION_STRING in Secrets. Exiting...")
    sys.exit(1)

try:
    validate_config(config)
except ValidationError as error:
    logging.error(f"Invalid config: {error.message}")
    logging.info(f"Please read the documentation carefully and configure the bot properly.")
    sys.exit(1)

logging.info(f"Initalizing bot...")

# Export for use in __main__.py
API_ID = config["pyrogram"]["api_id"]
API_HASH = config["pyrogram"]["api_hash"]

# ─── Dynamic config ──────────────────────────────────

sudo_users = [568336569]  # Solo tu ID — no se puede cambiar por env var
chat_rules = {}
monitored_chats = set()
RULES_FILE = "rules.json"


def rebuild_monitored():
    global monitored_chats
    new_set = set(chat_rules.keys())
    monitored_chats.clear()
    monitored_chats.update(new_set)


def _save_rules_to_disk():
    try:
        with open(RULES_FILE, "w") as f:
            json.dump(chat_rules, f, indent=2)
    except Exception as e:
        logging.warning(f"Could not save rules to disk: {e}")


def _load_rules_from_disk():
    try:
        with open(RULES_FILE) as f:
            data = json.load(f)
        chat_rules.clear()
        chat_rules.update({int(k): v for k, v in data.items()})
        rebuild_monitored()
        logging.info(f"Loaded {len(chat_rules)} rules from disk")
    except FileNotFoundError:
        pass
    except Exception as e:
        logging.warning(f"Could not load rules from disk: {e}")


def add_rule(from_id, to_ids):
    if isinstance(to_ids, (int, str)):
        to_ids = [int(to_ids)]
    else:
        to_ids = [int(x) for x in to_ids]
    from_id = int(from_id)
    if from_id in chat_rules:
        existing = set(chat_rules[from_id])
        existing.update(to_ids)
        chat_rules[from_id] = list(existing)
    else:
        chat_rules[from_id] = to_ids
    rebuild_monitored()
    _save_rules_to_disk()


def remove_rule(from_id, to_id=None):
    from_id = int(from_id)
    if to_id is None:
        chat_rules.pop(from_id, None)
    else:
        to_id = int(to_id)
        if from_id in chat_rules:
            chat_rules[from_id] = [x for x in chat_rules[from_id] if x != to_id]
            if not chat_rules[from_id]:
                del chat_rules[from_id]
    rebuild_monitored()
    _save_rules_to_disk()


def save_rules_to_disk():
    _save_rules_to_disk()


def list_rules():
    lines = ["**Reglas de reenvío:**"]
    for from_id, to_ids in chat_rules.items():
        lines.append(f"📥 `{from_id}` → 📤 `{', '.join(str(x) for x in to_ids)}`")
    if not chat_rules:
        lines.append("_No hay reglas configuradas_")
    return "\n".join(lines)


def rules_to_json():
    return json.dumps([{"from": k, "to": v if len(v) > 1 else v[0]} for k, v in chat_rules.items()], indent=2)


# Load initial rules from config
for chat_cfg in config.get("chats", []):
    from_ids = chat_cfg["from"]
    to_ids = chat_cfg["to"]
    if not isinstance(from_ids, list):
        from_ids = [from_ids]
    if not isinstance(to_ids, list):
        to_ids = [to_ids]
    for fid in from_ids:
        add_rule(int(fid), [int(t) for t in to_ids])

# Override with saved rules (survives restarts, not rebuilds)
_load_rules_from_disk()

logging.info(f"Monitored chats: {', '.join(str(x) for x in sorted(monitored_chats))}")
logging.info(f"Chat rules: {chat_rules}")

# ─── Dual-mode clients ─────────────────────────────────────
# bot_app  = interacts with user (commands, menus, buttons)
# user_app = reads channels + forwards messages (via SESSION_STRING)
bot_app = None
user_app = None

has_bot_token = bool(config["pyrogram"].get("bot_token"))
has_session = bool(config["pyrogram"].get("session_string"))

if has_bot_token:
    bot_app = Client(
        "bot",
        api_id=config["pyrogram"]["api_id"],
        api_hash=config["pyrogram"]["api_hash"],
        bot_token=config["pyrogram"]["bot_token"],
    )
if has_session:
    user_app = Client(
        "user",
        api_id=config["pyrogram"]["api_id"],
        api_hash=config["pyrogram"]["api_hash"],
        session_string=config["pyrogram"]["session_string"],
    )

if has_bot_token and has_session:
    logging.info("DUAL MODE: bot_app (commands) + user_app (channel access)")
elif has_bot_token:
    logging.info("BOT-ONLY mode (cannot read channels unless admin of source)")
elif has_session:
    logging.info("USER-ONLY mode (can read any channel you have access to)")

# Backwards-compat alias
app = bot_app or user_app
