import asyncio
import logging
import os
import tempfile
import time
import json
import traceback
import re
import threading
import urllib.request


# ─── Keep-Alive: ping del espacio cada 10 min ────────────
_SPACE_URL = os.environ.get(
    "SPACE_URL",
    "https://siriocu-telegram-forwarder-es.hf.space",
)


def _keep_alive():
    log = logging.getLogger("keepalive")
    while True:
        time.sleep(600)
        try:
            urllib.request.urlopen(_SPACE_URL, timeout=10)
            log.info("Ping OK")
        except Exception as e:
            log.debug(f"Ping failed (expected): {e}")


t = threading.Thread(target=_keep_alive, daemon=True)
t.start()


# Catch unhandled async Task exceptions (e.g. Pyrogram internal peer resolution)
def _handle_asyncio_exc(loop, context):
    exc = context.get("exception")
    msg = context.get("message", "")
    if exc:
        logging.getLogger("asyncio").warning(
            f"Async task error: {type(exc).__name__}: {exc}"
        )
    else:
        logging.getLogger("asyncio").warning(f"Async event loop: {msg}")


asyncio.get_event_loop().set_exception_handler(_handle_asyncio_exc)

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified, FloodWait
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from pyrogram.enums import ParseMode, ChatType

from bot import (
    app,
    bot_app,
    user_app,
    monitored_chats,
    chat_rules,
    sudo_users,
    add_rule,
    remove_rule,
    rules_to_json,
    save_rules_to_disk,
    API_ID,
    API_HASH,
)

# Dual-mode selection:
#   cmd_app      – receives commands / callbacks from user (bot preferred)
#   monitor_app  – monitors channels & forwards messages (user preferred)
cmd_app = bot_app or user_app
monitor_app = user_app or bot_app

# Monkey-patch: catch errors in Pyrogram's internal update handler so a
# single bad peer doesn't crash the entire update-processing task.
import pyrogram.client as _pyro_client

_orig_handle_updates = _pyro_client.Client.handle_updates

async def _safe_handle_updates(self, updates):
    try:
        await _orig_handle_updates(self, updates)
    except Exception:
        logging.getLogger("pyrogram").warning(
            "Suppressed error in handle_updates (non-fatal)", exc_info=True
        )

_pyro_client.Client.handle_updates = _safe_handle_updates

logging.info("Bot starting... (with download-upload forward)")

CONFIG_CHANNEL = os.environ.get("CONFIG_CHANNEL_ID")

# ─── Chat name cache ──────────────────────────────────
chat_names = {}  # {chat_id: "title"}


def _get_chat_name(chat_id):
    if chat_id in chat_names:
        return chat_names[chat_id]
    chat = None
    try:
        if user_app:
            chat = user_app.get_chat(chat_id)
        elif bot_app:
            chat = bot_app.get_chat(chat_id)
    except Exception:
        pass
    if chat:
        name = chat.title or getattr(chat, "username", "") or ""
        if name:
            chat_names[chat_id] = name
            return name
    return f"`{chat_id}`"


def _formatted_rules():
    lines = ["**Reglas de reenvío:**"]
    for from_id, to_ids in chat_rules.items():
        src = _get_chat_name(from_id)
        dst = ", ".join(_get_chat_name(t) for t in to_ids)
        lines.append(f"📥 {src} → 📤 {dst}")
    if not chat_rules:
        lines.append("_No hay reglas configuradas_")
    return "\n".join(lines)

# ─── Conversation state for "add rule via forward" ──────
user_states = {}  # {user_id: {"step":"source"|"dest","source_id":int,"source_name":str,"expires":float}}


def _state(user_id):
    s = user_states.get(user_id)
    if s and s.get("expires", 0) > time.time():
        return s
    if s:
        user_states.pop(user_id, None)
    return None


def _clear_state(user_id):
    user_states.pop(user_id, None)


def _set_state(user_id, step, **kw):
    user_states[user_id] = {"step": step, "expires": time.time() + 300, **kw}


# ─── Helpers / keyboards ────────────────────────────────

