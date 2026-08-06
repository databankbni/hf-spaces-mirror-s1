"""
Telegram Bot + Gradio Dashboard
Receives files via Telegram, uploads to HF Storage Bucket, displays live log in Gradio UI.
"""

import os
import threading
import logging
import asyncio
from datetime import datetime, timezone
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import gradio as gr
from huggingface_hub import HfApi
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
HF_TOKEN       = os.environ.get("HF_TOKEN", "")
HF_BUCKET_ID   = os.environ.get("HF_BUCKET_ID", "Krixter/Solo")
HF_BUCKET_URL  = f"https://huggingface.co/datasets/{HF_BUCKET_ID}"

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("BotUploader")

# Thread-pool for blocking HF upload calls (keeps the bot event-loop free)
_executor = ThreadPoolExecutor(max_workers=4)

# ---------------------------------------------------------------------------
# Shared in-memory log (thread-safe ring-buffer)
# ---------------------------------------------------------------------------

_log: deque = deque(maxlen=200)
_log_lock = threading.Lock()


def _add_log(filename: str, size_kb: float, user: str, status: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    with _log_lock:
        _log.appendleft([ts, filename, f"{size_kb:.1f} KB", user, status])


def _read_log() -> list:
    with _log_lock:
        return list(_log)


# ---------------------------------------------------------------------------
# Hugging Face upload — runs in executor thread, NOT in the async event loop
# ---------------------------------------------------------------------------

def _blocking_upload(file_bytes: bytes, remote_path: str) -> None:
    """
    Upload raw bytes to the HF Storage Bucket.

    Signature: batch_bucket_files(bucket_id, *, add: list[tuple[bytes|str|Path, str]])
    Each tuple is (source, destination_path_in_bucket).
    """
    api = HfApi(token=HF_TOKEN)
    api.batch_bucket_files(
        HF_BUCKET_ID,
        add=[(file_bytes, remote_path)],
    )
    logger.info("HF upload complete → %s", remote_path)


# ---------------------------------------------------------------------------
# Telegram bot handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[
        InlineKeyboardButton("📖 How to use", callback_data="help"),
        InlineKeyboardButton("🗄️ View Bucket", url=HF_BUCKET_URL),
    ]]
    await update.message.reply_text(
        text=(
            "👋 *Welcome to File Uploader Bot!*\n\n"
            "Send me any *document*, *photo*, or *video* and I'll upload it "
            f"straight to the Hugging Face bucket `{HF_BUCKET_ID}`.\n\n"
            "Use the buttons below to learn more or inspect the bucket."
        ),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _handle_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    file_id: str,
    filename: str,
) -> None:
    user       = update.effective_user
    user_label = f"@{user.username}" if user.username else str(user.id)
    loop       = asyncio.get_event_loop()

    # Send initial status message that we'll keep editing
    status_msg = await update.message.reply_text(
        f"📥 *Downloading* `{filename}` …",
        parse_mode="Markdown",
    )

    try:
        # ── 1. Download from Telegram ────────────────────────────────────────
        tg_file    = await context.bot.get_file(file_id)
        buf        = await tg_file.download_as_bytearray()
        file_bytes = bytes(buf)
        size_kb    = len(file_bytes) / 1024

        # ── 2. Announce upload phase ─────────────────────────────────────────
        await status_msg.edit_text(
            f"🚀 *Uploading* `{filename}` to bucket …",
            parse_mode="Markdown",
        )

        # ── 3. Upload in thread-pool (non-blocking for event loop) ───────────
        ts_prefix   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        remote_path = f"uploads/{ts_prefix}_{filename}"

        await loop.run_in_executor(
            _executor,
            _blocking_upload,
            file_bytes,
            remote_path,
        )

        # ── 4. Success ───────────────────────────────────────────────────────
        await status_msg.edit_text(
            f"✅ *Uploaded successfully!*\n\n"
            f"📄 File: `{filename}`\n"
            f"📦 Size: `{size_kb:.1f} KB`\n"
            f"📁 Path: `{remote_path}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🗄️ View Bucket", url=HF_BUCKET_URL)]]
            ),
        )

        _add_log(filename, size_kb, user_label, "✅ Success")
        logger.info("Uploaded %s (%.1f KB) for %s → %s", filename, size_kb, user_label, remote_path)

    except Exception as exc:
        logger.exception("Upload failed for %s", filename)
        await status_msg.edit_text(
            f"❌ *Upload failed* for `{filename}`\n\n`{exc}`",
            parse_mode="Markdown",
        )
        _add_log(filename, 0, user_label, f"❌ {type(exc).__name__}: {exc}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    doc = update.message.document
    await _handle_file(update, context, doc.file_id, doc.file_name or "document.bin")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    photo = update.message.photo[-1]          # largest available resolution
    ts    = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    await _handle_file(update, context, photo.file_id, f"photo_{ts}.jpg")


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    video    = update.message.video
    filename = video.file_name or f"video_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.mp4"
    await _handle_file(update, context, video.file_id, filename)


# ---------------------------------------------------------------------------
# Bot background thread
#
# KEY FACTS about PTB v21 in a non-main thread:
#
#   1. run_polling() calls loop.add_signal_handler() by default.
#      add_signal_handler() is ONLY valid on the main thread on Unix.
#      Calling it from a daemon thread raises ValueError and the bot
#      silently dies — this is the #1 cause of "no reaction" bugs.
#      Fix: stop_signals=None
#
#   2. run_polling() wraps everything in asyncio.run(), which creates
#      AND closes its own event loop. We must NOT pre-create a loop and
#      hand it to run_polling — that causes a conflict. Instead, let PTB
#      manage the loop entirely by not calling asyncio.new_event_loop()
#      before run_polling().
#      Fix: remove manual loop creation; use close_loop=True (default)
#           OR use asyncio.run(app.run_polling(...)) with a manual loop.
#
#   The cleanest approach for a daemon thread is:
#       - Create a fresh event loop
#       - Set it as current
#       - Call loop.run_until_complete(ptb_app.run_polling(...))
#       with stop_signals=None and close_loop=False so we control teardown.
# ---------------------------------------------------------------------------

def _run_bot() -> None:
    """
    Run the Telegram polling loop in a dedicated daemon thread.

    stop_signals=None  → skip loop.add_signal_handler() — safe in non-main threads
    close_loop=False   → we own and manage the event loop lifecycle
    """
    logger.info("Bot thread starting (thread: %s)", threading.current_thread().name)

    # Validate token early so errors are obvious in the Space logs
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN is not set — bot cannot start!")
        return
    if not HF_TOKEN:
        logger.warning("HF_TOKEN is not set — uploads will fail with auth errors!")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        ptb_app = (
            ApplicationBuilder()
            .token(TELEGRAM_TOKEN)
            .build()
        )

        ptb_app.add_handler(CommandHandler("start", cmd_start))
        ptb_app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        ptb_app.add_handler(MessageHandler(filters.PHOTO,        handle_photo))
        ptb_app.add_handler(MessageHandler(filters.VIDEO,        handle_video))

        logger.info("Telegram bot polling started ✓")

        # stop_signals=None is CRITICAL for non-main-thread operation
        ptb_app.run_polling(
            drop_pending_updates=True,
            stop_signals=None,   # ← REQUIRED: no signal hooks in non-main thread
            close_loop=False,    # ← we manage the loop
        )
    except Exception:
        logger.exception("Bot thread crashed!")
    finally:
        loop.close()
        logger.info("Bot event loop closed.")


def start_bot_thread() -> threading.Thread:
    t = threading.Thread(target=_run_bot, name="TelegramBot", daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Gradio Dashboard
# ---------------------------------------------------------------------------

_CSS = """
#header        { text-align: center; padding: 1.4rem 0 0.6rem; }
#header h1     { font-size: 2rem; font-weight: 700; letter-spacing: -0.5px; margin: 0; }
#header p      { color: var(--body-text-color-subdued); margin: 0.25rem 0 0; font-size: 0.95rem; }

#status-pill {
    display: inline-flex; align-items: center; gap: 0.5rem;
    background: #1a2e1a; color: #5dcc6a;
    border: 1px solid #2e4d2e; border-radius: 999px;
    padding: 0.25rem 1rem; font-size: 0.82rem; font-weight: 600;
    margin: 0.6rem auto 1.4rem; width: fit-content;
}
#status-pill .dot {
    width: 7px; height: 7px; border-radius: 50%; background: #5dcc6a;
    box-shadow: 0 0 0 0 rgba(93,204,106,.7);
    animation: pulse 2s infinite;
}
@keyframes pulse {
    0%   { box-shadow: 0 0 0 0   rgba(93,204,106,.7); }
    70%  { box-shadow: 0 0 0 6px rgba(93,204,106, 0); }
    100% { box-shadow: 0 0 0 0   rgba(93,204,106, 0); }
}
#links-card {
    border: 1px solid var(--border-color-primary); border-radius: 10px;
    padding: 1rem 1.25rem; background: var(--background-fill-secondary);
}
"""

_HEADER_HTML = f"""
<div id="header">
  <h1>📦 File Uploader Bot</h1>
  <p>Telegram → Hugging Face Storage Bucket</p>
</div>
<div id="status-pill">
  <span class="dot"></span>
  Bot active &nbsp;·&nbsp; Bucket: <code>{HF_BUCKET_ID}</code>
</div>
"""

_LINKS_HTML = f"""
<div id="links-card">
  <h3 style="margin:0 0 .6rem">🔗 Quick Links</h3>
  <ul style="margin:0;padding-left:1.2rem;line-height:2">
    <li><a href="{HF_BUCKET_URL}" target="_blank">🗄️ Open HF Bucket</a> — browse uploaded files</li>
    <li><a href="https://huggingface.co/spaces" target="_blank">🤗 Hugging Face Spaces</a> — manage this Space</li>
    <li><a href="https://docs.python-telegram-bot.org/" target="_blank">📖 PTB docs</a> — bot API reference</li>
  </ul>
</div>
"""

LOG_HEADERS = ["Time", "Filename", "Size", "User", "Status"]


def _get_stats() -> str:
    rows    = _read_log()
    total   = len(rows)
    success = sum(1 for r in rows if "✅" in r[4])
    return (
        f"**Total processed:** {total}  \n"
        f"**✅ Success:** {success}  \n"
        f"**❌ Errors:** {total - success}"
    )


def build_gradio_app() -> gr.Blocks:
    with gr.Blocks(css=_CSS, title="File Uploader Bot") as demo:

        gr.HTML(_HEADER_HTML)

        with gr.Row():
            with gr.Column(scale=3):
                gr.Markdown("### 📋 Recent Uploads")
                log_table = gr.Dataframe(
                    headers=LOG_HEADERS,
                    value=_read_log,
                    every=5,
                    interactive=False,
                    wrap=True,
                )
                gr.Button("🔄 Refresh Now", size="sm", variant="secondary").click(
                    fn=_read_log, outputs=log_table
                )

            with gr.Column(scale=1, min_width=230):
                gr.HTML(_LINKS_HTML)
                gr.Markdown("### ℹ️ Stats")
                gr.Markdown(value=_get_stats, every=5)

        gr.HTML(
            f"<p style='text-align:center;font-size:.8rem;"
            f"color:var(--body-text-color-subdued);margin-top:2rem'>"
            f"Logs reset on Space restart · Bucket: <code>{HF_BUCKET_ID}</code></p>"
        )

    return demo


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    missing = [v for v in ("TELEGRAM_TOKEN", "HF_TOKEN") if not os.environ.get(v)]
    if missing:
        logger.warning("⚠️  Missing env vars: %s — bot/upload will fail.", missing)

    start_bot_thread()
    logger.info("Bot thread launched. Starting Gradio …")

    build_gradio_app().launch()