def _is_sudo(user_id):
    return not sudo_users or int(user_id) in sudo_users


def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Ver reglas", callback_data="list")],
        [InlineKeyboardButton("➕ Nueva regla", callback_data="add")],
        [InlineKeyboardButton("❌ Quitar regla", callback_data="remove")],
        [InlineKeyboardButton("🗑 Borrar todo", callback_data="clear")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="help")],
    ])


# ─── Download-Upload Forward ────────────────────────────
# Always downloads media (bypasses "Restrict Saving Content")
# and sends via bot_app so the bot appears as author.


def _forward_media(reader, sender, message, to_id):
    """Download with reader, upload with sender — preserves all metadata."""
    original_name = None
    suffix = ".bin"

    if message.document:
        original_name = getattr(message.document, "file_name", None)
    elif message.video:
        original_name = getattr(message.video, "file_name", None)
    elif message.audio:
        original_name = getattr(message.audio, "file_name", None)
    elif message.photo:
        suffix = ".jpg"
    elif message.voice:
        suffix = ".ogg"
    elif message.animation:
        suffix = ".mp4"
    elif message.sticker:
        suffix = ".webp"
    elif message.video_note:
        suffix = ".mp4"

    if original_name:
        ext = os.path.splitext(original_name)[1]
        suffix = ext or suffix

    tmpdir = tempfile.mkdtemp()
    try:
        dl_path = os.path.join(tmpdir, original_name or f"file{suffix}")
        path = reader.download_media(message, file_name=dl_path)
        if not path:
            return False
        cap = message.caption.markdown if message.caption else ""

        if message.photo:
            sender.send_photo(to_id, path, caption=cap, parse_mode=ParseMode.MARKDOWN)
        elif message.video:
            v = message.video
            sender.send_video(
                to_id, path,
                caption=cap,
                parse_mode=ParseMode.MARKDOWN,
                duration=v.duration,
                width=v.width,
                height=v.height,
                file_name=original_name,
                supports_streaming=True,
            )
        elif message.audio:
            a = message.audio
            sender.send_audio(
                to_id, path,
                caption=cap,
                parse_mode=ParseMode.MARKDOWN,
                duration=a.duration,
                performer=a.performer,
                title=a.title,
                file_name=original_name,
            )
        elif message.voice:
            vc = message.voice
            sender.send_voice(to_id, path, duration=vc.duration)
        elif message.animation:
            an = message.animation
            sender.send_animation(
                to_id, path,
                caption=cap,
                parse_mode=ParseMode.MARKDOWN,
                duration=an.duration,
                width=an.width,
                height=an.height,
                file_name=original_name,
            )
        elif message.sticker:
            sender.send_sticker(to_id, path)
        elif message.video_note:
            vn = message.video_note
            sender.send_video_note(to_id, path, duration=vn.duration, length=vn.length)
        else:
            sender.send_document(
                to_id, path,
                caption=cap,
                parse_mode=ParseMode.MARKDOWN,
                file_name=original_name,
            )
        return True
    except Exception as e:
        logging.error(f"download-upload error: {e}")
        return False
    finally:
        try:
            for f in os.listdir(tmpdir):
                os.remove(os.path.join(tmpdir, f))
            os.rmdir(tmpdir)
        except Exception:
            pass


def _forward_native(client, message, to_id):
    """Try Telegram's native messages.forwardMessages — preserves original quality."""
    from pyrogram.raw.functions.messages import ForwardMessages
    try:
        from_peer = client.resolve_peer(message.chat.id)
        to_peer = client.resolve_peer(to_id)
        client.invoke(
            ForwardMessages(
                from_peer=from_peer,
                id=[message.id],
                to_peer=to_peer,
                drop_author=True,
            )
        )
        return True
    except Exception as e:
        logging.debug(f"Native forward failed: {e}")
        return False


def _do_forward(reader, sender, message, to_id):
    """Forward — native API first (preserves quality), fallback to download-upload."""
    if not message.document and not message.video:
        return

    if _forward_native(reader, message, to_id):
        return

    ok = _forward_media(reader, sender, message, to_id)
    if not ok:
        logging.warning(f"Forward failed for {message.chat.id} → {to_id}")


def forward_message(message, to_ids):
    reader = user_app or monitor_app
    sender = bot_app or monitor_app
    for to_id in to_ids:
        try:
            _do_forward(reader, sender, message, to_id)
        except Exception as e:
            logging.error(f"Error forwarding {message.chat.id} → {to_id}: {e}")


# ─── Auto-forward handler ───────────────────────────────

@monitor_app.on_message(filters.incoming, group=2)
def work(client: Client, message: Message):
    if message.outgoing:
        return
    if message.chat.id not in monitored_chats:
        return
    to_ids = chat_rules.get(message.chat.id)
    if not to_ids:
        return
    # Only forward documents (files) and videos
    if not message.document and not message.video:
        return
    forward_message(message, to_ids)


# ─── /start ─────────────────────────────────────────────

@cmd_app.on_message(filters.command(["start", "menu"]) & ~filters.channel, group=1)
def start_cmd(_: Client, message: Message):
    if not _is_sudo(message.from_user.id):
        return
    _clear_state(message.from_user.id)
    message.reply_text(_menu_text(), reply_markup=main_keyboard())


def _menu_text():
    active = len(chat_rules)
    dests = sum(len(v) for v in chat_rules.values())
    if bot_app and user_app:
        mode = "🤖 Bot + 👤 Cuenta"
    elif user_app:
        mode = "👤 Usuario"
    else:
        mode = "🤖 Bot"
    warn = ""
    if not user_app:
        warn = (
            "\n\n⚠️ **Sin SESSION_STRING** — no puedes leer canales a menos que seas admin.\n"
            "Configura SESSION_STRING desde la web:\n"
            "https://siriocu-telegram-forwarder-es.hf.space/setup"
        )
    return (
        f"**Bot Reenviador** — {mode}\n\n"
        f"📊 **{active} regla(s)** → **{dests} canal(es)** destino"
        f"{warn}"
    )


# ─── Conversation: Add rule via forward ────────────────

@cmd_app.on_message(filters.private & ~filters.service, group=3)
def handle_input(client: Client, message: Message):
    uid = message.from_user.id
    if not _is_sudo(uid):
        return
    if message.text and message.text.startswith("/"):
        return
    state = _state(uid)
    if not state:
        return

    step = state["step"]

    # ── Add-rule flow ─────────────────────────────────────
    chat_id = None
    chat_title = None

    # Extract chat info from forwarded message or direct text
    if message.forward_from_chat:
        chat_id = message.forward_from_chat.id
        chat_title = message.forward_from_chat.title
    elif message.forward_from:
        # User forward — not a channel
        message.reply_text("❌ Ese es un usuario, no un canal. Reenvía un mensaje de un **canal**.")
        return
    else:
        txt = message.text.strip() if message.text else ""
        if txt.startswith("-100") and txt.lstrip("-").isdigit():
            chat_id = int(txt)
            chat_title = txt
        elif txt.isdigit() and len(txt) > 5:
            chat_id = int(txt)
            chat_title = txt
        elif txt.isdigit() and not txt.startswith("0"):
            message.reply_text("❌ Ese no parece un ID de canal. Los IDs de canal empiezan con `-100`.\n\nReenvía un mensaje del canal o escribe el ID numérico.")
            return
        else:
            message.reply_text("❌ No entendí. Reenvía un mensaje del canal o escribe su ID numérico (ej: `-1001234567890`).")
            return

    if step == "source":
        _set_state(uid, "dest", source_id=chat_id, source_name=chat_title or str(chat_id))
        if chat_title:
            chat_names[chat_id] = chat_title
        names = chat_title or f"`{chat_id}`"
        message.reply_text(
            f"✅ Canal **origen**: {names}\n\nAhora **reinvía un mensaje** del canal **destino**\n(adonde quieres que lleguen los mensajes)\n\no escribe su ID numérico.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Cancelar", callback_data="back")],
            ]),
        )

    elif step == "dest":
        src = state["source_id"]
        src_name = state.get("source_name", str(src))
        dst_name = chat_title or f"`{chat_id}`"
        if chat_title:
            chat_names[chat_id] = chat_title
        try:
            add_rule(src, chat_id)
        except Exception as e:
            message.reply_text(f"❌ Error al crear regla: {e}")
            _clear_state(uid)
            return
        _clear_state(uid)
        _save_config_if_possible(message)
        message.reply_text(
            f"✅ **Regla creada**\n\n"
            f"📥 De: {src_name}\n"
            f"📤 Hacia: {dst_name}\n\n"
            f"Cuando alguien publique en el origen, se copiará automáticamente al destino.",
            reply_markup=main_keyboard(),
        )


# ─── /add (fallback for manual) ─────────────────────────

@cmd_app.on_message(filters.command(["add"]) & ~filters.channel, group=1)
def add_cmd(_: Client, message: Message):
    if not _is_sudo(message.from_user.id):
        return
    parts = message.command
    if len(parts) < 3:
        message.reply_text(
            "❌ **Faltan datos**\n\n"
            "Para añadir manualmente:\n"
            "`/add <ID_origen> <ID_destino>`\n\n"
            "**O mejor:** usa el botón **➕ Nueva regla** y reenvía mensajes.",
            reply_markup=main_keyboard(),
        )
        return
    from_id = parts[1]
    to_ids = parts[2:]
    try:
        add_rule(from_id, to_ids)
        dests = '`, `'.join(str(int(x)) for x in to_ids)
        message.reply_text(
            f"✅ **Regla añadida**\n📥 `{int(from_id)}` → 📤 `{dests}`",
            reply_markup=main_keyboard(),
        )
        _save_config_if_possible(message)
    except Exception as e:
        message.reply_text(f"❌ Error: {e}", reply_markup=main_keyboard())


# ─── /remove ────────────────────────────────────────────

@cmd_app.on_message(filters.command(["remove"]) & ~filters.channel, group=1)
def remove_cmd(_: Client, message: Message):
    if not _is_sudo(message.from_user.id):
        return
    parts = message.command
    if len(parts) < 2:
        message.reply_text(
            "❌ **Faltan datos**\n\n"
            "`/remove <ID_origen>` — quitar toda la regla\n"
            "`/remove <ID_origen> <ID_destino>` — quitar solo ese destino\n\n"
            "**O mejor:** usa el botón **❌ Quitar regla**.",
            reply_markup=main_keyboard(),
        )
        return
    from_id = parts[1]
    to_id = parts[2] if len(parts) > 2 else None
    try:
        remove_rule(from_id, to_id)
        msg = f"✅ Eliminado `{int(from_id)}`"
        if to_id:
            msg += f" → `{int(to_id)}`"
        message.reply_text(msg, reply_markup=main_keyboard())
        _save_config_if_possible(message)
    except Exception as e:
        message.reply_text(f"❌ Error: {e}", reply_markup=main_keyboard())


# ─── /list ──────────────────────────────────────────────

@cmd_app.on_message(filters.command(["list"]) & ~filters.channel, group=1)
def list_cmd(_: Client, message: Message):
    if not _is_sudo(message.from_user.id):
        return
    message.reply_text(_formatted_rules(), reply_markup=main_keyboard())


# ─── /clear ─────────────────────────────────────────────

@cmd_app.on_message(filters.command(["clear"]) & ~filters.channel, group=1)
def clear_cmd(_: Client, message: Message):
    if not _is_sudo(message.from_user.id):
        return
    chat_rules.clear()
    monitored_chats.clear()
    save_rules_to_disk()
    message.reply_text("✅ **Todas las reglas eliminadas**", reply_markup=main_keyboard())


# ─── /fwd ───────────────────────────────────────────────

@cmd_app.on_message(filters.command(["fwd", "forward"]) & ~filters.channel, group=1)
def forward_cmd(client: Client, message: Message):
    if not _is_sudo(message.from_user.id):
        return
    parts = list(message.command)
    args = [x.strip() for x in " ".join(parts[1:]).split()]
    if len(args) < 2 or not args[1].lstrip("-").isdigit():
        message.reply_text(
            "❌ **Uso:** `/fwd <ID_canal> <cantidad>`\n"
            "Ej: `/fwd -1001234567890 50`\n\n"
            "Reenvía mensajes antiguos de un canal.",
            reply_markup=main_keyboard(),
        )
        return
    chat_id = int(args[0])
    limit = int(args[1])
    offset = int(args[2]) if len(args) > 2 else 0
    status = message.reply_text(f"⏳ Reenviando {limit} mensajes...")
    reader_fwd = user_app or client
    sender_fwd = bot_app or client
    count = 0
    for msg in reader_fwd.get_chat_history(chat_id, limit=limit, offset_id=offset):
        try:
            _do_forward(reader_fwd, sender_fwd, msg, message.chat.id)
            count += 1
        except Exception:
            pass
    try:
        status.edit_text(f"✅ {count} mensajes reenviados")
    except Exception:
        pass


# ─── /setup ─────────────────────────────────────────────

@cmd_app.on_message(filters.command(["setup"]) & ~filters.channel, group=1)
def setup_cmd(_: Client, message: Message):
    if not _is_sudo(message.from_user.id):
        return
    message.reply_text(
        "🌐 **Obtén tu SESSION_STRING desde el navegador**\n\n"
        "Abre esta URL en tu navegador:\n"
        "https://siriocu-telegram-forwarder-es.hf.space/setup\n\n"
        "Es más fácil y evita bloqueos de seguridad de Telegram."
    )


@cmd_app.on_message(filters.command(["test"]) & ~filters.channel, group=1)
def test_cmd(_: Client, message: Message):
    if not _is_sudo(message.from_user.id):
        return
    message.reply_text("ℹ️ DEBUG: /test handler works!")

@cmd_app.on_message(filters.command(["ping"]) & ~filters.channel, group=1)
def ping_cmd(_: Client, message: Message):
    if not _is_sudo(message.from_user.id):
        return
    message.reply_text("pong")


# ─── /help ──────────────────────────────────────────────

@cmd_app.on_message(filters.command(["help"]) & ~filters.channel, group=1)
def help_cmd(_: Client, message: Message):
    if not _is_sudo(message.from_user.id):
        return
    message.reply_text(_help_text(), reply_markup=main_keyboard())


# ─── Help text ──────────────────────────────────────────

def _help_text():
    return (
        "**❓ Cómo usar este bot**\n\n"
        "Este bot reenvía mensajes automáticamente de un canal a otro.\n\n"
        "**1. Únete al canal ORIGEN** como miembro normal.\n"
        "**2. Añade al bot** como **admin** del canal DESTINO.\n"
        "**3. Presiona ➕ Nueva regla** y reenvía un mensaje de cada canal.\n"
        "**4. ¡Listo!** Los mensajes nuevos se copiarán solos.\n\n"
        "**Importante:**\n"
        "• El bot funciona con **tu cuenta de Telegram** (userbot)\n"
        "• Puede reenviar desde canales con restricción de copia\n"
        "• No necesitas ser admin del canal ORIGEN\n"
        "• El bot usa cron-job.org para mantenerse despierto\n\n"
        "**Comandos disponibles:**\n"
        "/start — Menú principal\n"
        "/setup — Generar SESSION_STRING para tu cuenta\n"
        "/add -100xxx -100yyy — Regla manual\n"
        "/remove -100xxx — Quitar regla\n"
        "/list — Ver reglas\n"
        "/fwd -100xxx 50 — Reenviar mensajes antiguos"
    )


# ─── Callback handler ───────────────────────────────────

@cmd_app.on_callback_query(filters.create(lambda _, __, q: _is_sudo(q.from_user.id)))
def handle_callback(client: Client, cb: CallbackQuery):
    data = cb.data

    if data == "back":
        _clear_state(cb.from_user.id)
        cb.edit_message_text(_menu_text(), reply_markup=main_keyboard())
        cb.answer()
        return

    # ── Add ──
    if data == "add":
        _set_state(cb.from_user.id, "source")
        cb.edit_message_text(
            "**➕ Nueva regla — Paso 1**\n\n"
            "**Reenvíame cualquier mensaje** del canal **ORIGEN**\n"
            "(del que quieres copiar los mensajes)\n\n"
            "Si el canal tiene restricción de reenvío,\n"
            "escribe su ID numérico (ej: `-1001234567890`).\n\n"
            "Puedes obtener el ID añadiendo @userinfobot al canal.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Cancelar", callback_data="back")],
            ]),
        )
        cb.answer()
        return

    # ── List ──
    if data == "list":
        text = _formatted_rules()
        cb.edit_message_text(text, reply_markup=main_keyboard())
        cb.answer()
        return

    # ── Remove selection ──
    if data == "remove":
        if not chat_rules:
            cb.answer("No hay reglas para quitar", show_alert=True)
            return
        buttons = []
        for from_id in list(chat_rules.keys()):
            to_ids = chat_rules[from_id]
            # Try to get a friendly name
            buttons.append([InlineKeyboardButton(
                f"📥 {from_id}  →  {len(to_ids)} destino(s)",
                callback_data=f"del_{from_id}",
            )])
        buttons.append([InlineKeyboardButton("🔙 Volver", callback_data="back")])
        cb.edit_message_text("**❌ ¿Qué regla quieres eliminar?**", reply_markup=InlineKeyboardMarkup(buttons))
        cb.answer()
        return

    if data.startswith("del_"):
        from_id = int(data.split("_", 1)[1])
        remove_rule(from_id)
        _save_config_if_possible(cb.message)
        cb.edit_message_text(f"✅ Regla `{from_id}` eliminada", reply_markup=main_keyboard())
        cb.answer()
        return

    # ── Clear ──
    if data == "clear":
        if not chat_rules:
            cb.answer("No hay reglas", show_alert=True)
            return
        cb.edit_message_text(
            "**⚠️ ¿Eliminar todas las reglas?**",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Sí, borrar todo", callback_data="clear_confirm")],
                [InlineKeyboardButton("🔙 No", callback_data="back")],
            ]),
        )
        cb.answer()
        return

    if data == "clear_confirm":
        chat_rules.clear()
        monitored_chats.clear()
        save_rules_to_disk()
        _save_config_if_possible(cb.message)
        cb.edit_message_text("✅ **Todas las reglas eliminadas**", reply_markup=main_keyboard())
        cb.answer()
        return

    # ── Help ──
    if data == "help":
        try:
            cb.edit_message_text(_help_text(), reply_markup=main_keyboard())
        except MessageNotModified:
            pass
        cb.answer()
        return

    cb.answer()


# ─── Persistence helpers ────────────────────────────────

def _save_config_if_possible(msg_or_cb):
    if not CONFIG_CHANNEL:
        return
    cfg_client = bot_app or user_app or app
    try:
        data = rules_to_json()
        msg_id = int(os.environ.get("CONFIG_MSG_ID", "0"))
        if msg_id:
            try:
                cfg_client.delete_messages(int(CONFIG_CHANNEL), msg_id)
            except Exception:
                pass
        sent = cfg_client.send_message(int(CONFIG_CHANNEL), f"`{data}`")
        os.environ["CONFIG_MSG_ID"] = str(sent.id)
    except Exception:
        pass


from pyrogram import idle

# Keep trying to start until FloodWait expires
clients = set()
if bot_app:
    clients.add(bot_app)
if user_app and user_app is not bot_app:
    clients.add(user_app)

for c in clients:
    while True:
        try:
            c.start()
            break
        except FloodWait as exc:
            m = re.search(r"wait of (\d+) seconds", str(exc))
            wait = int(m.group(1)) if m else 60
            logging.warning(f"FloodWait: esperando {wait}s...")
            time.sleep(wait)

idle()
