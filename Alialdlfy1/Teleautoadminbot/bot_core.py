import asyncio
import re
import logging
import tempfile
import os
import time
import shutil
import html
import hashlib
import difflib

from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, InputMediaVideo
try:
    from pyrogram.types import MessageEntity
    from pyrogram.enums import MessageEntityType
except Exception:
    MessageEntity = None
    MessageEntityType = None
from pyrogram.errors import MessageNotModified, FloodWait
from pyrogram.enums import ParseMode

import config
import database as db
from modules.blogger.ui import register_blogger_handlers, BLOGGER_CALLBACKS, handle_blogger_text_input
from modules.blogger.publisher import BloggerPublisher
from core.app import App as P29App
from core.control.section_control import SectionControl

logging.basicConfig(level=logging.INFO)
from modules.logging_security import install_logging_safety
install_logging_safety()
logger = logging.getLogger(__name__)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("pyrogram.session").setLevel(logging.WARNING)
logging.getLogger("pyrogram.connection").setLevel(logging.WARNING)
logging.getLogger("pyrogram.dispatcher").setLevel(logging.WARNING)

bot_client = None
user_client = None
BOT_LOG_FILE = "/tmp/telegram_auto_poster_bot.log"
user_states = {}
# Per-user back navigation stack so every shared UI page can return one step
# to the exact page the user came from, like a mobile app back gesture.
_BACK_STACKS = {}
_BACK_CURRENT = {}
_BACK_STACK_LIMIT = 16

_P29_APP = None
_P29_SECTION_CONTROL = None

def _get_p29_runtime():
    global _P29_APP, _P29_SECTION_CONTROL
    if _P29_APP is None:
        _P29_APP = P29App(legacy_db=db)
        _P29_SECTION_CONTROL = SectionControl(_P29_APP.runtime, admin_check=lambda uid: is_admin(uid) if uid is not None else False)
    return _P29_APP.runtime, _P29_SECTION_CONTROL


def _back_stack_key(callback):
    from_user = getattr(callback, "from_user", None) or {}
    user_id = from_user.get("id") if isinstance(from_user, dict) else getattr(from_user, "id", None)
    if user_id is None:
        msg = getattr(callback, "message", None)
        chat = getattr(msg, "chat", None)
        user_id = getattr(chat, "id", None) if chat is not None else None
    return user_id


def _push_back(callback):
    key = _back_stack_key(callback)
    if key is None:
        return
    stack = list(_BACK_STACKS.get(key) or [])
    stack.append(str(callback.data))
    if len(stack) > _BACK_STACK_LIMIT:
        stack = stack[-_BACK_STACK_LIMIT:]
    _BACK_STACKS[key] = stack
    _BACK_CURRENT[key] = str(callback.data)
def _back_step(callback):
    """الصفحة السابقة للصفحة الحالية (سلوك زر الرجوع في تطبيقات الموبايل).
    يزيل مدخلات الصفحة الحالية المتكررة في أعلى المكدس ثم يعيد الصفحة التي تحتها."""
    key = _back_stack_key(callback)
    stack = list(_BACK_STACKS.get(key) or [])
    current = _BACK_CURRENT.get(key)
    while stack and stack[-1] == current:
        stack.pop()
    previous = None
    if stack:
        previous = stack.pop()
    _BACK_STACKS[key] = stack
    return previous
def _peek_prev_back(callback):
    """الصفحة قبل الصفحة الحالية في المكدس (زر الرجوع في صفحات الشرح والتنفيذ)."""
    key = _back_stack_key(callback)
    stack = _BACK_STACKS.get(key) or []
    if len(stack) < 2:
        return None
    return stack[-2]


_middle_peer_warmed = False
_middle_auto_ignore_until = 0.0
_middle_album_buffers = {}
_middle_album_tasks = {}
_last_poll_ok = time.time()
_last_publish_ok = time.time()
_last_watchdog_alert = 0.0
_last_heartbeat_log = 0.0
_notification_alerted_ids = set()
_last_alert_ts = {}

# Telegram limits callback_data to 64 UTF-8 bytes. UI pages can carry nested
# back callbacks and resource IDs that exceed that limit, so retain the full
# UI payload server-side and expose only a short opaque token to Telegram.
_UI_CALLBACK_CONTEXTS = {}
_UI_CALLBACK_CONTEXT_LIMIT = 4096


def _compact_ui_callback_data(callback_data):
    if not callback_data:
        return callback_data
    if len(str(callback_data).encode("utf-8")) <= 64:
        return callback_data
    raw = str(callback_data)
    token = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    key = f"ui_ctx|{token}"
    _UI_CALLBACK_CONTEXTS[key] = raw
    if len(_UI_CALLBACK_CONTEXTS) > _UI_CALLBACK_CONTEXT_LIMIT:
        oldest = next(iter(_UI_CALLBACK_CONTEXTS), None)
        if oldest is not None and oldest != key:
            _UI_CALLBACK_CONTEXTS.pop(oldest, None)
    return key


def _expand_ui_callback_data(callback_data):
    if not str(callback_data).startswith("ui_ctx|"):
        return callback_data
    return _UI_CALLBACK_CONTEXTS.get(str(callback_data))


def _compact_ui_markup(reply_markup):
    if reply_markup is None:
        return reply_markup
    for row in getattr(reply_markup, "inline_keyboard", ()) or ():
        for button in row or ():
            callback_data = getattr(button, "callback_data", None)
            compacted = _compact_ui_callback_data(callback_data)
            if compacted != callback_data:
                button.callback_data = compacted
    return reply_markup


def is_admin(user_id):
    return user_id in config.ADMINS

def mark_runtime_activity(kind="poll"):
    """يسجل آخر نشاط ناجح حتى نعرف إذا البوت عالق بدون نشر/فحص."""
    global _last_poll_ok, _last_publish_ok
    now = time.time()
    if kind == "publish":
        _last_publish_ok = now
    _last_poll_ok = now


def is_transient_network_error(error):
    """أخطاء اتصال مؤقتة من HuggingFace/Telegram لا تعتبر عطل منطقي بالكود."""
    text = str(error).lower()
    transient_terms = [
        "broken pipe",
        "socket.send() raised exception",
        "connection reset",
        "connection aborted",
        "server disconnected",
        "transport closed",
        "timed out",
        "timeout",
        "network is unreachable",
        "cannot write to closing transport",
    ]
    return any(term in text for term in transient_terms)


async def reconnect_user_client_if_needed(reason=""):
    """محاولة إنعاش جلسة الحساب عند Broken pipe بدون لمس إعدادات النشر."""
    global _middle_peer_warmed
    try:
        logger.warning(f"🔌 محاولة إعادة تهيئة اتصال user_client بسبب: {reason}")
        try:
            await user_client.stop()
        except Exception:
            pass
        await asyncio.sleep(3)
        await user_client.start()
        _middle_peer_warmed = False
        await warm_middle_peer()
        logger.info("✅ تمت إعادة تهيئة اتصال user_client")
        return True
    except Exception as e:
        logger.warning(f"⚠️ فشلت إعادة تهيئة user_client: {e}")
        return False


async def _retry_on_flood(send_func, label="", max_retries=3):
    """ينفذ عملية إرسال مع انتظار تلقائي عند حظر تيليجرام للإرسال السريع."""
    for attempt in range(max_retries):
        try:
            return await send_func()
        except FloodWait as e:
            wait = int(e.value) + 2
            logger.warning(f"⏳ FloodWait{' - ' + label if label else ''}: انتظار {wait}s (محاولة {attempt+1}/{max_retries})")
            await asyncio.sleep(wait)
        except Exception:
            raise
    return await send_func()


# ============================================================
# VerificationService - طبقة التحقق الموحدة
# ============================================================

class VerificationService:
    """طبقة تحقق موحدة.
    
    - جميع عمليات التحقق تمر من هنا فقط.
    - يستخدم Smart Cache للواجهات والقوائم.
    - يقوم بتحقق حقيقي من Telegram قبل العمليات الحساسة.
    - يستخدم BotManager للحصول على التوكنات (لا وصول مباشر للتوكن).
    """

    def __init__(self):
        self._verify_cache_ttl = 120  # 2 دقيقة للعمليات
        self._ui_cache_ttl = 600      # 10 دقائق للواجهات

    # ---- تحقق داخلي من Telegram (بدون كاش) ----

    async def _api_check_bot_in_channel(self, token, channel_id):
        """اتصال مباشر بـ Telegram للتحقق من وجود البوت في القناة."""
        result = {"verified": False, "can_post": False, "status": "", "permissions": {}}
        if not token or not channel_id:
            return result
        try:
            temp = Client(":memory:", api_id=config.API_ID, api_hash=config.API_HASH, bot_token=token, in_memory=True)
            await temp.start()
            me = await temp.get_me()
            try:
                member = await temp.get_chat_member(int(channel_id), me.id)
                status = member_status_value(getattr(member, "status", None))
                result["status"] = status
                if is_bot_admin_status(status):
                    result["verified"] = True
                    if hasattr(member, "can_post_messages"):
                        result["can_post"] = bool(member.can_post_messages)
                    elif status in ("owner", "creator"):
                        result["can_post"] = True
                    else:
                        result["can_post"] = True
                    if hasattr(member, "privileges"):
                        priv = member.privileges
                        if priv:
                            result["permissions"] = {
                                "can_post_messages": bool(getattr(priv, "can_post_messages", True)),
                                "can_edit_messages": bool(getattr(priv, "can_edit_messages", True)),
                                "can_delete_messages": bool(getattr(priv, "can_delete_messages", True)),
                            }
            except Exception as e:
                result["status"] = str(e)[:50]
            await temp.stop()
        except Exception as e:
            result["status"] = f"فشل الاتصال: {str(e)[:50]}"
        return result

    async def _api_check_token(self, token):
        """التحقق من صحة التوكن عبر Telegram."""
        result = {"valid": False, "id": "", "username": "", "first_name": "", "error": ""}
        try:
            temp = Client(":memory:", api_id=config.API_ID, api_hash=config.API_HASH, bot_token=token, in_memory=True)
            await temp.start()
            me = await temp.get_me()
            result["valid"] = True
            result["id"] = str(me.id)
            result["username"] = me.username or ""
            result["first_name"] = me.first_name or ""
            await temp.stop()
        except Exception as e:
            result["error"] = str(e)[:100]
        return result

    async def _api_check_session(self, session_string, api_id, api_hash):
        """التحقق من صلاحية جلسة مستخدم."""
        result = {"valid": False, "id": "", "username": "", "error": ""}
        try:
            temp = Client(":memory:", api_id=api_id, api_hash=api_hash, session_string=session_string, in_memory=True)
            await temp.start()
            me = await temp.get_me()
            result["valid"] = True
            result["id"] = str(me.id)
            result["username"] = me.username or ""
            await temp.stop()
        except Exception as e:
            result["error"] = str(e)[:100]
        return result

    async def _api_check_channel(self, channel_id):
        """التحقق من إمكانية الوصول للقناة عبر البوت الرئيسي."""
        result = {"ok": False, "title": "", "username": "", "type": "", "error": ""}
        try:
            chat = await bot_client.get_chat(int(channel_id))
            result["ok"] = True
            result["title"] = getattr(chat, "title", "") or ""
            result["username"] = getattr(chat, "username", "") or ""
            result["type"] = str(getattr(chat, "type", "")) or ""
        except Exception as e:
            result["error"] = str(e)[:100]
        return result

    # ---- تحقق مع كاش للعمليات الحساسة ----

    async def check_bot_in_channel(self, bot_id, channel_id, force=False):
        """التحقق من وجود بوت في قناة.
        
        - force=True: يتجاهل الكاش ويتصل بـ Telegram مباشرة.
        - force=False: يستخدم الكاش إذا كان حديثاً.
        """
        token = db.bot_manager.get_token(bot_id) if hasattr(db, "bot_manager") else ""
        if not token:
            return {"verified": False, "can_post": False, "status": "no_token",
                    "permissions": {}, "from_cache": False, "last_check": 0}

        cache_key = f"verify_bot|{bot_id}|{channel_id}"
        if not force:
            cached = db.cache_get(cache_key)
            if cached is not None:
                cached["from_cache"] = True
                return cached

        result = await self._api_check_bot_in_channel(token, channel_id)
        result["last_check"] = time.time()
        result["from_cache"] = False
        result["bot_id"] = bot_id

        db.cache_set(cache_key, result, ttl=self._verify_cache_ttl)
        if hasattr(db, "set_bot_channel_verification"):
            bname = ""
            b = db.get_publishing_bot(bot_id)
            if b:
                bname = b.get("name", "")
            db.set_bot_channel_verification(bot_id, channel_id,
                result["verified"], result["can_post"],
                result["status"], result["permissions"],
                bname, "")
        return result

    async def check_channel_before_operation(self, channel_id, force=False):
        """التحقق من القناة قبل أي عملية حساسة (نشر/حذف)."""
        cache_key = f"channel_op|{channel_id}"
        if not force:
            cached = db.cache_get(cache_key)
            if cached is not None:
                return cached.get("ok", False)

        ch = db.get_channel(str(channel_id))
        if not ch:
            return False

        ver = await self._api_check_channel(channel_id)
        if ver.get("ok"):
            db.cache_set(cache_key, {"ok": True}, ttl=self._verify_cache_ttl)
            return True

        db.cache_set(cache_key, {"ok": False}, ttl=60)
        return False

    async def validate_token(self, token):
        """التحقق من صحة توكن بوت."""
        cache_key = f"token_valid|{token[:10]}"
        cached = db.cache_get(cache_key)
        if cached is not None:
            return cached
        result = await self._api_check_token(token)
        db.cache_set(cache_key, result, ttl=db.CACHE_TTL.get("bot_token_valid", 3600))
        return result

    async def validate_session(self, session_string, api_id, api_hash):
        """التحقق من صلاحية جلسة مستخدم."""
        cache_key = f"session_valid|{session_string[:20]}"
        cached = db.cache_get(cache_key)
        if cached is not None:
            return cached
        result = await self._api_check_session(session_string, api_id, api_hash)
        db.cache_set(cache_key, result, ttl=db.CACHE_TTL.get("session_valid", 600))
        return result

    # ---- دوال مساعدة للواجهات ----

    def get_cached_verification(self, bot_id, channel_id):
        """إرجاع التحقق المخبأ للعرض في الواجهات فقط."""
        if hasattr(db, "get_bot_channel_verification"):
            return db.get_bot_channel_verification(bot_id, channel_id)
        return {"verified": False, "can_post": False, "status": "", "last_check": 0}

    def _get_from_smartcache_or_db(self, bot_id, channel_id):
        """محاولة الحصول على التحقق من Smart Cache أولاً (TTL=120s)،
        فإن لم يكن موجوداً→ من Persistent DB (data.json).
        يطبع Trace كامل في Console."""
        # 1. حاول من Smart Cache
        cache_key = f"verify_bot|{bot_id}|{channel_id}"
        cached = db.cache_get(cache_key) if hasattr(db, "cache_get") else None
        if cached is not None:
            age = int(time.time() - cached.get("last_check", 0))
            logger.info(
                f"🔍 TRACE: bot={bot_id} channel={channel_id} "
                f"المصدر=SmartCache عمر={age}ث "
                f"verified={cached.get('verified')} can_post={cached.get('can_post')}"
            )
            return cached
        # 2. من Persistent DB
        persistent = db.get_bot_channel_verification(bot_id, channel_id) if hasattr(db, "get_bot_channel_verification") else {}
        age = int(time.time() - persistent.get("last_check", 0)) if persistent.get("last_check") else -1
        logger.info(
            f"🔍 TRACE: bot={bot_id} channel={channel_id} "
            f"المصدر=PersistentDB عمر={age}ث "
            f"verified={persistent.get('verified')} can_post={persistent.get('can_post')}"
        )
        return persistent

    def get_cached_verifications_for_channel(self, channel_id):
        """إرجاع جميع التحققات لقناة (للواجهات).
        - يحاول Smart Cache أولاً
        - يرجع Persistent DB إذا الكاش فارغ
        """
        result = {}
        # نحتاج IDs البوتات المرتبطة بالقناة
        if hasattr(db, "mapper"):
            bot_ids = db.mapper.get_bots_for_channel(channel_id)
        else:
            cfg = db.get_channel_config(channel_id) if hasattr(db, "get_channel_config") else {}
            bot_ids = cfg.get("assigned_bots", [])
        for bid in bot_ids:
            result[str(bid)] = self._get_from_smartcache_or_db(bid, channel_id)
        # إذا ما في بوتات مرتبطة بالم mapper، نبحث في persistent
        if not bot_ids and hasattr(db, "get_verifications_for_channel"):
            result = db.get_verifications_for_channel(channel_id)
        return result

    def get_cached_verifications_for_bot(self, bot_id):
        """إرجاع جميع التحققات لبوت (للواجهات).
        - يحاول Smart Cache أولاً
        - يرجع Persistent DB إذا الكاش فارغ
        """
        result = {}
        # نحتاج IDs القنوات المرتبطة بالبوت
        if hasattr(db, "mapper"):
            channel_ids = db.mapper.get_channels_for_bot(bot_id)
        else:
            deps = db.get_dependencies_for("publishing_bot", bot_id) if hasattr(db, "get_dependencies_for") else []
            channel_ids = [d.get("id", "") for d in deps]
        for cid in channel_ids:
            result[str(cid)] = self._get_from_smartcache_or_db(bot_id, cid)
        # إذا ما في قنوات مرتبطة، نبحث في persistent
        if not channel_ids and hasattr(db, "get_verifications_for_bot"):
            result = db.get_verifications_for_bot(bot_id)
        return result


# إنشاء instance عامة
verifier = VerificationService()


# ============================================================
# دوال تحقق قديمة (متوافقة مع الكود الموجود)
# ============================================================

async def _telegram_verify_bot_in_channel(bot_token, channel_id):
    """للتوافق مع الكود القديم - يستخدم VerificationService."""
    return await verifier._api_check_bot_in_channel(bot_token, channel_id)


async def require_bot_token_valid(token):
    """للتوافق مع الكود القديم."""
    return await verifier.validate_token(token)


def member_status_value(member_status):
    """يرجع قيمة حالة العضوية كنص نظيف (متوافق مع Enum أو نص من أي إصدار pyrogram)."""
    if member_status is None:
        return ""
    if hasattr(member_status, "value"):
        return str(member_status.value)
    return str(member_status)


def is_bot_admin_status(status_value):
    """الحالات الصالحة: ADMINISTRATOR / OWNER (و creator للتوافق القديم).
    غير الصالحة: MEMBER / LEFT / BANNED / RESTRICTED."""
    return status_value in ("administrator", "owner", "creator")


async def _verify_channel_before_publish(target):
    """التحقق من القناة قبل النشر."""
    return await verifier.check_channel_before_operation(str(target))


async def heartbeat_watchdog_loop():
    """نبض مراقبة: يطبع حالة دورية وينبه إذا توقف الفحص/النشر مدة طويلة."""
    global _last_watchdog_alert, _last_heartbeat_log
    await asyncio.sleep(60)
    while True:
        try:
            now = time.time()
            idle_poll = int(now - _last_poll_ok)
            idle_publish = int(now - _last_publish_ok)

            if now - _last_heartbeat_log >= 600:
                _last_heartbeat_log = now
                logger.info(f"💓 Heartbeat OK | آخر فحص قبل {idle_poll}s | آخر نشر قبل {idle_publish}s")

            if idle_poll >= 3600 and now - _last_watchdog_alert >= 3600:
                _last_watchdog_alert = now
                logger.warning(f"⚠️ Watchdog: لا يوجد فحص ناجح منذ {idle_poll} ثانية")
                await notify_admins(f"⚠️ تنبيه مراقبة: لا يوجد فحص ناجح منذ {idle_poll // 60} دقيقة. إذا لم يرجع النشر، افتح الاستضافة أو سوِ Restart.")
                await reconnect_user_client_if_needed("watchdog idle poll")
        except Exception as e:
            logger.warning(f"⚠️ خطأ في Heartbeat/Watchdog: {e}")
        await asyncio.sleep(60)

def clean_text(text, source_id=None, channel_id=None):
    """تنظيف نهائي قبل النشر لقناة معيّنة. يرجع None إذا النص يحتوي كلمة محظورة خاصة بهذه القناة."""
    if not text:
        return text

    if isinstance(text, str):
        text = full_clean_text(text, source_id=source_id)
        text = apply_channel_remove_terms(text, channel_id)
        text = apply_channel_link_filters(text, channel_id)

        blocked = db.get_channel_blocked_words(channel_id) if channel_id is not None and hasattr(db, "get_channel_blocked_words") else []
        for word in blocked:
            if word and word in text:
                return None

        return "\n".join(line for line in text.splitlines() if line.strip())

    return text

def apply_tail(text, tail):
    if tail:
        return f"{text}\n{tail}" if text else tail
    return text


def get_publish_delay_for_channel(channel_id, default=0.5):
    try:
        return db.get_channel_publish_delay(channel_id, default) if hasattr(db, "get_channel_publish_delay") else default
    except Exception:
        return default

def is_channel_bold_enabled(channel_id):
    try:
        return bool(db.get_channel_bold_publish(channel_id, True)) if hasattr(db, "get_channel_bold_publish") else True
    except Exception:
        return True


def _utf16_len(text):
    try:
        return len(str(text or "").encode("utf-16-le")) // 2
    except Exception:
        return len(str(text or ""))


def _entity_type(name):
    if MessageEntityType is None:
        return None
    try:
        return getattr(MessageEntityType, name)
    except Exception:
        return None


def build_quote_entities_for_channel(text, channel_id, content_type="text"):
    """يبني entities رسمية للاقتباس حتى لا نعتمد على HTML blockquote إذا ما يدعمه Pyrogram."""
    if not text:
        return None
    if not is_channel_quote_enabled(channel_id, content_type):
        return None
    if MessageEntity is None or MessageEntityType is None:
        return None

    length = _utf16_len(text)
    if length <= 0:
        return None

    entities = []
    blockquote_type = _entity_type("BLOCKQUOTE")
    bold_type = _entity_type("BOLD")

    if blockquote_type is not None:
        try:
            entities.append(MessageEntity(type=blockquote_type, offset=0, length=length))
        except Exception:
            return None

    if is_channel_bold_enabled(channel_id) and bold_type is not None:
        try:
            entities.append(MessageEntity(type=bold_type, offset=0, length=length))
        except Exception:
            pass

    return entities or None


def _html_quote_text_for_channel(text, channel_id):
    """يبني اقتباس Telegram الرسمي بصيغة HTML بدون إضافة رموز مرئية مثل ▌."""
    escaped = html.escape(str(text or ""))
    if is_channel_bold_enabled(channel_id):
        escaped = f"<b>{escaped}</b>"
    return f"<blockquote>{escaped}</blockquote>"


def format_outgoing_payload_for_channel(text, channel_id, content_type="text", news_text=None, tail=None):
    """يرجع النص + parse_mode + entities. عند تفعيل الاقتباس نستخدم Telegram Quote الرسمي فقط."""
    if not text:
        return text, None, None

    cfg = db.get_channel_config(channel_id) if hasattr(db, "get_channel_config") else {}
    title_quote = bool(cfg.get("title_quote", False))
    sig_quote = bool(cfg.get("signature_quote", False))

    if title_quote or sig_quote:
        bold_enabled = is_channel_bold_enabled(channel_id)
        body = str(text)
        news_text_str = str(news_text or "").strip()
        tail_str = str(tail or "").strip()
        escaped_body = html.escape(body)
        # نبحث عن النص الأصلي ونبدله بالنسخة المقتبسة داخل الـ HTML
        if title_quote and news_text_str:
            escaped_news = html.escape(news_text_str)
            if escaped_news in escaped_body:
                escaped_body = escaped_body.replace(escaped_news, f"<blockquote>{escaped_news}</blockquote>", 1)
        if sig_quote and tail_str:
            escaped_tail = html.escape(tail_str)
            idx = escaped_body.rfind(escaped_tail)
            if idx != -1:
                escaped_body = escaped_body[:idx] + f"<blockquote>{escaped_tail}</blockquote>" + escaped_body[idx + len(escaped_tail):]
        if bold_enabled:
            escaped_body = f"<b>{escaped_body}</b>"
        return escaped_body, ParseMode.HTML, None

    if is_channel_quote_enabled(channel_id, content_type):
        entities = build_quote_entities_for_channel(str(text), channel_id, content_type)
        if entities:
            return str(text), None, entities
        return _html_quote_text_for_channel(text, channel_id), ParseMode.HTML, None

    formatted, parse_mode = format_outgoing_text_for_channel(text, channel_id)
    return formatted, parse_mode, None


def format_outgoing_text_for_channel(text, channel_id):
    """يرجع النص مع ParseMode المناسب. ترتيب الهاشتاك/التوقيع يتم قبل هذه الدالة."""
    if not text:
        return text, None

    bold_enabled = is_channel_bold_enabled(channel_id)

    escaped = html.escape(str(text))
    if bold_enabled:
        escaped = f"<b>{escaped}</b>"

    if bold_enabled:
        return escaped, ParseMode.HTML
    return str(text), None

def channel_display_name(ch_or_id):
    ch = ch_or_id if isinstance(ch_or_id, dict) else db.get_channel(ch_or_id)
    if isinstance(ch, dict):
        name = entity_name(ch)
        cid = ch.get("id")
        if isinstance(cid, (str, int)):
            return f"{name} | ID: `{cid}`"
        return name
    if isinstance(ch_or_id, (str, int)):
        return f"ID: `{ch_or_id}`"
    return str(ch_or_id or "")


def source_display_name(src_id):
    meta = db.get_source_meta(src_id) if hasattr(db, "get_source_meta") else {"id": src_id}
    return f"{entity_name(meta)} | ID: `{src_id}`"


def pair_buttons(buttons):
    """يرتب الأزرار المفردة على عمودين قدر الإمكان."""
    rows = []
    pending = []
    for item in buttons:
        if isinstance(item, list):
            if pending:
                rows.append(pending)
                pending = []
            rows.append(item)
        else:
            pending.append(item)
            if len(pending) == 2:
                rows.append(pending)
                pending = []
    if pending:
        rows.append(pending)
    return rows




def grid_buttons(buttons, max_cols=3):
    """يرتب الأزرار المفردة بعمودين فقط حتى تظهر أسماء الأزرار بوضوح."""
    rows = []
    pending = []
    max_cols = 2
    for item in buttons:
        if isinstance(item, list):
            if pending:
                rows.append(pending)
                pending = []
            rows.append(item)
        else:
            pending.append(item)
            if len(pending) >= max_cols:
                rows.append(pending)
                pending = []
    if pending:
        rows.append(pending)
    return rows


def nav_row(back=None):
    row = []
    if back:
        row.append(InlineKeyboardButton("🔙 رجوع", callback_data=back))
    row.append(InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu"))
    return row


def append_channel_hashtags(text, channel_id):
    try:
        tags = db.get_channel_hashtags(channel_id) if hasattr(db, "get_channel_hashtags") else []
    except Exception:
        tags = []
    if not tags:
        return text
    tag_line = " ".join(tags)
    return f"{text}\n\n{tag_line}" if text else tag_line


def compose_channel_post_text(news_text, channel_id, tail=""):
    """يرتب المنشور دائماً: الخبر ثم الهاشتاك ثم التوقيع ثم الفاصل."""
    parts = []
    news_text = str(news_text or "").strip()
    if news_text:
        parts.append(news_text)
    try:
        tags = db.get_channel_hashtags(channel_id) if hasattr(db, "get_channel_hashtags") else []
    except Exception:
        tags = []
    if tags:
        parts.append(" ".join(tags).strip())
    tail = str(tail or "").strip()
    if tail:
        parts.append(tail)
        if "---" not in tail and "—" not in tail:
            parts.append("------------")
    return "\n\n".join([p for p in parts if p])

def is_channel_quote_enabled(channel_id, content_type="text"):
    try:
        if hasattr(db, "get_channel_quote_type"):
            return bool(db.get_channel_quote_type(channel_id, content_type, False))
        return bool(db.get_channel_quote_publish(channel_id, False)) if hasattr(db, "get_channel_quote_publish") else False
    except Exception:
        return False


def get_channel_quote_types_safe(channel_id):
    try:
        if hasattr(db, "get_channel_quote_types"):
            return db.get_channel_quote_types(channel_id)
    except Exception:
        pass
    enabled = is_channel_quote_enabled(channel_id, "text")
    return {"text": enabled, "photo": enabled, "video": enabled, "album": enabled}



def is_ignore_short_posts_enabled():
    try:
        return bool(db.get_ignore_short_posts()) if hasattr(db, "get_ignore_short_posts") else False
    except Exception:
        return False


def is_short_post_text(text, min_words=5, min_chars=20):
    cleaned = compact_text(text or "")
    if not cleaned:
        return False
    word_count = len([w for w in cleaned.split() if w.strip()])
    char_count = len(cleaned)
    return word_count < int(min_words) or char_count < int(min_chars)


def is_ignore_short_posts_enabled_for_channel(channel_id):
    try:
        if hasattr(db, "get_channel_ignore_short_posts"):
            return bool(db.get_channel_ignore_short_posts(channel_id))
    except Exception:
        pass
    return is_ignore_short_posts_enabled()


def should_ignore_short_post(text):
    """Legacy global helper kept for compatibility with older callers/tests."""
    return is_ignore_short_posts_enabled() and is_short_post_text(text)


def should_ignore_short_post_for_channel(text, channel_id):
    return is_ignore_short_posts_enabled_for_channel(channel_id) and is_short_post_text(text)


def record_channel_success(channel_id):
    try:
        if hasattr(db, "record_channel_publish_success"):
            db.record_channel_publish_success(channel_id)
    except Exception:
        pass


async def record_channel_failure_and_maybe_alert(channel_id, error):
    count = None
    try:
        if hasattr(db, "record_channel_publish_failure"):
            count = db.record_channel_publish_failure(channel_id, error, limit=5)
    except Exception:
        pass
    if count and int(count) >= 5:
        await notify_admins(f"تم إيقاف قناة النشر تلقائياً بعد {count} أخطاء متتالية:\n{channel_display_name(channel_id)}\n\nالخطأ: {error}")

async def notify_admins(text):
    try:
        if hasattr(db, "add_last_error"):
            db.add_last_error("admin_alert", text)
    except Exception:
        pass
    for admin_id in config.ADMINS:
        try:
            await bot_client.send_message(admin_id, f"⚠️ {text}")
        except Exception as e:
            logger.error(f"فشل إشعار الأدمن {admin_id}: {e}")

async def hydrate_peer(client, chat_id, label="peer"):
    """يحاول تحميل الـ peer داخل جلسة Pyrogram حتى لا يظهر Peer id invalid."""
    try:
        chat = await client.get_chat(int(chat_id))
        logger.info(f"✅ تم تحميل {label}: {getattr(chat, 'id', chat_id)}")
        return chat
    except Exception as first_error:
        logger.warning(f"⚠️ فشل get_chat أول مرة لـ {label}={chat_id}: {first_error}. سيتم فحص الحوارات...")

    try:
        async for dialog in client.get_dialogs(limit=300):
            if dialog.chat and int(dialog.chat.id) == int(chat_id):
                logger.info(f"✅ تم العثور على {label} داخل الحوارات: {chat_id}")
                return dialog.chat
    except Exception as dialog_error:
        logger.warning(f"⚠️ فشل فحص الحوارات لـ {label}: {dialog_error}")

    chat = await client.get_chat(int(chat_id))
    return chat


async def hydrate_publish_channel(channel_id):
    """تهيئة قناة نشر قبل الإرسال، خصوصاً بعد الاستيراد."""
    ch = db.get_channel(channel_id) if hasattr(db, "get_channel") else None
    candidates = []
    if ch:
        username = ch.get("username") or ""
        link = ch.get("link") or ""
        if username:
            candidates.append("@" + username.lstrip("@"))
        if link:
            candidates.append(link)
    candidates.append(int(channel_id))
    last_error = None
    for item in candidates:
        try:
            return await bot_client.get_chat(item)
        except Exception as e:
            last_error = e
    raise last_error or ValueError(f"تعذر تهيئة قناة النشر {channel_id}")


async def hydrate_source_channel(source_id):
    meta = db.get_source_meta(source_id) if hasattr(db, "get_source_meta") else {}
    candidates = []
    username = meta.get("username") or "" if isinstance(meta, dict) else ""
    link = meta.get("link") or "" if isinstance(meta, dict) else ""
    if username:
        candidates.append("@" + username.lstrip("@"))
    if link:
        candidates.append(link)
    candidates.append(int(source_id))
    last_error = None
    for item in candidates:
        try:
            return await user_client.get_chat(item)
        except Exception as e:
            last_error = e
    raise last_error or ValueError(f"تعذر تهيئة المصدر {source_id}")


async def safe_send_channel_message(target, text, parse_mode=None, entities=None):
    """إرسال نص مع معالجة FloodWait وإعادة تهيئة peer عند الحاجة."""
    try:
        await hydrate_publish_channel(target)
    except Exception as e:
        logger.warning(f"⚠️ فشل تهيئة قناة النشر {target} قبل الإرسال: {e}")

    disable_preview = db.get_channel_disable_preview(target) if hasattr(db, "get_channel_disable_preview") else False

    async def _send_once():
        if entities:
            try:
                return await bot_client.send_message(target, text, entities=entities, disable_web_page_preview=disable_preview)
            except TypeError:
                return await bot_client.send_message(target, _html_quote_text_for_channel(text, target), parse_mode=ParseMode.HTML, disable_web_page_preview=disable_preview)
        return await bot_client.send_message(target, text, parse_mode=parse_mode, disable_web_page_preview=disable_preview)

    for attempt in range(3):
        try:
            return await _send_once()
        except FloodWait as e:
            wait = int(e.value) + 2
            logger.warning(f"⏳ FloodWait في الإرسال إلى {target}: انتظار {wait}s (محاولة {attempt+1}/3)")
            await asyncio.sleep(wait)
        except Exception as first_error:
            if "Peer id invalid" in str(first_error) or "PEER_ID_INVALID" in str(first_error):
                await hydrate_publish_channel(target)
                return await _send_once()
            raise
    return await _send_once()

async def warm_middle_peer():
    """تحميل القناة الوسيطة داخل جلسة الحساب والبوت قبل أي تحويل ميديا."""
    global _middle_peer_warmed
    if _middle_peer_warmed:
        return True

    ok = True
    try:
        await hydrate_peer(user_client, config.MIDDLE_CHANNEL, "القناة الوسيطة / user_client")
    except Exception as e:
        ok = False
        logger.error(f"❌ user_client لا يستطيع الوصول للقناة الوسيطة {config.MIDDLE_CHANNEL}: {e}")

    try:
        await hydrate_peer(bot_client, config.MIDDLE_CHANNEL, "القناة الوسيطة / bot_client")
    except Exception as e:
        ok = False
        logger.error(f"❌ bot_client لا يستطيع الوصول للقناة الوسيطة {config.MIDDLE_CHANNEL}: {e}")

    _middle_peer_warmed = ok
    return ok

async def forward_to_middle(source_chat_id, message_ids):
    """يحّول رسالة أو مجموعة رسائل إلى القناة الوسيطة مع إعادة محاولة عند Peer id invalid."""
    await warm_middle_peer()
    try:
        return await user_client.forward_messages(
            chat_id=config.MIDDLE_CHANNEL,
            from_chat_id=int(source_chat_id),
            message_ids=message_ids
        )
    except Exception as e:
        logger.warning(f"⚠️ فشل التوجيه للوسيطة، سيتم إعادة تحميل الـ peer والمحاولة مرة ثانية: {e}")
        global _middle_peer_warmed
        _middle_peer_warmed = False
        await warm_middle_peer()
        return await user_client.forward_messages(
            chat_id=config.MIDDLE_CHANNEL,
            from_chat_id=int(source_chat_id),
            message_ids=message_ids
        )

async def copy_middle_messages_to_target(target, middle_messages, caption=None, parse_mode=None, content_type=None, caption_entities=None):
    """ينسخ رسائل الوسيطة لقناة النشر.
    - الصور/الفيديو المفرد: copy_message بدون تحميل.
    - الألبومات: send_media_group كألبوم واحد بدون Forward.
    """
    if not isinstance(middle_messages, (list, tuple)):
        middle_messages = [middle_messages]

    middle_messages = sorted([m for m in middle_messages if m], key=lambda m: m.id)
    if not middle_messages:
        return False

    try:
        await hydrate_publish_channel(target)
    except Exception as e:
        logger.warning(f"⚠️ فشل تهيئة قناة النشر {target} قبل النسخ: {e}")

    is_album = len(middle_messages) > 1 or bool(getattr(middle_messages[0], "media_group_id", None))

    # الألبومات فقط: نرسلها كـ Media Group واحد حتى لا تتفكك إلى صور منفصلة.
    # هذا المسار قد يحمّل ملفات الألبوم مؤقتاً ثم يحذفها، بينما الصور/الفيديو المفرد تبقى بدون تحميل.
    if is_album and len(middle_messages) > 1:
        temp_dir = tempfile.mkdtemp(prefix="album_clean_")
        downloaded_files = []
        media_items = []
        try:
            for idx, m in enumerate(middle_messages):
                if not getattr(m, "photo", None) and not getattr(m, "video", None):
                    logger.warning(f"⚠️ تم تخطي عنصر غير مدعوم داخل الألبوم | message_id={getattr(m, 'id', None)}")
                    continue

                file_path = await m.download(file_name=os.path.join(temp_dir, ""))
                if not file_path:
                    logger.warning(f"⚠️ فشل تنزيل عنصر من الألبوم | message_id={getattr(m, 'id', None)}")
                    continue

                downloaded_files.append((file_path, bool(getattr(m, "video", None))))
                item_caption = caption if idx == 0 and caption else None

                if getattr(m, "video", None):
                    media_items.append(InputMediaVideo(
                        media=file_path,
                        caption=item_caption,
                        parse_mode=None if (idx == 0 and item_caption and caption_entities) else (parse_mode if item_caption else None),
                        caption_entities=caption_entities if idx == 0 and item_caption and caption_entities else None
                    ))
                else:
                    media_items.append(InputMediaPhoto(
                        media=file_path,
                        caption=item_caption,
                        parse_mode=None if (idx == 0 and item_caption and caption_entities) else (parse_mode if item_caption else None),
                        caption_entities=caption_entities if idx == 0 and item_caption and caption_entities else None
                    ))

            if not media_items:
                logger.error(f"❌ فشل نشر الألبوم النظيف إلى {target}: لا توجد وسائط صالحة")
                return False

            sent = None
            pyrofork_topics_success = False
            try:
                sent = await _retry_on_flood(lambda: bot_client.send_media_group(chat_id=int(target), media=media_items), label=f"album→{target}")
            except TypeError as e:
                err_text = str(e)
                if "topics" in err_text and "Messages.__init__" in err_text:
                    pyrofork_topics_success = True
                    logger.warning(f"⚠️ نُشر الألبوم غالباً لكن Pyrofork فشل بقراءة الرد بسبب topics؛ اعتُبر نجاحاً لمنع التكرار | target={target}")
                else:
                    # بعض إصدارات Pyrogram/Pyrofork لا تقبل caption_entities داخل InputMedia.
                    media_items = []
                    for idx, (file_path, is_video_file) in enumerate(downloaded_files):
                        item_caption = caption if idx == 0 and caption else None
                        if is_video_file:
                            media_items.append(InputMediaVideo(media=file_path, caption=item_caption, parse_mode=parse_mode if item_caption else None))
                        else:
                            media_items.append(InputMediaPhoto(media=file_path, caption=item_caption, parse_mode=parse_mode if item_caption else None))
                    try:
                        sent = await _retry_on_flood(lambda: bot_client.send_media_group(chat_id=int(target), media=media_items), label=f"album→{target}")
                    except TypeError as e2:
                        err_text2 = str(e2)
                        if "topics" in err_text2 and "Messages.__init__" in err_text2:
                            pyrofork_topics_success = True
                            logger.warning(f"⚠️ نُشر الألبوم غالباً لكن Pyrofork فشل بقراءة الرد بسبب topics؛ اعتُبر نجاحاً لمنع التكرار | target={target}")
                        else:
                            raise
            except Exception as e:
                err_text = str(e)
                if "topics" in err_text and "Messages.__init__" in err_text:
                    pyrofork_topics_success = True
                    logger.warning(f"⚠️ نُشر الألبوم غالباً لكن Pyrofork فشل بقراءة الرد بسبب topics؛ اعتُبر نجاحاً لمنع التكرار | target={target}")
                else:
                    raise

            sent_list = [] if sent is None else (sent if isinstance(sent, list) else [sent])
            sent_ids = [m.id for m in sent_list if getattr(m, "id", None)]
            try:
                if hasattr(db, "record_published_messages") and sent_ids:
                    db.record_published_messages(target, sent_ids, content_type or "album")
            except Exception:
                pass

            mark_runtime_activity("publish")
            if pyrofork_topics_success:
                logger.info(f"✅ نُشر ألبوم نظيف إلى {target} بدون Forward | Pyrofork topics handled")
            else:
                logger.info(f"✅ نُشر ألبوم نظيف إلى {target} بدون Forward | count={len(sent_ids)}")
            return True
        except Exception as e:
            logger.error(f"❌ فشل نشر الألبوم النظيف إلى {target}: {e}")
            try:
                if hasattr(db, "add_last_error"):
                    db.add_last_error("clean_album", f"{target}: {e}")
            except Exception:
                pass
            return False
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # الصور والفيديوهات المفردة: تبقى بدون تحميل عبر copy_message.
    sent_ids = []
    disable_preview = db.get_channel_disable_preview(target) if hasattr(db, "get_channel_disable_preview") else False
    for idx, m in enumerate(middle_messages):
        item_caption = caption if idx == 0 and caption else None
        item_parse_mode = None if (idx == 0 and caption and caption_entities) else (parse_mode if idx == 0 and caption else None)

        kwargs = dict(
            chat_id=int(target),
            from_chat_id=config.MIDDLE_CHANNEL,
            message_id=m.id,
            caption=item_caption,
            parse_mode=item_parse_mode,
            disable_web_page_preview=disable_preview,
        )
        if idx == 0 and caption and caption_entities:
            kwargs["caption_entities"] = caption_entities

        async def _do_copy(kw=kwargs, ix=idx, cap=item_caption):
            try:
                return await bot_client.copy_message(**kw)
            except TypeError:
                kw.pop("caption_entities", None)
                kw.pop("disable_web_page_preview", None)
                if ix == 0 and cap and caption_entities:
                    kw["caption"] = _html_quote_text_for_channel(cap, target)
                    kw["parse_mode"] = ParseMode.HTML
                else:
                    kw["parse_mode"] = parse_mode if ix == 0 and cap else None
                return await bot_client.copy_message(**kw)

        try:
            sent = await _retry_on_flood(_do_copy, label=f"copy→{target}")
            if getattr(sent, "id", None):
                sent_ids.append(sent.id)
        except Exception as e:
            logger.warning(f"⚠️ فشل نسخ رسالة وسيطة إلى {target} (idx={idx}): {e}")

        await asyncio.sleep(0.3)

    try:
        if hasattr(db, "record_published_messages") and sent_ids:
            db.record_published_messages(target, sent_ids, content_type or "photo")
    except Exception:
        pass

    if sent_ids:
        mark_runtime_activity("publish")
        logger.info(f"✅ نُشر {len(sent_ids)} رسالة إلى {target} بدون تحميل")
        return True

    logger.warning(f"⚠️ فشل نشر جميع رسائل الوسيطة إلى {target}")
    return False

async def safe_edit(callback, text, reply_markup=None):
    if len(text) > 4096:
        text = text[:4093] + "..."
    reply_markup = _compact_ui_markup(reply_markup)
    try:
        await callback.edit_message_text(text, reply_markup=reply_markup)
    except MessageNotModified:
        try:
            await callback.answer()
        except Exception:
            pass
    except Exception as e:
        callback_data = getattr(callback, "data", "")
        logger.error(
            "فشل تعديل الرسالة: callback=%r error=%s: %s",
            callback_data,
            type(e).__name__,
            e,
        )
        try:
            await callback.answer("حدث خطأ أثناء تحديث القائمة.", show_alert=True)
        except Exception:
            pass

async def resolve_chat_id(raw, prefer_user=True):
    chat = await resolve_chat_info(raw, prefer_user=prefer_user)
    return int(chat.id)


def normalize_chat_input(raw):
    raw = str(raw).strip()
    match = re.match(r'(?:https?://)?t\.me/([A-Za-z0-9_]+)', raw)
    if match:
        raw = "@" + match.group(1)
    return raw


def split_bulk_lines(text):
    items = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if "," in line and "t.me/" not in line:
            items.extend([p.strip() for p in line.split(",") if p.strip()])
        else:
            items.append(line)
    seen = set()
    unique = []
    for item in items:
        key = normalize_chat_input(item).lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def split_terms_lines(text):
    """يقسم النص إلى عناصر جماعية: كل سطر عنصر، ويدعم الفواصل إذا ما بيها روابط."""
    items = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if "," in line and "http" not in line and "t.me/" not in line:
            items.extend([p.strip() for p in line.split(",") if p.strip()])
        else:
            items.append(line)
    seen = set()
    out = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


async def resolve_chat_info_timeout(raw, prefer_user=True, timeout=8):
    """يجلب معلومات القناة/المصدر بمهلة حتى لا يعلق البوت عند الإضافة."""
    return await asyncio.wait_for(resolve_chat_info(raw, prefer_user=prefer_user), timeout=timeout)


def apply_source_remove_terms(text, source_id):
    """التنظيف الذكي: يحذف عناصر هذا المصدر فقط ولا يمنع المنشور."""
    if not text:
        return text
    try:
        terms = db.get_source_remove_terms(source_id) if hasattr(db, "get_source_remove_terms") else []
    except Exception:
        terms = []
    cleaned = str(text)
    for term in terms:
        cleaned = remove_term_variants(cleaned, term)
    return compact_text(cleaned)


# ===== 🔗 إدارة الروابط — خاصة بكل قناة على حدة =====
CHANNEL_LINK_TG_RE = re.compile(r"(?:https?://)?(?:www\.)?(?:t(?:elegram|lgrm)?\.me|t\.me)/[^\s]+", re.IGNORECASE)
CHANNEL_TG_USERNAME_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{4,32}\b")
CHANNEL_WEB_LINK_RE = re.compile(r"(?:https?://|www\.)[^\s]+", re.IGNORECASE)


def apply_channel_link_filters(text, channel_id):
    """يحذف الروابط حسب إعدادات هذه القناة فقط: روابط تيليجرام / يوزرات @ / روابط المواقع."""
    if not text or channel_id is None:
        return text
    try:
        ch = db.get_channel(channel_id)
    except Exception:
        ch = None
    if not ch:
        return text
    cleaned = str(text)
    if ch.get("link_remove_tg"):
        cleaned = CHANNEL_LINK_TG_RE.sub("", cleaned)
    if ch.get("link_remove_tg_user"):
        cleaned = CHANNEL_TG_USERNAME_RE.sub("", cleaned)
    if ch.get("link_remove_web"):
        cleaned = CHANNEL_WEB_LINK_RE.sub(
            lambda m: m.group(0) if CHANNEL_LINK_TG_RE.match(m.group(0)) else "",
            cleaned,
        )
    return compact_text(cleaned)


# ===== Phase 3 Part 1: advanced filters and cleaning =====
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\u2600-\u27BF"
    "]+",
    flags=re.UNICODE
)

HIDDEN_CHARS_PATTERN = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\u200b\u200c\u200d\ufeff]")


def compact_text(text):
    text = str(text or "")
    text = HIDDEN_CHARS_PATTERN.sub("", text)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def remove_term_variants(text, term):
    """يحذف الكلمة كما هي، وكهاشتاك، ومع تحويل الفراغات إلى _ أو -."""
    if not text or not term:
        return text
    term = str(term).strip()
    if not term:
        return text

    base = term.lstrip("#@").strip()
    variants = {term, base}
    if base:
        variants.add("#" + base)
        variants.add("@" + base)
        variants.add("#" + base.replace(" ", "_"))
        variants.add("#" + base.replace(" ", "-"))
        variants.add(base.replace(" ", "_"))
        variants.add(base.replace(" ", "-"))

    cleaned = str(text)
    for variant in sorted(variants, key=len, reverse=True):
        if not variant:
            continue
        pattern = re.escape(variant)
        # حدود مرنة حتى لا تلتصق الكلمات بباقي النص
        cleaned = re.sub(r"(?<!\w)" + pattern + r"(?!\w)", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace(variant, "")
    return cleaned


def _is_emoji_char(ch):
    """كشف واسع للإيموجي بدون الاعتماد فقط على Regex حتى تُحذف الرموز المركبة أيضاً."""
    if not ch:
        return False
    code = ord(ch)

    # Unicode emoji blocks + رموز BMP التي تُعرض كإيموجي مع variation selector.
    if (
        0x1F1E6 <= code <= 0x1F1FF or  # flags
        0x1F300 <= code <= 0x1FAFF or  # emoji/symbols/pictographs
        0x2600 <= code <= 0x27BF or    # misc symbols/dingbats
        0x2300 <= code <= 0x23FF or    # technical symbols (⌚ ⏰ ⏩ ...)
        0x2190 <= code <= 0x21FF or    # arrows
        0x2B00 <= code <= 0x2BFF or    # arrows/stars/shapes
        code in {
            0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139,
            0x3030, 0x303D, 0x3297, 0x3299,
        }
    ):
        return True

    # أجزاء الإيموجي المركبة: ألوان/تعديل لون الجلد/variation/keycap/tag chars.
    if (
        0xFE00 <= code <= 0xFE0F or
        0x1F3FB <= code <= 0x1F3FF or
        code == 0x20E3 or
        0xE0020 <= code <= 0xE007F
    ):
        return True

    return False


def remove_emoji_chars(text):
    if not text:
        return text
    cleaned = EMOJI_PATTERN.sub("", str(text))
    cleaned = "".join(ch for ch in cleaned if not _is_emoji_char(ch))
    return compact_text(cleaned)


def programmatic_clean_text(text):
    """تنظيف برمجي عام بدون الاعتماد على أي سيرفر خارجي."""
    if not text:
        return text
    cleaned = html.unescape(str(text))
    cleaned = cleaned.replace("&quot;", "").replace("&rlm;", "").replace("&lrm;", "").replace("&nbsp;", " ")
    cleaned = HIDDEN_CHARS_PATTERN.sub("", cleaned)
    return compact_text(cleaned)


def apply_global_remove_terms(text):
    if not text:
        return text
    try:
        terms = db.get_global_remove_terms() if hasattr(db, "get_global_remove_terms") else []
    except Exception:
        terms = []
    cleaned = str(text)
    for term in terms:
        cleaned = remove_term_variants(cleaned, term)
    return compact_text(cleaned)


def apply_channel_remove_terms(text, channel_id):
    """يطبّق قائمة الحذف الخاصة بقناة نشر معيّنة فقط (مستقلة عن باقي القنوات)."""
    if not text or channel_id is None:
        return text
    try:
        terms = db.get_channel_delete_terms(channel_id) if hasattr(db, "get_channel_delete_terms") else []
    except Exception:
        terms = []
    cleaned = str(text)
    for term in terms:
        cleaned = remove_term_variants(cleaned, term)
    return compact_text(cleaned)


def prepare_dedup_text(text, source_id=None, channel_id=None):
    """يجهز النص للمقارنة بعد كلمات الحذف وقبل قالب النشر.
    الكلمات المحظورة تُفحص قبل استدعاء هذه الدالة، ولا تستخدم أي AI."""
    cleaned = full_clean_text(text, source_id=source_id)
    cleaned = apply_global_remove_terms(cleaned)
    cleaned = apply_channel_remove_terms(cleaned, channel_id)
    return compact_text(cleaned)


def full_clean_text(text, source_id=None):
    if not text:
        return text
    cleaned = str(text)

    # قراءة إعداد حذف الإيموجي مرة واحدة فقط لتجنب استعلامات متكررة
    should_remove_emoji = False
    if source_id is not None:
        try:
            if hasattr(db, "get_source_remove_emoji"):
                should_remove_emoji = bool(db.get_source_remove_emoji(source_id))
        except Exception:
            pass

    if source_id is not None:
        cleaned = apply_source_remove_terms(cleaned, source_id)
        if should_remove_emoji:
            cleaned = remove_emoji_chars(cleaned)

    cleaned = programmatic_clean_text(cleaned)

    if should_remove_emoji:
        cleaned = remove_emoji_chars(cleaned)

    return compact_text(cleaned)


def clean_text_for_source(text, source_id=None, channel_id=None):
    """تنظيف نهائي مرتبط بالمصدر وبالقناة المستهدفة قبل بناء المنشور."""
    cleaned = clean_text(text, source_id=source_id, channel_id=channel_id)
    if cleaned is None:
        return None
    if source_id is not None:
        try:
            if hasattr(db, "get_source_remove_emoji") and db.get_source_remove_emoji(source_id):
                cleaned = remove_emoji_chars(cleaned)
        except Exception:
            pass
    return compact_text(cleaned)



def published_content_type_for_message(message, is_album=False):
    if is_album:
        return "album"
    if getattr(message, "video", None):
        return "video"
    if getattr(message, "photo", None):
        return "photo"
    if getattr(message, "voice", None):
        return "voice"
    if getattr(message, "audio", None):
        return "audio"
    if getattr(message, "document", None):
        return "document"
    if not getattr(message, "media", None):
        return "text"
    return "document"


def content_type_for_message(message, is_album=False):
    if is_album or getattr(message, "media_group_id", None):
        return "album"
    if not getattr(message, "media", None):
        return "text"
    if getattr(message, "photo", None):
        return "photo"
    if getattr(message, "video", None):
        return "video"
    if getattr(message, "voice", None):
        return "voice"
    if getattr(message, "audio", None):
        return "audio"
    if getattr(message, "document", None):
        return "document"
    # أي ميديا غير مصنفة نعاملها كملف حتى لا تُنشر إلا إذا فعلت الملفات بالمصدر
    return "document"


def is_content_allowed_for_source(source_id, content_type):
    try:
        types = db.get_source_content_types(source_id) if hasattr(db, "get_source_content_types") else {}
    except Exception:
        types = {}
    if not types:
        return True
    return bool(types.get(content_type, True))


def is_source_paused(source_id):
    try:
        return bool(db.is_source_paused(source_id)) if hasattr(db, "is_source_paused") else False
    except Exception:
        return False


NEWS_STOPWORDS = {
    "عاجل", "عاجــــــــل", "عــــاجــــل", "حصري", "هام", "تنويه", "الان", "الآن",
    "مصدر", "مصادر", "قال", "قالت", "افاد", "أفاد", "اعلن", "أعلن", "اعلنت", "أعلنت",
    "بيان", "خبر", "متابعة", "مراسل", "وكالة", "قناة", "شبكة", "رسميا", "رسمياً",
    "واشنطن", "ايران", "إيران"  # تُعاد إيران ككلمة معيارية عبر المرادفات أدناه؛ المدن تبقى لهوية الحدث
}

NEWS_SYNONYMS = {
    "الأميركية": "امريكا", "الأمريكية": "امريكا", "امريكية": "امريكا", "أميركية": "امريكا",
    "الامريكية": "امريكا", "امريكا": "امريكا", "أمريكا": "امريكا", "اميركا": "امريكا", "أميركا": "امريكا",
    "الولايات": "امريكا", "المتحدة": "امريكا", "واشنطن": "امريكا",
    "إيران": "ايران", "ايراني": "ايران", "إيراني": "ايران", "الايرانية": "ايران", "الإيرانية": "ايران",
    "مرتبطة": "متعلقة", "متعلق": "متعلقة", "متعلقة": "متعلقة", "تتعلق": "متعلقة",
    "عقوبة": "عقوبات", "العقوبات": "عقوبات", "عقوبات": "عقوبات",
    "الخزانة": "خزانة", "وزارة": "وزارة",
}

def normalize_for_similarity(text):
    """بصمة إخبارية أقوى لمنع تكرار نفس الخبر بصياغات مختلفة."""
    cleaned = full_clean_text(text or "")
    cleaned = remove_emoji_chars(cleaned)
    cleaned = re.sub(r"[^\w\s\u0600-\u06FF]", " ", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    words = []
    for raw in cleaned.split():
        w = raw.strip("_-ـ")
        if not w or len(w) < 2:
            continue
        # إزالة مدود عاجل وأشكال الزخرفة
        w = re.sub(r"ـ+", "", w)
        w = NEWS_SYNONYMS.get(w, w)
        if w in NEWS_STOPWORDS:
            continue
        if w in {"ال", "في", "من", "على", "الى", "إلى", "عن", "مع", "هذا", "هذه", "ذلك", "تلك"}:
            continue
        words.append(w)
    # نزيل التكرار مع الحفاظ على الترتيب
    seen = set()
    unique = []
    for w in words:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return " ".join(unique)

def make_text_fp(text):
    normalized = normalize_for_similarity(text)
    if not normalized:
        return "", normalized
    return hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest(), normalized


def make_similarity_fp(text):
    fp, normalized = make_text_fp(text)
    if len(normalized) < 20:
        return "", normalized
    return fp, normalized


def make_event_fp(text):
    """Stable local event fingerprint: normalized news tokens, not wording."""
    normalized = normalize_for_similarity(text)
    tokens = [token for token in normalized.split() if len(token) >= 3 or token.isdigit()]
    if len(tokens) < 3:
        return ""
    return hashlib.sha1(" ".join(sorted(set(tokens))).encode("utf-8", errors="ignore")).hexdigest()


def make_url_fp(text):
    urls = re.findall(r"https?://[^\s<>]+", str(text or ""), flags=re.IGNORECASE)
    if not urls:
        return ""
    clean_urls = sorted({url.rstrip(".,،؛:!?)]}'\"") for url in urls})
    return hashlib.sha1("\n".join(clean_urls).encode("utf-8", errors="ignore")).hexdigest()


def _event_overlap(left, right):
    left_tokens = set(str(left or "").split())
    right_tokens = set(str(right or "").split())
    if len(left_tokens) < 3 or len(right_tokens) < 3:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))


def _event_core_tokens(text):
    """يبني مجموعة كلمات حدث حتمية لمطابقة الصياغات العربية المختصرة.
    لا يعتمد على AI ولا يساوي بين خبرين لمجرد اشتراكهما بكلمة عامة."""
    stopwords = {
        "من", "في", "عن", "على", "الى", "إلى", "مع", "هذا", "هذه", "ذلك", "تلك",
        "الذي", "التي", "تم", "قد", "كما", "بعد", "قبل", "اليوم", "غدا", "غدًا",
        "اعلن", "أعلن", "تعلن", "يعلن", "أعلنت", "قال", "تقول", "ذكر", "حول", "ضمن",
        "بشأن", "بخصوص", "و", "أو", "او", "ثم", "أن", "ان", "إن", "وذلك",
    }
    tokens = set()
    for token in normalize_for_similarity(text).split():
        token = token.strip(".,،؛:!?()[]{}\"'")
        if len(token) < 3 or token in stopwords:
            continue
        variants = {token}
        if token.startswith("ال") and len(token) > 4:
            variants.add(token[2:])
        # توحيد لواصق عربية شائعة داخل هوية الحدث: للعراق/العراق → عراق.
        if token.startswith("لل") and len(token) > 4:
            variants.add(token[2:])
        if token.startswith("و") and len(token) > 4:
            variants.add(token[1:])
        if token.endswith("ية") and len(token) > 5:
            variants.add(token[:-2])
        tokens.update(variants)
    return tokens


def _event_identity_score(left, right):
    """درجة تغطية كلمات الحدث المشتركة؛ الصفر يعني عدم كفاية الهوية."""
    left_core = _event_core_tokens(left)
    right_core = _event_core_tokens(right)
    if len(left_core) < 3 or len(right_core) < 3:
        return 0.0
    shared = left_core & right_core
    if len(shared) < 3:
        return 0.0
    return len(shared) / max(1, min(len(left_core), len(right_core)))


def _event_numbers(text):
    return set(re.findall(r"(?<!\w)\d+(?:[.,]\d+)?", str(text or "")))


def _event_details_differ(left, right):
    left_numbers = _event_numbers(left)
    right_numbers = _event_numbers(right)
    return bool(left_numbers and right_numbers and left_numbers != right_numbers)


def _ai_decide_gray_zone(normalized, sample):
    """حسم المنطقة الرمادية عبر AI عند الحاجة وفقط إذا كانت مفاتيح AI مفعلة.
    يرجع True إذا قرر AI أنها نفس الحدث. يُستدعى فقط في المنطقة الرمادية
    (similarity بين 0.60 و0.75) ولا يستهلك رموزاً لأي منشور مرفوض مسبقاً."""
    try:
        if not (hasattr(db, "get_all_ai_keys") and db.get_all_ai_keys()):
            return False
        setting = False
        if hasattr(db, "get_setting"):
            try:
                setting = bool(db.get_setting("ai_gray_zone_dedup", False))
            except Exception:
                setting = False
        if not setting:
            return False
        prompt = (
            "هل هذان النصان الإخباريان يتحدثان عن نفس الحدث المحدث؟ أجب بـ yes أو no فقط.\n"
            f"النص الأول: {normalized[:300]}\nالنص الثاني: {sample[:300]}"
        )
        import urllib.request as _ur
        import urllib.parse as _up
        import json as _j2
        ai_calls = globals().get("_p27_ai_call_count", 0)
        globals()["_p27_ai_call_count"] = ai_calls + 1
        for k in db.get_all_ai_keys():
            try:
                key = k.get("key") or k.get("api_key")
                provider = (k.get("provider") or "").lower()
                if not key:
                    continue
                if provider.startswith("gemini") and hasattr(db, "get_ai_key"):
                    try:
                        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=" + _up.quote(str(key), safe="")
                        body = {"contents": [{"parts": [{"text": prompt}]}]}
                        req = _ur.Request(url, data=_j2.dumps(body).encode(), headers={"Content-Type": "application/json"})
                        with _ur.urlopen(req, timeout=20) as r:
                            resp = _j2.loads(r.read().decode())
                        text = resp.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").lower()
                        return "yes" in text
                    except Exception:
                        continue
            except Exception:
                continue
        return False
    except Exception:
        return False


def is_hybrid_news_duplicate(text, source_id=None, message_id=None, threshold=0.75, scope_id=None):
    """Dedup مشترك حسب القسم (scope_id) — المقارنة فقط مع الأخبار المقبولة والمنشورة
    فعلياً في نفس القسم خلال آخر 48 ساعة.
    تسلسل الطبقات: Exact → URL → Event → Similarity → Event Overlap → AI للمنطقة الرمادية."""
    text_fp, normalized = make_text_fp(text)
    event_fp = make_event_fp(text)
    url_fp = make_url_fp(text)
    if not text_fp:
        return False, "none", 0.0
    try:
        if source_id is not None and message_id is not None and hasattr(db, "has_recent_source_event"):
            if db.has_recent_source_event(source_id, message_id):
                return True, "source_event", 1.0
        recent = db.get_recent_fingerprints(scope_id=scope_id) if hasattr(db, "get_recent_fingerprints") else []
    except Exception:
        recent = []
    best = 0.0
    details_differ = False
    for item in recent[-300:]:
        if not isinstance(item, dict):
            continue
        # 1. Exact
        if item.get("fp") == text_fp:
            return True, "exact", 1.0
        # 2. URL
        if url_fp and item.get("url_fp") == url_fp:
            return True, "url", 1.0
        # 3. Event
        if event_fp and item.get("event_fp") == event_fp:
            return True, "event", 1.0
        sample = item.get("sample", "")
        if not sample or len(normalized) < 20:
            continue
        ratio = difflib.SequenceMatcher(None, normalized, sample).ratio()
        best = max(best, ratio)
        # اختلاف التفاصيل/الأرقام المهمة يمنع الحكم Duplicate
        if _event_details_differ(normalized, sample):
            details_differ = True
            continue
        # مطابقة حتمية لهوية الحدث للصياغات المختصرة، قبل أي AI.
        event_identity_score = _event_identity_score(normalized, sample)
        if event_identity_score >= 0.75:
            return True, "event_identity", event_identity_score
        if ratio >= threshold:
            stored_event_fp = item.get("event_fp", "")
            if event_fp and stored_event_fp and stored_event_fp != event_fp:
                details_differ = True
                continue
            return True, "similarity", ratio
        # 4. Event Overlap — لا يجوز حكماً منفرداً: يتطلب تطابق event_fp
        stored_event_fp = item.get("event_fp", "")
        if (
            0.60 <= ratio < threshold
            and _event_overlap(normalized, sample) >= 0.70
            and event_fp
            and stored_event_fp
            and stored_event_fp == event_fp
        ):
            return True, "event_overlap", ratio
        # 5. المنطقة الرمادية → AI للحسم عند الحاجة فقط
        if 0.60 <= ratio < threshold and event_fp and stored_event_fp and stored_event_fp == event_fp:
            try:
                if _ai_decide_gray_zone(normalized, sample):
                    return True, "ai_gray_zone", ratio
            except Exception:
                pass
    return False, "event_details_differ" if details_differ else "none", best

def check_section_claim(scope_id, event_fp):
    """حجز ذري على مستوى القسم: أول وصول يفوز، والباقي مرفوض Duplicate (TOCTOU protected)."""
    if scope_id is None or event_fp is None:
        return True
    try:
        if hasattr(db, "claim_section_event"):
            return bool(db.claim_section_event(scope_id, event_fp))
    except Exception:
        pass
    return True


def is_smart_duplicate(text, threshold=0.75):
    """Legacy similarity-only helper retained for media/caption compatibility."""
    fp, normalized = make_similarity_fp(text)
    if not fp:
        return False, 0.0
    try:
        recent = db.get_recent_fingerprints() if hasattr(db, "get_recent_fingerprints") else []
    except Exception:
        recent = []
    best = 0.0
    for item in recent[-300:]:
        sample = item.get("sample", "") if isinstance(item, dict) else ""
        if not sample:
            continue
        ratio = difflib.SequenceMatcher(None, normalized, sample).ratio()
        best = max(best, ratio)
        if ratio >= threshold:
            return True, ratio
    return False, best


def remember_published_text(text, source_id=None, message_id=None, scope_id=None, section_label=None):
    fp, normalized = make_text_fp(text)
    if fp and hasattr(db, "add_recent_fingerprint"):
        try:
            db.add_recent_fingerprint(
                fp,
                normalized,
                source_id=source_id,
                message_id=message_id,
                event_fp=make_event_fp(text),
                url_fp=make_url_fp(text),
                scope_id=scope_id,
                section_label=section_label,
            )
        except Exception:
            pass


def content_types_status_line(source_id):
    labels = {"text": "نصوص", "photo": "صور", "video": "فيديو", "album": "ألبومات", "voice": "بصمات", "audio": "صوتيات", "document": "ملفات"}
    try:
        types = db.get_source_content_types(source_id) if hasattr(db, "get_source_content_types") else {}
    except Exception:
        types = {}
    if not types:
        types = {"text": True, "photo": True, "video": True, "album": True}
    return " | ".join(("✅ " if types.get(k, True) else "❌ ") + v for k, v in labels.items())



async def resolve_chat_info(raw, prefer_user=True):
    raw = normalize_chat_input(raw)
    value = int(raw) if re.fullmatch(r"-?\d+", raw) else raw
    clients = [user_client, bot_client] if prefer_user else [bot_client, user_client]
    last_error = None
    for c in [x for x in clients if x]:
        try:
            return await c.get_chat(value)
        except Exception as e:
            last_error = e
    raise last_error or ValueError("تعذر جلب معلومات القناة")


def chat_title(chat, fallback=""):
    return getattr(chat, "title", None) or getattr(chat, "first_name", None) or getattr(chat, "username", None) or str(fallback)


def chat_username(chat):
    return getattr(chat, "username", None) or ""


def chat_link_from_username(username):
    return f"https://t.me/{username}" if username else ""


def chat_type_name(chat):
    return str(getattr(chat, "type", "")).replace("ChatType.", "")


def chat_meta(chat, fallback=""):
    username = chat_username(chat)
    title = chat_title(chat, fallback)
    return {
        "name": title,
        "title": title,
        "username": username,
        "link": chat_link_from_username(username),
        "chat_type": chat_type_name(chat),
    }


def entity_name(record_or_id, is_source=False):
    if isinstance(record_or_id, dict):
        return record_or_id.get("title") or record_or_id.get("name") or record_or_id.get("username") or str(record_or_id.get("id", ""))
    if is_source and hasattr(db, "get_source_meta"):
        return entity_name(db.get_source_meta(record_or_id))
    return str(record_or_id)


def entity_details_line(item, is_source=False):
    if is_source:
        meta = db.get_source_meta(item) if not isinstance(item, dict) else item
        item_id = meta.get("id", item)
    else:
        meta = item
        item_id = item.get("id")
    name = entity_name(meta)
    username = meta.get("username") or ""
    username_txt = f"@{username}" if username else "لا يوجد يوزر"
    return f"• {name}\n  {username_txt}\n  ID: `{item_id}`"


async def show_public_sources_menu_from_message(message):
    srcs = db.get_public_sources()
    meta_list = db.get_all_public_sources_with_meta() if hasattr(db, "get_all_public_sources_with_meta") else [{"id": s, "name": str(s)} for s in srcs]
    text = f"**المصادر العامة ({len(srcs)}):**\n➕ إضافة مصدر/مصادر: يضيف قنوات عامة جديدة يراقبها البوت (رابط/يوزر/ID).\n🗑 حذف مصدر عام: يحذف مصدراً عاماً من المراقبة."
    text += "\n\n".join(entity_details_line(m, is_source=True) for m in meta_list) if srcs else "لا توجد."
    buttons = [
        [InlineKeyboardButton("➕ إضافة مصدر/مصادر", callback_data="add_public_src")],
        [InlineKeyboardButton("🗑 حذف مصدر عام", callback_data="del_public_src")],
        nav_row("main_menu"),
    ]
    await message.reply(text, reply_markup=InlineKeyboardMarkup(buttons))


async def show_blocked_words_menu_from_message(message):
    words = db.get_blocked_words()
    text = "**الكلمات المحظورة:**\n" + (", ".join(words) if words else "لا توجد.") + "\n➕ إضافة كلمة: يمنع نشر أي منشور يحتوي هذه الكلمة.\n🗑 حذف كلمة: يزيل كلمة من القائمة المحظورة."
    buttons = [
        [InlineKeyboardButton("➕ إضافة كلمة", callback_data="add_blocked_word")],
        [InlineKeyboardButton("🗑 حذف كلمة", callback_data="del_blocked_word")],
        nav_row("main_menu"),
    ]
    await message.reply(text, reply_markup=InlineKeyboardMarkup(buttons))


async def show_special_sources_menu_from_message(message, ch_id):
    ch = db.get_channel(ch_id)
    if not ch:
        await message.reply("❌ القناة غير موجودة.")
        return
    sources = ch.get("special_sources", [])
    text = "**المصادر المخصصة:**\n➕ إضافة: يضيف مصدراً خاصاً لهذه القناة فقط.\n🗑 حذف: يزيل مصدراً خاصاً."
    text += "\n".join(f"• {entity_name(s, is_source=True)}\n  ID: `{s}`" for s in sources) if sources else "لا توجد."
    buttons = [
        [InlineKeyboardButton("➕ إضافة", callback_data=f"addspecsrc_{ch_id}")],
        [InlineKeyboardButton("🗑 حذف", callback_data=f"delspecsrc_{ch_id}")],
        nav_row(f"ch_{ch_id}"),
    ]
    await message.reply(text, reply_markup=InlineKeyboardMarkup(buttons))


def format_bulk_report(title, results):
    ok = [r for r in results if r[0] == "ok"]
    exists = [r for r in results if r[0] == "exists"]
    failed = [r for r in results if r[0] == "fail"]
    lines = [title, "", f"✅ تمت الإضافة: {len(ok)}", f"⚠️ موجود مسبقاً: {len(exists)}", f"❌ فشل: {len(failed)}"]
    if ok:
        lines.append("\n**المضافة:**")
        lines.extend([f"• {name}" for _, name, _ in ok[:30]])
    if exists:
        lines.append("\n**الموجودة مسبقاً:**")
        lines.extend([f"• {name}" for _, name, _ in exists[:20]])
    if failed:
        lines.append("\n**الفاشلة:**")
        lines.extend([f"• {raw}: {err}" for _, raw, err in failed[:20]])
    return "\n".join(lines)

main_keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("📢 إدارة قنوات النشر", callback_data="menu_channels"),
        InlineKeyboardButton("🌐 إدارة المصادر العامة", callback_data="menu_public_src")
    ],
    [
        InlineKeyboardButton("💾 الاستيراد / التصدير", callback_data="backup_menu"),
        InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")
    ],
    [
        InlineKeyboardButton("🖥️ النظام", callback_data="system_menu"),
        InlineKeyboardButton("🔐 الأسرار", callback_data="secrets_menu")
    ],
    [
        InlineKeyboardButton("📰 الأخبار", callback_data="section_menu|news"),
        InlineKeyboardButton("⚽ الرياضة", callback_data="section_menu|sports"),
    ],
    [
        InlineKeyboardButton("🌐 Blogger Publisher", callback_data="section_menu|blogger")
    ]
])


async def section_menu(client, callback):
    """Unified Phase-15 controls; legacy Blogger callbacks remain untouched."""
    try:
        section = str(callback.data).split("|", 1)[1]
    except Exception:
        await callback.answer("قسم غير صالح.", show_alert=True)
        return
    runtime, control = _get_p29_runtime()
    state = runtime.get_section_state(section)
    buttons = [
        [
            InlineKeyboardButton("⚙️ الإعدادات", callback_data=f"{section}:settings"),
            InlineKeyboardButton("📡 المصادر", callback_data=f"{section}:sources"),
        ],
        [
            InlineKeyboardButton("🚫 الكلمات المحظورة", callback_data=f"{section}:blocked"),
            InlineKeyboardButton("♻️ منع التكرار", callback_data=f"{section}:duplicates"),
        ],
        [
            InlineKeyboardButton("🤖 الذكاء الاصطناعي", callback_data=f"{section}:ai"),
            InlineKeyboardButton("📋 الطابور", callback_data=f"{section}:queue"),
        ],
        [
            InlineKeyboardButton("📊 الحالة", callback_data=f"{section}:status"),
            InlineKeyboardButton("🛠️ الإصلاح التلقائي", callback_data=f"{section}:repair"),
        ],
        [
            InlineKeyboardButton("▶️ تشغيل", callback_data=f"{section}:enable"),
            InlineKeyboardButton("⛔ إيقاف", callback_data=f"{section}:disable"),
        ],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="main_menu")],
    ]
    text = (
        f"**{section.upper()} — Phase 15**\n\n"
        f"الحالة: {'🟢 تعمل' if state['enabled'] else '🔴 متوقفة'}\n"
        f"AI: {'🟢' if state['ai_enabled'] else '🔴'}\n"
        f"منع التكرار: {'🟢' if state['duplicate_protection'] else '🔴'}\n"
        f"Auto-Repair: {'🟢' if state['auto_repair_enabled'] else '🔴'}"
    )
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))

async def section_control_callback(client, callback):
    runtime, control = _get_p29_runtime()
    result = control.handle(str(callback.data), getattr(callback.from_user, "id", None))
    if not result.get("ok"):
        await callback.answer(str(result.get("reason", "فشل")), show_alert=True)
        return
    await callback.answer("تم.")
    section = str(callback.data).split(":", 1)[0]
    callback.data = f"section_menu|{section}"
    await section_menu(client, callback)

async def backup_menu(client, callback):
    text = "**💾 الاستيراد / التصدير**\n\n📥 تصدير البيانات: ينزّل ملفاً يحتوي كل إعدادات البوت.\n📤 استيراد البيانات: يرفع ملف إعدادات سابقاً لاستعادة البوت."
    buttons = [
        [
            InlineKeyboardButton("📥 تصدير البيانات", callback_data="export_data"),
            InlineKeyboardButton("📤 استيراد البيانات", callback_data="import_data")
        ],
        nav_row("main_menu")
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def start(client, message):
    user_id = message.from_user.id
    user_states.pop(user_id, None)

    logger.info(f"📥 /start من ID: {user_id}")

    if not is_admin(user_id):
        await message.reply(f"❌ غير مصرح. معرفك: `{user_id}`")
        return

    await message.reply("أهلاً بك في لوحة تحكم البوت:", reply_markup=main_keyboard)

async def export_callback(client, callback):
    try:
        data_str = db.export_data()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as tmp:
            tmp.write(data_str)
            tmp_path = tmp.name

        await callback.message.reply_document(document=tmp_path, file_name=f"backup_{int(time.time())}.json")
        os.unlink(tmp_path)
        await callback.answer("تم إرسال ملف النسخة الاحتياطية.")
    except Exception as e:
        logger.error(f"فشل التصدير: {e}")
        await callback.answer("فشل التصدير.", show_alert=True)

async def import_callback(client, callback):
    user_states[callback.from_user.id] = {"state": "waiting_import"}
    await safe_edit(callback, "أرسل ملف JSON الذي تريد استيراده:")

async def handle_import(client, message):
    if not is_admin(message.from_user.id):
        return

    uid = message.from_user.id

    if uid not in user_states or user_states[uid].get("state") != "waiting_import":
        return

    if not message.document:
        await message.reply("❌ أرفق ملف JSON صحيح.")
        return

    try:
        file_path = await message.download()
        with open(file_path, "r", encoding="utf-8") as f:
            data = f.read()

        result = db.import_data(data)
        if isinstance(result, dict):
            report = (
                "✅ تم استيراد الإعدادات بنجاح.\n\n"
                f"• قنوات النشر: {result.get('channels', 0)}\n"
                f"• المصادر العامة: {result.get('public_sources', 0)}\n"
                f"• الكلمات المحظورة: {result.get('blocked_words', 0)}\n"
                f"• قائمة الحذف العامة: {result.get('global_remove_terms', 0)}\n"
                f"• إعدادات المصادر: {result.get('source_meta', 0)}\n"
                f"• آخر رسائل المصادر: {result.get('last_source_messages', 0)}"
            )
        else:
            report = "✅ تم استيراد الإعدادات بنجاح."
        await message.reply(report + "\n\n🔄 جارٍ تهيئة القنوات والمصادر بعد الاستيراد...", reply_markup=main_keyboard)
        try:
            await warm_all_peers_after_import()
            await message.reply("✅ تمت تهيئة القنوات والمصادر بعد الاستيراد. المفروض النشر يشتغل بدون إعادة إضافة يدوية.")
        except Exception as e:
            logger.error(f"فشل تهيئة الاستيراد: {e}")
            await message.reply(f"⚠️ تم الاستيراد، لكن فشلت التهيئة التلقائية: {e}")
    except Exception as e:
        await message.reply(f"❌ فشل الاستيراد: {e}")
    finally:
        user_states.pop(uid, None)


CONTENT_TYPE_LABELS = {
    "text": "النصوص",
    "photo": "الصور",
    "video": "الفيديوهات",
    "album": "الألبومات",
}


async def purge_published_prompt(client, callback):
    try:
        _, ch_id, kind = callback.data.split("|", 2)
    except Exception:
        await callback.answer("طلب غير صالح.", show_alert=True)
        return
    label = CONTENT_TYPE_LABELS.get(kind, kind)
    ids = db.get_published_message_ids(ch_id, kind) if hasattr(db, "get_published_message_ids") else []
    ch = db.get_channel(ch_id)
    text = (
        f"⚠️ **تأكيد حذف {label} من قناة النشر**\n\n"
        f"{channel_display_name(ch_id)}\n\n"
        f"عدد الرسائل المسجلة للحذف: {len(ids)}\n\n"
        "سيحذف البوت فقط الرسائل التي يعرف IDs مالتهن والمنشورة بعد إضافة هذا النظام."
    )
    buttons = [
        [InlineKeyboardButton(f"✅ نعم، احذف {label}", callback_data=f"confirmpurge|{ch_id}|{kind}")],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"purgepage_{ch_id}")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def _try_delete_with_bots(ch_id, mids):
    """محاولة الحذف باستخدام البوت الأساسي ثم البوتات المخصصة للقناة."""
    deleted_ids = []
    failed_ids = []
    bots_to_try = [bot_client]
    cfg = db.get_channel_config(ch_id) if hasattr(db, "get_channel_config") else {}
    for bid in cfg.get("assigned_bots", []):
        token = db.bot_manager.get_token(bid) if hasattr(db, "bot_manager") else (db.get_publishing_bot(bid) or {}).get("token", "")
        bdata = db.get_publishing_bot(bid) if hasattr(db, "get_publishing_bot") else None
        if token:
            bots_to_try.append({"id": bid, "token": token, **(bdata or {})})
    remaining = list(mids)
    for bot in bots_to_try:
        if not remaining:
            break
        if isinstance(bot, dict):
            token = db.bot_manager.get_token(bot.get("id", "")) if hasattr(db, "bot_manager") else bot.get("token", "")
            try:
                temp = Client(":memory:", api_id=config.API_ID, api_hash=config.API_HASH, bot_token=token, in_memory=True)
                await temp.start()
                for mid in remaining:
                    try:
                        await temp.delete_messages(int(ch_id), int(mid))
                        deleted_ids.append(mid)
                    except Exception:
                        failed_ids.append(mid)
                    await asyncio.sleep(0.2)
                await temp.stop()
            except Exception:
                failed_ids.extend(remaining)
            remaining = [m for m in remaining if m not in deleted_ids]
        else:
            for i in range(0, len(remaining), 100):
                chunk = remaining[i:i+100]
                try:
                    await bot.delete_messages(int(ch_id), chunk)
                    deleted_ids.extend(chunk)
                except Exception:
                    for mid in chunk:
                        try:
                            await bot.delete_messages(int(ch_id), int(mid))
                            deleted_ids.append(mid)
                        except Exception as e:
                            failed_ids.append(mid)
                await asyncio.sleep(0.3)
            remaining = [m for m in remaining if m not in deleted_ids]
    return deleted_ids, failed_ids


async def confirm_purge_published(client, callback):
    try:
        _, ch_id, kind = callback.data.split("|", 2)
    except Exception:
        await callback.answer("طلب غير صالح.", show_alert=True)
        return
    ids = db.get_published_message_ids(ch_id, kind) if hasattr(db, "get_published_message_ids") else []
    if not ids:
        await callback.answer("لا توجد رسائل محفوظة من هذا النوع.", show_alert=True)
        await post_settings_menu(client, callback)
        return

    # تحقق فوري من صلاحية الحذف قبل التنفيذ
    if not await _verify_channel_before_publish(ch_id):
        await safe_edit(callback, f"⛔ **فشل التحقق من القناة**\n\nالبوت الرئيسي لا يمكنه الوصول إلى القناة `{ch_id}`.\nتأكد من أن البوت مشرف في القناة.", InlineKeyboardMarkup([nav_row(f"ch_{ch_id}")]))
        return

    deleted_ids, failed_ids = await _try_delete_with_bots(ch_id, ids)

    if hasattr(db, "clear_published_message_ids"):
        db.clear_published_message_ids(ch_id, kind, None if not failed_ids else deleted_ids)

    label = CONTENT_TYPE_LABELS.get(kind, kind)
    deleted = len(deleted_ids)
    failed = len(failed_ids)
    await notify_admins(f"تم حذف {label} من {channel_display_name(ch_id)}\n✅ المحذوف: {deleted}\n❌ فشل: {failed}")
    await safe_edit(callback, f"🧹 **نتيجة حذف {label}:**\n\n✅ تم حذف: {deleted}\n❌ فشل: {failed}\n\n💡 البوت لا يمكنه حذف رسائل أقدم من 48 ساعة (حد Telegram).", InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع لحذف المنشورات", callback_data=f"purgepage_{ch_id}"), InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ]))


def channel_buttons(ch_id):
    buttons = [
        InlineKeyboardButton("📰 إعدادات المنشورات", callback_data=f"postset_{ch_id}"),
        InlineKeyboardButton("📡 المصادر", callback_data=f"srcset_{ch_id}"),
        InlineKeyboardButton("⚙️ الإعدادات العامة", callback_data=f"genset_{ch_id}"),
    ]
    rows = grid_buttons(buttons, 2)
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="menu_channels"), InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


# ============================================================
# 📝 إعدادات المنشورات
# ============================================================

async def post_settings_menu(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("غير موجودة.")
        return
    bold = ch.get("bold_publish", True)
    quote_types = get_channel_quote_types_safe(ch_id)
    cfg = db.get_channel_config(ch_id) if hasattr(db, "get_channel_config") else {}
    quote_count = sum(1 for v in quote_types.values() if v) + int(bool(cfg.get("title_quote"))) + int(bool(cfg.get("signature_quote")))
    disable_preview = db.get_channel_disable_preview(ch_id) if hasattr(db, "get_channel_disable_preview") else False
    ignore_short = is_ignore_short_posts_enabled_for_channel(ch_id)
    buttons = [
        InlineKeyboardButton(f"{'✅' if bold else '❌'} الخط السميك", callback_data=f"togglebold_{ch_id}"),
        InlineKeyboardButton(
            f"📝 النصوص القصيرة: {'✅ تشغيل' if ignore_short else '❌ إيقاف'}",
            callback_data=f"toggle_short_posts|{ch_id}",
        ),
        InlineKeyboardButton(f"✍️ التوقيع", callback_data=f"tails_{ch_id}"),
        InlineKeyboardButton(f"💬 الاقتباس ({quote_count}/6)", callback_data=f"quotemenu_{ch_id}"),
        InlineKeyboardButton(f"#️⃣ الهاشتاكات", callback_data=f"hashtags_{ch_id}"),
        InlineKeyboardButton(f"⏱ سرعة النشر", callback_data=f"speedmenu_{ch_id}"),
        InlineKeyboardButton(f"🗑 حذف المنشورات", callback_data=f"purgepage_{ch_id}"),
        InlineKeyboardButton(f"🚫 الكلمات المحظورة", callback_data=f"chwords|{ch_id}"),
        InlineKeyboardButton(f"✂️ الكلمات المحذوفة", callback_data=f"chdelterms|{ch_id}"),
        InlineKeyboardButton(f"🔗 إدارة الروابط", callback_data=f"chlinks|{ch_id}"),
        InlineKeyboardButton(f"{'✅' if not disable_preview else '❌'} معاينة الروابط", callback_data=f"ch_preview_{ch_id}"),
        InlineKeyboardButton("🧪 اختبار القناة", callback_data=f"testset_{ch_id}"),
    ]
    rows = grid_buttons(buttons, 2)
    rows.append(nav_row(f"ch_{ch_id}"))
    await safe_edit(callback, f"📰 **إعدادات المنشورات**\n{entity_name(ch)}\n📝 النصوص القصيرة: " + ("✅ الحظر مفعّل" if ignore_short else "❌ متوقف") + "\n💬 الاقتباسات: {quote_count}/6 أنواع مفعّلة\n" + "🔗 معاينة الروابط: " + ("✅ مفعّلة" if not disable_preview else "❌ معطّلة") + "\n" + "📌 الخط السميك: " + ("✅ مفعّل" if bold else "❌ معطّل") + "\n", InlineKeyboardMarkup(rows))


async def purge_published_menu(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("غير موجودة.")
        return
    buttons = [
        InlineKeyboardButton("🧹 حذف النصوص", callback_data=f"purgepub|{ch_id}|text"),
        InlineKeyboardButton("🧹 حذف الصور", callback_data=f"purgepub|{ch_id}|photo"),
        InlineKeyboardButton("🧹 حذف الفيديوهات", callback_data=f"purgepub|{ch_id}|video"),
        InlineKeyboardButton("🧹 حذف الألبومات", callback_data=f"purgepub|{ch_id}|album"),
    ]
    rows = grid_buttons(buttons, 2)
    rows.append(nav_row(f"postset_{ch_id}"))
    await safe_edit(callback, f"🗑 **حذف المنشورات**\n{channel_display_name(ch_id)}\n\nاختر نوع المنشورات المسجلة لحذفها من القناة:\n\n🧹 حذف النصوص/الصور/الفيديوهات/الألبومات: يحذف الرسائل المسجلة من هذا النوع في هذه القناة فقط.", InlineKeyboardMarkup(rows))


# ============================================================
# 📚 إعدادات المصادر
# ============================================================

async def source_settings_channel_menu(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("غير موجودة.")
        return
    sources = ch.get("special_sources", [])
    buttons = [
        InlineKeyboardButton(f"📢 عرض المصادر ({len(sources)})", callback_data=f"specsrc_{ch_id}"),
        InlineKeyboardButton("➕ إضافة مصدر", callback_data=f"addspecsrc_{ch_id}"),
        InlineKeyboardButton("➖ حذف مصدر", callback_data=f"delspecsrc_{ch_id}"),
        InlineKeyboardButton("📋 جميع المصادر", callback_data="menu_public_src"),
    ]
    rows = grid_buttons(buttons, 2)
    rows.append(nav_row(f"ch_{ch_id}"))
    text = (
        f"📚 **إعدادات المصادر**\n{entity_name(ch)}\n\n"
        f"عدد المصادر المخصصة: {len(sources)}\n\n📢 عرض المصادر: يعرض قائمة المصادر المخصصة.\n➕ إضافة/➖ حذف: إدارة المصادر المخصصة."
    )
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


# ============================================================
# 🔖 إعدادات التوقيع
# ============================================================

async def tail_settings_menu(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("غير موجودة.")
        return
    tail_enabled = db.get_channel_tail_enabled(ch_id) if hasattr(db, "get_channel_tail_enabled") else True
    tail_min = db.get_channel_tail_min_words(ch_id) if hasattr(db, "get_channel_tail_min_words") else 20
    tail_pos = db.get_channel_tail_position(ch_id) if hasattr(db, "get_channel_tail_position") else "bottom"
    current_tail = ch.get("tail", "")
    min_active = tail_min >= 20
    pos_label = "⬆️ أعلى" if tail_pos == "top" else "⬇️ أسفل"
    text = (
        f"🔖 **إعدادات التوقيع**\n{entity_name(ch)}\n\n🔖 التوقيع نص يُضاف لنهاية (أو بداية) المنشورات في هذه القناة.\n"
        f"{'✅' if tail_enabled else '❌'} التوقيع"
        + (f":\n`{current_tail}`" if current_tail and tail_enabled else "")
        + ("\n\n📊 شرط {0} كلمة: {1}".format(tail_min, "✅ مفعل" if min_active else "❌ متوقف"))
        + f"\n📍 المكان: {pos_label}"
    )
    buttons = [
        InlineKeyboardButton(f"{'✅' if tail_enabled else '❌'} تشغيل التوقيع", callback_data=f"tailtoggle_{ch_id}"),
        InlineKeyboardButton(f"✏️ تعديل النص", callback_data=f"edittail_{ch_id}"),
        InlineKeyboardButton(f"{'✅' if min_active else '❌'} شرط {tail_min} كلمة", callback_data=f"tailmintoggle_{ch_id}"),
        InlineKeyboardButton(f"{'⬆️' if tail_pos=='top' else '⬇️'} المكان: {pos_label}", callback_data=f"tailpos_{ch_id}"),
        InlineKeyboardButton("🗑 حذف التوقيع", callback_data=f"deltail_{ch_id}"),
    ]
    rows = grid_buttons(buttons, 2)
    rows.append(nav_row(f"postset_{ch_id}"))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def tail_toggle_handler(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    cur = db.get_channel_tail_enabled(ch_id) if hasattr(db, "get_channel_tail_enabled") else True
    if hasattr(db, "set_channel_tail_enabled"):
        db.set_channel_tail_enabled(ch_id, not cur)
    await callback.answer("تم التحديث.")
    callback.data = f"tails_{ch_id}"
    await tail_settings_menu(client, callback)


async def tail_min_toggle_handler(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    cur = db.get_channel_tail_min_words(ch_id) if hasattr(db, "get_channel_tail_min_words") else 20
    new_val = 0 if cur >= 20 else 20
    if hasattr(db, "set_channel_tail_min_words"):
        db.set_channel_tail_min_words(ch_id, new_val)
    await callback.answer(f"تم التحديث إلى {'20' if new_val else 'بدون'} كلمة.")
    callback.data = f"tails_{ch_id}"
    await tail_settings_menu(client, callback)


async def tail_position_toggle_handler(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    cur = db.get_channel_tail_position(ch_id) if hasattr(db, "get_channel_tail_position") else "bottom"
    new_pos = "top" if cur == "bottom" else "bottom"
    if hasattr(db, "set_channel_tail_position"):
        db.set_channel_tail_position(ch_id, new_pos)
    await callback.answer(f"تم تغيير المكان إلى {'أعلى' if new_pos == 'top' else 'أسفل'}.")
    callback.data = f"tails_{ch_id}"
    await tail_settings_menu(client, callback)


# ============================================================
# 🧪 إعدادات الاختبار
# ============================================================

async def test_settings_menu(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("غير موجودة.")
        return
    buttons = [
        InlineKeyboardButton("🧪 اختبار نشر", callback_data=f"testpub_{ch_id}"),
        InlineKeyboardButton("👁 معاينة المنشور", callback_data=f"preview_{ch_id}"),
    ]
    rows = grid_buttons(buttons, 2)
    rows.append(nav_row(f"postset_{ch_id}"))
    text = f"🧪 **إعدادات الاختبار**\n{entity_name(ch)}\n\n🧪 اختبار نشر: يرسل رسالة اختبار حقيقية للقناة.\n👁 معاينة المنشور: يعرض كيف سيبدو المنشور مع الإعدادات الحالية."
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def preview_post(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("غير موجودة.")
        return
    await callback.answer("جاري تحضير المعاينة...")
    try:
        sources = ch.get("special_sources", [])
        if not sources:
            srcs = db.get_public_sources()
            if srcs:
                sources = [srcs[0].get("id") if isinstance(srcs[0], dict) else srcs[0]]
        if not sources:
            await safe_edit(callback, "❌ لا توجد مصادر لهذه القناة.\nأضف مصدراً أولاً.", InlineKeyboardMarkup([nav_row(f"testset_{ch_id}")]))
            return
        preview_text = f"""📄 معاينة المنشور لقناة {entity_name(ch)}

━━━━━━━━━━━━━━━━
نص تجريبي لتطبيق الإعدادات على المنشور قبل النشر.

يتم تطبيق جميع إعدادات القناة الحالية على هذا النص.
━━━━━━━━━━━━━━━━"""

        bold = ch.get("bold_publish", True)
        tail = ch.get("tail", "")
        tail_enabled = db.get_channel_tail_enabled(ch_id) if hasattr(db, "get_channel_tail_enabled") else True
        tail_min = db.get_channel_tail_min_words(ch_id) if hasattr(db, "get_channel_tail_min_words") else 20
        tail_pos = db.get_channel_tail_position(ch_id) if hasattr(db, "get_channel_tail_position") else "bottom"
        tags = db.get_channel_hashtags(ch_id) if hasattr(db, "get_channel_hashtags") else []
        delay = ch.get("publish_delay")

        word_count = len(preview_text.split())
        tail_applied = tail_enabled and bool(tail) and (tail_min == 0 or word_count >= tail_min)

        report_lines = ["📄 **تقرير المعالجة**\n"]
        report_lines.append(f"{'✅' if bold else '❌'} تم {'تطبيق' if bold else 'إلغاء'} الخط السميك")
        if tail_applied:
            report_lines.append(f"✅ تم إضافة التوقيع")
            report_lines.append(f"📍 مكان التوقيع:\n{'⬆️ أعلى' if tail_pos == 'top' else '⬇️ أسفل'} المنشور")
        else:
            if not tail_enabled:
                report_lines.append(f"❌ التوقيع متوقف")
            elif not tail:
                report_lines.append(f"❌ لا يوجد نص توقيع")
            else:
                report_lines.append(f"❌ تم تجاهل التوقيع (أقل من {tail_min} كلمة)")
        report_lines.append(f"📊 عدد الكلمات: {word_count}")
        report_lines.append(f"🏷 عدد الهاشتاكات: {len(tags)}")
        if delay:
            report_lines.append(f"⏱ تأخير النشر: {delay} ثانية")
        else:
            report_lines.append(f"⏱ سرعة النشر: افتراضي")

        text = "\n".join(report_lines)
        buttons = [
            nav_row(f"testset_{ch_id}"),
        ]
        await safe_edit(callback, text, InlineKeyboardMarkup(buttons))
    except Exception as e:
        logger.error(f"خطأ في المعاينة: {e}")
        await safe_edit(callback, f"❌ فشلت المعاينة:\n{e}", InlineKeyboardMarkup([nav_row(f"testset_{ch_id}")]))


async def toggle_channel_bold(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("القناة غير موجودة.")
        return
    current = bool(ch.get("bold_publish", True))
    if hasattr(db, "set_channel_bold_publish"):
        db.set_channel_bold_publish(ch_id, not current)
    else:
        db.update_channel(ch_id, "bold_publish", not current)
    await callback.answer("تم تحديث خيار الخط السميك.")
    callback.data = f"postset_{ch_id}"
    await post_settings_menu(client, callback)

async def menu_channels(client, callback):
    channels = db.get_all_channels()

    if not channels:
        text = "لا توجد قنوات منشورة بعد. اضغط ➕ لإضافتها."
        rows = [
            [InlineKeyboardButton("➕ إضافة قناة/قنوات", callback_data="add_channel")],
            nav_row("main_menu")
        ]
    else:
        text = f"**قنوات النشر ({len(channels)}):**\n⚙️ اسم القناة: يفتح إعدادات القناة.\n➕ إضافة قناة/قنوات: يسجل قنوات نشر جديدة (رابط/يوزر/ID)."
        btns = []
        for ch in channels:
            paused = " ⏸️" if ch.get('paused') else ""
            name = entity_name(ch)
            username = ch.get("username") or ""
            username_txt = f"@{username}" if username else "لا يوجد يوزر"
            text += f"\n✅ {name}{paused}\n   {username_txt}\n   ID: `{ch['id']}`\n"
            btns.append(InlineKeyboardButton(f"⚙️ {name}", callback_data=f"ch_{ch['id']}"))
        rows = grid_buttons(btns, 2 if len(btns) <= 8 else 3)
        rows.append([InlineKeyboardButton("➕ إضافة قناة/قنوات", callback_data="add_channel")])
        rows.append(nav_row("main_menu"))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))

async def show_channels_menu_from_message(message):
    channels = db.get_all_channels()
    if not channels:
        text = "لا توجد قنوات منشورة بعد. اضغط ➕ لإضافتها."
        rows = [
            [InlineKeyboardButton("➕ إضافة قناة/قنوات", callback_data="add_channel")],
            nav_row("main_menu")
        ]
    else:
        text = f"**قنوات النشر ({len(channels)}):**\n⚙️ اسم القناة: يفتح إعدادات القناة.\n➕ إضافة قناة/قنوات: يسجل قنوات نشر جديدة (رابط/يوزر/ID)."
        btns = []
        for ch in channels:
            paused = " ⏸️" if ch.get('paused') else ""
            name = entity_name(ch)
            username = ch.get("username") or ""
            username_txt = f"@{username}" if username else "لا يوجد يوزر"
            text += f"\n✅ {name}{paused}\n   {username_txt}\n   ID: `{ch['id']}`\n"
            btns.append(InlineKeyboardButton(f"⚙️ {name}", callback_data=f"ch_{ch['id']}"))
        rows = grid_buttons(btns, 2 if len(btns) <= 8 else 3)
        rows.append([InlineKeyboardButton("➕ إضافة قناة/قنوات", callback_data="add_channel")])
        rows.append(nav_row("main_menu"))
    await message.reply(text, reply_markup=InlineKeyboardMarkup(rows))

async def channel_settings(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("غير موجودة.")
        return
    name = entity_name(ch)
    username = ch.get("username") or ""
    username_txt = f"@{username}" if username else "لا يوجد يوزر"
    if hasattr(db, "mapper"):
        assigned_bots = db.mapper.get_bots_for_channel(ch_id)
    else:
        cfg = db.get_channel_config(ch_id) if hasattr(db, "get_channel_config") else {}
        assigned_bots = cfg.get("assigned_bots", [])
    bot_count = len(assigned_bots)
    verifications = verifier.get_cached_verifications_for_channel(ch_id)
    ok_count = sum(1 for v in verifications.values() if v.get("verified") and v.get("can_post"))
    ch_sources = ch.get("special_sources", [])
    src_count = len(ch_sources)
    if ch.get("bot_admin") is None:
        bot_line = "🤖 ❓ لم يُفحص بعد"
    else:
        bot_line = "🤖 ✅ البوت مشرف" if ch.get("bot_admin") else "🤖 ❌ البوت ليس مشرفاً"
    text = (
        f"📢 **{name}**\n\n"
        f"👤 {username_txt}\n"
        f"🆔 `{ch_id}`\n"
        f"{'⏸️ موقوفة' if ch.get('paused') else '✅ شغالة'}"
        f" | 📄 {ch.get('posts_count', 0)}"
        f" | ⚠️ {ch.get('fail_count', 0)}\n"
        f"{bot_line}\n"
        f"🤖 {bot_count} بوت ({ok_count} جاهز)"
        f" | 📚 {src_count} مصدر"
    )
    await safe_edit(callback, text, channel_buttons(ch_id))

async def add_channel_prompt(client, callback):
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {"state": "waiting_channel_id"}
    await safe_edit(callback, "أرسل قناة واحدة أو عدة قنوات نشر.\nكل رابط/يوزر/ID بسطر مستقل:")

async def toggle_pause(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)

    if not ch:
        await callback.answer("غير موجودة.")
        return

    db.update_channel(ch_id, "paused", not ch.get("paused"))
    await callback.answer("تم التحديث.")
    await channel_settings(client, callback)

async def delete_channel_prompt(client, callback):
    channels = db.get_all_channels()
    if not channels:
        await callback.answer("لا توجد قنوات.")
        return
    ch_id = callback.data.split("_", 1)[1]
    buttons = []
    for ch in channels:
        name = entity_name(ch)
        buttons.append([InlineKeyboardButton(f"🗑 حذف {name}", callback_data=f"confirm_del_{ch['id']}")])
    buttons.append(nav_row(f"genset_{ch_id}"))
    await safe_edit(callback, "اختر القناة التي تريد حذفها:", InlineKeyboardMarkup(buttons))

async def confirm_delete_channel(client, callback):
    ch_id = callback.data.split("_", 2)[2]
    db.delete_channel(ch_id)
    await callback.answer("تم الحذف.")
    await menu_channels(client, callback)

async def tail_menu(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)

    if not ch:
        await callback.answer("غير موجودة.")
        return

    current = ch.get("tail", "")
    text = (f"التوقيع الحالي:\n`{current}`" if current else "لا يوجد توقيع.") + "\n\n✏️ تعديل/إضافة: يحدّث نص التوقيع.\n🗑 حذف التوقيع: يمسح التوقيع الحالي."

    buttons = [
        [InlineKeyboardButton("✏️ تعديل/إضافة", callback_data=f"edittail_{ch_id}")],
        [InlineKeyboardButton("🗑 حذف التوقيع", callback_data=f"deltail_{ch_id}")],
        nav_row(f"tails_{ch_id}")
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))

async def edit_tail_prompt(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {"state": "waiting_tail", "ch_id": ch_id}
    await safe_edit(callback, "أرسل نص التوقيع الجديد:", InlineKeyboardMarkup([nav_row(f"tails_{ch_id}")]))

async def delete_tail(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    db.update_channel(ch_id, "tail", "")
    await callback.answer("تم حذف التوقيع.")
    await tail_menu(client, callback)

async def menu_public_sources(client, callback):
    srcs = db.get_public_sources()
    meta_list = db.get_all_public_sources_with_meta() if hasattr(db, "get_all_public_sources_with_meta") else [{"id": s, "name": str(s)} for s in srcs]
    text = f"**المصادر العامة ({len(srcs)}):**\n➕ إضافة مصدر/مصادر: يضيف قنوات عامة جديدة يراقبها البوت (رابط/يوزر/ID).\n🗑 حذف مصدر عام: يحذف مصدراً عاماً من المراقبة."
    text += "\n\n".join(entity_details_line(m, is_source=True) for m in meta_list) if srcs else "لا توجد."
    btns = []
    for meta in meta_list:
        sid = meta.get("id")
        paused = " ⏸️" if is_source_paused(sid) else ""
        btns.append(InlineKeyboardButton(f"⚙️ {entity_name(meta)}{paused}", callback_data=f"srcset|{sid}|menu_public_src"))
    rows = grid_buttons(btns, 2 if len(btns) <= 8 else 3)
    rows.append([InlineKeyboardButton("➕ إضافة مصدر/مصادر", callback_data="add_public_src"), InlineKeyboardButton("🗑 حذف مصدر عام", callback_data="del_public_src")])
    rows.append(nav_row("main_menu"))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))

async def add_public_src_prompt(client, callback):
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {"state": "waiting_public_source"}
    await safe_edit(callback, "أرسل مصدر واحد أو عدة مصادر عامة.\nكل رابط/يوزر/ID بسطر مستقل:", InlineKeyboardMarkup([nav_row("menu_public_src")]))

async def del_public_src_prompt(client, callback):
    srcs = db.get_public_sources()
    if not srcs:
        await callback.answer("لا توجد مصادر.")
        return
    buttons = []
    for idx, src in enumerate(srcs):
        name = entity_name(src, is_source=True)
        buttons.append([InlineKeyboardButton(f"🗑 حذف {name}", callback_data=f"del_pub_idx_{idx}")])
    buttons.append(nav_row("menu_public_src"))
    await safe_edit(callback, "اختر المصدر للحذف:", InlineKeyboardMarkup(buttons))

async def confirm_del_public_src(client, callback):
    idx = int(callback.data.split("_")[-1])
    srcs = db.get_public_sources()

    if idx < 0 or idx >= len(srcs):
        await callback.answer("المصدر غير موجود.")
        return

    db.remove_public_source(srcs[idx])
    await callback.answer("تم الحذف.")
    await menu_public_sources(client, callback)

async def menu_blocked_words(client, callback):
    words = db.get_blocked_words()

    text = "**الكلمات المحظورة:**\n"
    text += (", ".join(words) if words else "لا توجد.") + "\n➕ إضافة كلمة: يمنع نشر أي منشور يحتويها.\n🗑 حذف كلمة: يزيل كلمة من القائمة."

    buttons = [
        [InlineKeyboardButton("➕ إضافة كلمة", callback_data="add_blocked_word")],
        [InlineKeyboardButton("🗑 حذف كلمة", callback_data="del_blocked_word")],
        nav_row("main_menu")
    ]

    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))

async def add_blocked_word_prompt(client, callback):
    await callback.answer()
    logger.info(f"add_blocked_word_prompt: user {callback.from_user.id}")
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {"state": "waiting_blocked_word"}
    await safe_edit(callback, "أرسل كلمة أو عدة كلمات محظورة.\nكل كلمة/عبارة بسطر مستقل:", InlineKeyboardMarkup([nav_row("menu_blocked")]))

async def del_blocked_word_prompt(client, callback):
    await callback.answer()
    logger.info(f"del_blocked_word_prompt: user {callback.from_user.id}")
    words = db.get_blocked_words()

    if not words:
        await callback.answer("لا توجد كلمات محظورة.")
        return

    buttons = []

    for idx, word in enumerate(words):
        buttons.append([InlineKeyboardButton(f"حذف {word}", callback_data=f"delword_idx_{idx}")])

    buttons.append(nav_row("menu_blocked"))
    await safe_edit(callback, "اختر الكلمة:", InlineKeyboardMarkup(buttons))

async def confirm_del_blocked_word(client, callback):
    idx = int(callback.data.split("_")[-1])
    words = db.get_blocked_words()

    if idx < 0 or idx >= len(words):
        await callback.answer("الكلمة غير موجودة.")
        return

    db.remove_blocked_word(words[idx])
    await callback.answer("تم الحذف.")
    await menu_blocked_words(client, callback)


# ============================================================
# 🚫 الكلمات المحظورة — خاصة بكل قناة على حدة
# ============================================================

async def channel_blocked_words_menu(client, callback):
    ch_id = callback.data.split("|", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("القناة غير موجودة.")
        return
    words = db.get_channel_blocked_words(ch_id)
    text = f"🚫 **الكلمات المحظورة — {entity_name(ch)}**\n\n"
    text += "أي منشور يحتوي إحدى هذي الكلمات لن يُنشر بهذه القناة فقط (باقي القنوات غير متأثرة).\n\n"
    text += (", ".join(words) if words else "لا توجد كلمات محظورة لهذه القناة.") + "\n\n➕ إضافة كلمة / 🗑 حذف كلمة: إدارة الكلمات المحظورة لهذه القناة فقط."
    buttons = [
        [InlineKeyboardButton("➕ إضافة كلمة", callback_data=f"chwordadd|{ch_id}")],
        [InlineKeyboardButton("🗑 حذف كلمة", callback_data=f"chworddel|{ch_id}")],
        nav_row(f"postset_{ch_id}"),
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def channel_add_blocked_word_prompt(client, callback):
    await callback.answer()
    logger.info(f"channel_add_blocked_word_prompt: user {callback.from_user.id}")
    ch_id = callback.data.split("|", 1)[1]
    if not db.get_channel(ch_id):
        await callback.answer("القناة غير موجودة.")
        return
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {"state": "waiting_channel_blocked_word", "ch_id": ch_id}
    await safe_edit(callback, "أرسل كلمة أو عدة كلمات محظورة لهذه القناة فقط.\nكل كلمة/عبارة بسطر مستقل:", InlineKeyboardMarkup([nav_row(f"chwords|{ch_id}")]))


async def channel_del_blocked_word_prompt(client, callback):
    ch_id = callback.data.split("|", 1)[1]
    words = db.get_channel_blocked_words(ch_id)
    if not words:
        await callback.answer("لا توجد كلمات محظورة لهذه القناة.")
        return
    buttons = []
    for idx, word in enumerate(words):
        buttons.append([InlineKeyboardButton(f"حذف {word}", callback_data=f"chworddelidx|{ch_id}|{idx}")])
    buttons.append(nav_row(f"chwords|{ch_id}"))
    await safe_edit(callback, "اختر الكلمة:", InlineKeyboardMarkup(buttons))


async def confirm_channel_del_blocked_word(client, callback):
    try:
        _, ch_id, idx_str = callback.data.split("|", 2)
    except ValueError:
        await callback.answer("طلب غير صالح.")
        return
    words = db.get_channel_blocked_words(ch_id)
    try:
        idx = int(idx_str)
    except ValueError:
        await callback.answer("خطأ في البيانات.")
        return
    if idx < 0 or idx >= len(words):
        await callback.answer("الكلمة غير موجودة.")
        return
    db.remove_channel_blocked_word(ch_id, words[idx])
    await callback.answer("تم الحذف.")
    callback.data = f"chwords|{ch_id}"
    await channel_blocked_words_menu(client, callback)


# ============================================================
# 🔗 إدارة الروابط — خاصة بكل قناة على حدة
# ============================================================

CHANNEL_LINK_FILTER_KEYS = {
    "chlinktg|": "link_remove_tg",
    "chlinktguser|": "link_remove_tg_user",
    "chlinkweb|": "link_remove_web",
}


async def channel_links_menu(client, callback):
    ch_id = callback.data.split("|", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("القناة غير موجودة.")
        return
    link_tg = bool(ch.get("link_remove_tg"))
    link_tg_user = bool(ch.get("link_remove_tg_user"))
    link_web = bool(ch.get("link_remove_web"))
    text = (
        f"🔗 **إدارة الروابط — {entity_name(ch)}**\n\n"
        "التحكم بروابط المنشورات المُرسلة لهذه القناة فقط (باقي القنوات غير متأثرة).\n\n"
        f"{'✅' if link_tg else '❌'} حذف روابط تيليجرام (t.me)\n"
        f"{'✅' if link_tg_user else '❌'} حذف يوزرات تيليجرام (@username)\n"
        f"{'✅' if link_web else '❌'} حذف روابط المواقع (ما عدا تيليجرام)\n\nاضغط على الزر لتفعيل/إيقاف حذف نوع الروابط في منشورات هذه القناة فقط."
    )
    buttons = [
        [InlineKeyboardButton(f"{'✅' if link_tg else '❌'} حذف روابط تيليجرام", callback_data=f"chlinktg|{ch_id}")],
        [InlineKeyboardButton(f"{'✅' if link_tg_user else '❌'} حذف يوزرات @", callback_data=f"chlinktguser|{ch_id}")],
        [InlineKeyboardButton(f"{'✅' if link_web else '❌'} حذف روابط المواقع", callback_data=f"chlinkweb|{ch_id}")],
        nav_row(f"postset_{ch_id}"),
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def toggle_channel_link_filter(client, callback):
    prefix, ch_id = callback.data.split("|", 1)
    key = CHANNEL_LINK_FILTER_KEYS.get(prefix + "|")
    if not key:
        await callback.answer("أمر غير معروف.")
        return
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("القناة غير موجودة.")
        return
    db.update_channel(ch_id, key, not bool(ch.get(key)))
    await callback.answer("تم التحديث.")
    callback.data = f"chlinks|{ch_id}"
    await channel_links_menu(client, callback)


# ============================================================
# 🤖 التحقق من البوت — فحص حقيقي لحالة البوت داخل القناة
# ============================================================

def format_bot_check_result(status_value, privileges=None, error=""):
    """يبني نص نتيجة الفحص الحقيقي لحالة البوت داخل القناة."""
    if error:
        return f"❌ تعذر الوصول إلى القناة.\nالسبب الحقيقي: {error}"
    status_value = status_value or ""
    if is_bot_admin_status(status_value):
        perm_lines = ""
        if privileges:
            perm_lines = "\n".join(
                f"• {label}: {'✅' if bool(getattr(privileges, key, True)) else '❌'}"
                for label, key in (
                    ("نشر الرسائل", "can_post_messages"),
                    ("تعديل الرسائل", "can_edit_messages"),
                    ("حذف الرسائل", "can_delete_messages"),
                )
            )
        text = f"✅ البوت مشرف في القناة\nالحالة: `{status_value}`"
        if perm_lines:
            text += f"\nالصلاحيات:\n{perm_lines}"
        return text
    if status_value in ("member", "restricted"):
        return f"❌ البوت ليس مشرفاً في القناة\nالحالة الفعلية: `{status_value}`"
    if status_value in ("left",):
        return f"❌ البوت غير موجود داخل القناة.\nالحالة الفعلية: `{status_value}`"
    if status_value in ("banned", "kicked"):
        return f"❌ البوت محظور داخل القناة.\nالحالة الفعلية: `{status_value}`"
    return f"❌ البوت ليس مشرفاً في القناة\nالحالة الفعلية: `{status_value}`"


async def channel_bot_check(client, callback):
    """فحص حقيقي (Real Check) عبر Telegram API بحالة البوت داخل القناة — بدون أي نتيجة محفوظة."""
    ch_id = callback.data.split("|", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("القناة غير موجودة.")
        return
    await callback.answer("جاري الفحص الحقيقي...")
    bot_status = "unknown"
    bot_admin = False
    result_text = ""
    try:
        bot_member = await bot_client.get_chat_member(int(ch_id), (await bot_client.get_me()).id)
        bot_status = member_status_value(getattr(bot_member, "status", None))
        bot_admin = is_bot_admin_status(bot_status)
        result_text = format_bot_check_result(bot_status, getattr(bot_member, "privileges", None))
    except Exception as e:
        result_text = format_bot_check_result("", error=str(e)[:200])
    db.update_channel(ch_id, "bot_admin", bot_admin)
    db.update_channel(ch_id, "bot_status", bot_status)
    text = (
        f"🤖 **التحقق من البوت — {entity_name(ch)}**\n"
        f"🆔 `{ch_id}`\n\n"
        f"{result_text}"
    )
    buttons = [[InlineKeyboardButton("🔙 رجوع لإعدادات القناة", callback_data=f"ch_{ch_id}")]]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))

async def manage_special_sources(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("غير موجودة.")
        return
    sources = ch.get("special_sources", [])
    text = "**المصادر المخصصة:**\n➕ إضافة: يضيف مصدراً خاصاً لهذه القناة فقط.\n🗑 حذف: يزيل مصدراً خاصاً."
    text += "\n".join(f"• {entity_name(s, is_source=True)}\n  ID: `{s}`" for s in sources) if sources else "لا توجد."
    btns = []
    for s in sources:
        paused = " ⏸️" if is_source_paused(s) else ""
        btns.append(InlineKeyboardButton(f"⚙️ {entity_name(s, is_source=True)}{paused}", callback_data=f"srcset|{s}|specsrc_{ch_id}"))
    rows = grid_buttons(btns, 2 if len(btns) <= 8 else 3)
    rows.append([InlineKeyboardButton("➕ إضافة", callback_data=f"addspecsrc_{ch_id}"), InlineKeyboardButton("🗑 حذف", callback_data=f"delspecsrc_{ch_id}")])
    rows.append(nav_row(f"srcset_{ch_id}"))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))

async def source_cleanup_menu(client, callback):
    parts = callback.data.split("|", 2)
    source_id = parts[1]
    back = parts[2] if len(parts) > 2 else "menu_public_src"
    terms = db.get_source_remove_terms(source_id) if hasattr(db, "get_source_remove_terms") else []
    meta = db.get_source_meta(source_id) if hasattr(db, "get_source_meta") else {"name": str(source_id)}
    name = entity_name(meta)
    text = f"🧹 **التنظيف الذكي للمصدر:**\n{name}\nID: `{source_id}`\n\n➕ إضافة عناصر جماعياً: تُحذف منشورات المصدر التي تحتوي هذه العناصر.\n🗑 حذف عناصر جماعياً: يزيل عناصر من قائمة التنظيف.\n\n"
    text += "العناصر الحالية:\n" + ("\n".join(f"• `{t}`" for t in terms) if terms else "لا توجد عناصر.")
    buttons = [
        [InlineKeyboardButton("➕ إضافة عناصر جماعياً", callback_data=f"addclean|{source_id}|{back}")],
        [InlineKeyboardButton("🗑 حذف عناصر جماعياً", callback_data=f"delclean|{source_id}|{back}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"srcset|{source_id}|{back}")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def add_source_cleanup_prompt(client, callback):
    _, source_id, back = callback.data.split("|", 2)
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {"state": "waiting_source_cleanup_add", "source_id": source_id, "back": back}
    await safe_edit(callback, "أرسل عناصر التنظيف الذكي لهذا المصدر.\nكل كلمة/هاشتاك/يوزر بسطر مستقل:", InlineKeyboardMarkup([nav_row(f"srcset|{source_id}|{back}")]))


async def del_source_cleanup_prompt(client, callback):
    _, source_id, back = callback.data.split("|", 2)
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {"state": "waiting_source_cleanup_del", "source_id": source_id, "back": back}
    terms = db.get_source_remove_terms(source_id) if hasattr(db, "get_source_remove_terms") else []
    current = "\n".join(f"• {t}" for t in terms) if terms else "لا توجد عناصر حالياً."
    await safe_edit(callback, "أرسل العناصر التي تريد حذفها من التنظيف الذكي.\nكل عنصر بسطر مستقل.\n\nالحالي:\n" + current, InlineKeyboardMarkup([nav_row(f"srcset|{source_id}|{back}")]))


async def source_settings_menu(client, callback):
    _, source_id, back = callback.data.split("|", 2)
    meta = db.get_source_meta(source_id) if hasattr(db, "get_source_meta") else {"name": str(source_id)}
    name = entity_name(meta)
    paused = is_source_paused(source_id)
    remove_emoji = db.get_source_remove_emoji(source_id) if hasattr(db, "get_source_remove_emoji") else False
    terms = db.get_source_remove_terms(source_id) if hasattr(db, "get_source_remove_terms") else []
    text = (
        f"⚙️ **إعدادات المصدر:**\n{name}\n\n"
        f"🆔 ID: `{source_id}`\n"
        f"📊 الحالة: {'⏸️ موقوف' if paused else '✅ شغال'}\n"
        f"😀 حذف الإيموجي: {'✅ مفعل' if remove_emoji else '❌ متوقف'}\n"
        f"📦 أنواع المحتوى:\n{content_types_status_line(source_id)}\n"
        f"🧹 عناصر التنظيف الذكي: {len(terms)}\n\n⏯️ تشغيل/إيقاف: يوقف فحص هذا المصدر دون حذفه.\n😀 الإيموجي: حذف الإيموجي من المنشورات.\n📦 المحتوى: اختيار أنواع المحتوى المسموحة.\n🧹 التنظيف: عناصر تحذف المنشورات المحتوية لها.\n📊 الإحصائيات / 📋 السجل / 🧪 اختبار: فحص حالة المصدر.\n📑 نسخ / 📋 لصق الإعدادات: نقل إعدادات مصدر لمصادر أخرى."
    )
    btns = [
        InlineKeyboardButton("⏯️ تشغيل/إيقاف", callback_data=f"togglesource|{source_id}|{back}"),
        InlineKeyboardButton("😀 الإيموجي", callback_data=f"toggleemoji|{source_id}|{back}"),
        InlineKeyboardButton("📦 المحتوى", callback_data=f"contentmenu|{source_id}|{back}"),
        InlineKeyboardButton("🧹 التنظيف", callback_data=f"clean_src|{source_id}|{back}"),
        InlineKeyboardButton("📊 الإحصائيات", callback_data=f"srcstats|{source_id}|{back}"),
        InlineKeyboardButton("📋 السجل", callback_data=f"srclog|{source_id}|{back}"),
        InlineKeyboardButton("🧪 اختبار", callback_data=f"testsrc|{source_id}|{back}"),
        InlineKeyboardButton("📑 نسخ الإعدادات", callback_data=f"copysrc|{source_id}|{back}"),
        InlineKeyboardButton("📋 لصق الإعدادات", callback_data=f"pastesrc|{source_id}|{back}"),
    ]
    rows = grid_buttons(btns, 2)
    rows.append(nav_row(back))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))

async def toggle_source_enabled(client, callback):
    _, source_id, back = callback.data.split("|", 2)
    new_state = not is_source_paused(source_id)
    if hasattr(db, "set_source_paused"):
        db.set_source_paused(source_id, new_state)
    await callback.answer("تم إيقاف المصدر." if new_state else "تم تشغيل المصدر.")
    callback.data = f"srcset|{source_id}|{back}"
    await source_settings_menu(client, callback)


async def toggle_source_emoji(client, callback):
    _, source_id, back = callback.data.split("|", 2)
    current = db.get_source_remove_emoji(source_id) if hasattr(db, "get_source_remove_emoji") else False
    if hasattr(db, "set_source_remove_emoji"):
        db.set_source_remove_emoji(source_id, not current)
    await callback.answer("تم التحديث.")
    callback.data = f"srcset|{source_id}|{back}"
    await source_settings_menu(client, callback)


async def source_content_menu(client, callback):
    _, source_id, back = callback.data.split("|", 2)
    types = db.get_source_content_types(source_id) if hasattr(db, "get_source_content_types") else {"text": True, "photo": True, "video": True, "album": True, "voice": False, "audio": False, "document": False}
    labels = {"text": "نصوص", "photo": "صور", "video": "فيديو", "album": "ألبومات", "voice": "بصمات", "audio": "صوتيات", "document": "ملفات"}
    meta = db.get_source_meta(source_id) if hasattr(db, "get_source_meta") else {"name": str(source_id)}
    text = f"📦 **فلتر أنواع المحتوى:**\n{entity_name(meta)}\n\nاختر نوع أو أكثر. الافتراضي هو الكل.\n\nيحدد أنواع المنشورات التي يستقبلها هذا المصدر (نصوص، صور، فيديو...)."
    btns = []
    for key, label in labels.items():
        mark = "✅" if types.get(key, True) else "❌"
        btns.append(InlineKeyboardButton(f"{mark} {label}", callback_data=f"togglectype|{source_id}|{key}|{back}"))
    rows = grid_buttons(btns, 2)
    rows.append(nav_row(f"srcset|{source_id}|{back}"))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))

async def toggle_content_type(client, callback):
    _, source_id, ctype, back = callback.data.split("|", 3)
    types = db.get_source_content_types(source_id) if hasattr(db, "get_source_content_types") else {"text": True, "photo": True, "video": True, "album": True, "voice": False, "audio": False, "document": False}
    new_value = not bool(types.get(ctype, True))
    ok = True
    if hasattr(db, "set_source_content_type"):
        ok = db.set_source_content_type(source_id, ctype, new_value)
    if not ok:
        await callback.answer("لا يمكن إيقاف كل الأنواع. لازم يبقى نوع واحد على الأقل.", show_alert=True)
    else:
        await callback.answer("تم التحديث.")
    callback.data = f"contentmenu|{source_id}|{back}"
    await source_content_menu(client, callback)


async def global_cleanup_menu(client, callback):
    terms = db.get_global_remove_terms() if hasattr(db, "get_global_remove_terms") else []
    text = "🧹 **قائمة الحذف العامة:**\n\n"
    text += "تنطبق على كل المصادر قبل النشر.\n\n➕ إضافة جماعية / 🗑 حذف جماعي: إدارة العناصر المحذوفة من جميع المصادر.\n\n"
    text += "العناصر الحالية:\n" + ("\n".join(f"• `{t}`" for t in terms) if terms else "لا توجد عناصر.")
    rows = [
        [InlineKeyboardButton("➕ إضافة جماعية", callback_data="addglobalclean"), InlineKeyboardButton("🗑 حذف جماعي", callback_data="delglobalclean")],
        nav_row("main_menu")
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))

async def add_global_cleanup_prompt(client, callback):
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {"state": "waiting_global_cleanup_add"}
    await safe_edit(callback, "أرسل كلمات/هاشتاكات/أسماء للحذف العام.\nكل عنصر بسطر مستقل:", InlineKeyboardMarkup([nav_row("global_clean")]))


async def del_global_cleanup_prompt(client, callback):
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {"state": "waiting_global_cleanup_del"}
    terms = db.get_global_remove_terms() if hasattr(db, "get_global_remove_terms") else []
    current = "\n".join(f"• {t}" for t in terms) if terms else "لا توجد عناصر حالياً."
    await safe_edit(callback, "أرسل العناصر التي تريد حذفها من قائمة الحذف العامة.\nكل عنصر بسطر مستقل.\n\nالحالي:\n" + current, InlineKeyboardMarkup([nav_row("global_clean")]))


# ============================================================
# 🧹 قائمة الكلمات المحذوفة — خاصة بكل قناة على حدة
# ============================================================

async def channel_delete_terms_menu(client, callback):
    ch_id = callback.data.split("|", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("القناة غير موجودة.")
        return
    terms = db.get_channel_delete_terms(ch_id)
    text = f"🧹 **قائمة الكلمات المحذوفة — {entity_name(ch)}**\n\n"
    text += "تُحذف هذي العناصر من النص قبل نشره بهذه القناة فقط (باقي القنوات غير متأثرة).\n\n"
    text += "العناصر الحالية:\n" + ("\n".join(f"• {t}" for t in terms) if terms else "لا توجد عناصر.") + "\n\n➕ إضافة جماعية / 🗑 حذف جماعي: إدارة الكلمات المحذوفة من منشورات هذه القناة فقط."
    rows = [
        [InlineKeyboardButton("➕ إضافة جماعية", callback_data=f"chdeltermadd|{ch_id}"), InlineKeyboardButton("🗑 حذف جماعي", callback_data=f"chdeltermdel|{ch_id}")],
        nav_row(f"postset_{ch_id}"),
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def channel_add_delete_term_prompt(client, callback):
    await callback.answer()
    logger.info(f"channel_add_delete_term_prompt: user {callback.from_user.id}")
    ch_id = callback.data.split("|", 1)[1]
    if not db.get_channel(ch_id):
        await callback.answer("القناة غير موجودة.")
        return
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {"state": "waiting_channel_delete_term_add", "ch_id": ch_id}
    await safe_edit(callback, "أرسل كلمات/هاشتاكات/أسماء لحذفها من منشورات هذه القناة فقط.\nكل عنصر بسطر مستقل:", InlineKeyboardMarkup([nav_row(f"chdelterms|{ch_id}")]))


async def channel_del_delete_term_prompt(client, callback):
    await callback.answer()
    logger.info(f"channel_del_delete_term_prompt: user {callback.from_user.id}")
    ch_id = callback.data.split("|", 1)[1]
    if not db.get_channel(ch_id):
        await callback.answer("القناة غير موجودة.")
        return
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {"state": "waiting_channel_delete_term_del", "ch_id": ch_id}
    terms = db.get_channel_delete_terms(ch_id)
    current = "\n".join(f"• {t}" for t in terms) if terms else "لا توجد عناصر حالياً."
    await safe_edit(callback, "أرسل العناصر التي تريد حذفها.\nكل عنصر بسطر مستقل.\n\nالحالي:\n" + current, InlineKeyboardMarkup([nav_row(f"chdelterms|{ch_id}")]))



async def channel_speed_menu(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("القناة غير موجودة.")
        return
    current = ch.get("publish_delay", None)
    text = (
        f"⏱ **سرعة النشر للقناة:**\n{entity_name(ch)}\n\n⏱ الفترة بالثانية بين المنشورات في هذه القناة.\n"
        f"الحالية: {'افتراضي' if current in (None, '') else str(current) + ' ثانية'}\n\n"
        "اختر قيمة سريعة أو اضغط تخصيص. 0 يعني رجوع للوضع الافتراضي."
    )
    buttons = [
        [InlineKeyboardButton("افتراضي", callback_data=f"setspeed|{ch_id}|default")],
        [InlineKeyboardButton("1 ثانية", callback_data=f"setspeed|{ch_id}|1"), InlineKeyboardButton("3 ثواني", callback_data=f"setspeed|{ch_id}|3")],
        [InlineKeyboardButton("5 ثواني", callback_data=f"setspeed|{ch_id}|5"), InlineKeyboardButton("10 ثواني", callback_data=f"setspeed|{ch_id}|10")],
        [InlineKeyboardButton("✏️ تخصيص رقم", callback_data=f"customspeed_{ch_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"postset_{ch_id}")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def set_channel_speed(client, callback):
    _, ch_id, value = callback.data.split("|", 2)
    if value == "default":
        db.set_channel_publish_delay(ch_id, None) if hasattr(db, "set_channel_publish_delay") else None
        await callback.answer("تم ضبطها على الافتراضي.")
    else:
        db.set_channel_publish_delay(ch_id, float(value)) if hasattr(db, "set_channel_publish_delay") else None
        await callback.answer(f"تم ضبطها على {value} ثانية.")
    callback.data = f"speedmenu_{ch_id}"
    await channel_speed_menu(client, callback)


async def custom_channel_speed_prompt(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {"state": "waiting_channel_speed", "ch_id": ch_id}
    await safe_edit(callback, "أرسل عدد الثواني لهذه القناة.\nمثال: 1 أو 2.5 أو 10\nأرسل 0 للرجوع للوضع الافتراضي:", InlineKeyboardMarkup([nav_row(f"speedmenu_{ch_id}")]))


def _format_ts(ts):
    if not ts:
        return "لا يوجد"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts)))
    except Exception:
        return str(ts)


async def source_stats_menu(client, callback):
    _, source_id, back = callback.data.split("|", 2)
    meta = db.get_source_meta(source_id) if hasattr(db, "get_source_meta") else {"name": str(source_id)}
    stats = db.get_source_stats(source_id) if hasattr(db, "get_source_stats") else {}
    text = (
        f"📊 **إحصائيات المصدر:**\n{entity_name(meta)}\nID: `{source_id}`\n\n"
        f"• المستلمة: {stats.get('received', 0)}\n"
        f"• المنشورة: {stats.get('published', 0)}\n"
        f"• المرفوضة: {stats.get('rejected', 0)}\n"
        f"• المتجاهلة: {stats.get('ignored', 0)}\n"
        f"• المكررة: {stats.get('duplicates', 0)}\n"
        f"• الأخطاء: {stats.get('errors', 0)}\n"
        f"• آخر رسالة: {stats.get('last_message_id') or 'لا يوجد'}\n"
        f"• آخر حدث: {stats.get('last_event') or 'لا يوجد'}\n"
        f"• السبب: {stats.get('last_reason') or 'لا يوجد'}\n"
        f"• الوقت: {_format_ts(stats.get('last_ts'))}"
    )
    await safe_edit(callback, text, InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"srcset|{source_id}|{back}")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ]))


async def source_log_menu(client, callback):
    _, source_id, back = callback.data.split("|", 2)
    meta = db.get_source_meta(source_id) if hasattr(db, "get_source_meta") else {"name": str(source_id)}
    logs = db.get_source_logs(source_id, 20) if hasattr(db, "get_source_logs") else []
    text = f"📋 **سجل المصدر:**\n{entity_name(meta)}\nID: `{source_id}`\n\n"
    if not logs:
        text += "لا توجد عمليات مسجلة."
    else:
        rows = []
        for item in reversed(logs[-20:]):
            rows.append(f"• {_format_ts(item.get('ts'))} | {item.get('event')} | msg={item.get('message_id')} | {item.get('reason') or ''}")
        text += "\n".join(rows[:20])
    await safe_edit(callback, text[:3900], InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"srcset|{source_id}|{back}")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ]))


async def test_source(client, callback):
    _, source_id, back = callback.data.split("|", 2)
    source_id_int = int(source_id)
    meta = db.get_source_meta(source_id) if hasattr(db, "get_source_meta") else {"name": source_id}
    kind = source_kind_label(source_id_int)
    targets = sorted(get_targets_for_source(source_id_int))
    last_seen = db.get_last_source_message(source_id_int) if hasattr(db, "get_last_source_message") else None
    try:
        last_msg = None
        async for msg in user_client.get_chat_history(source_id_int, limit=1):
            last_msg = msg
            break
        access = "✅ متاح"
        last_id = getattr(last_msg, "id", None) if last_msg else "لا يوجد"
        preview = (getattr(last_msg, "text", None) or getattr(last_msg, "caption", None) or "")[:120] if last_msg else ""
    except Exception as e:
        access = f"❌ فشل: {e}"
        last_id = "غير معروف"
        preview = ""
    text = (
        f"🧪 **اختبار المصدر:**\n{entity_name(meta)}\nID: `{source_id}`\n\n"
        f"• الوصول: {access}\n"
        f"• النوع: {kind}\n"
        f"• آخر ID محفوظ: {last_seen or 'لا يوجد'}\n"
        f"• آخر رسالة بالقناة: {last_id}\n"
        f"• القنوات المستهدفة: {targets if targets else 'لا توجد'}\n"
        f"• معاينة: {preview or 'لا يوجد'}"
    )
    await safe_edit(callback, text, InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"srcset|{source_id}|{back}")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ]))


async def copy_source_settings_prompt(client, callback):
    _, source_id, back = callback.data.split("|", 2)
    user_states[callback.from_user.id] = {"state": "source_settings_copied", "source_id": source_id, "back": back}
    meta = db.get_source_meta(source_id) if hasattr(db, "get_source_meta") else {"name": str(source_id)}
    text = (
        f"✅ تم نسخ إعدادات المصدر:\n{entity_name(meta)}\n\n"
        "الآن يمكنك:\n"
        "• الذهاب لأي مصدر آخر والضغط على 📋 لصق الإعدادات (واحد بواحد)\n"
        "• أو اضغط الزر أدناه للصق لعدة مصادر دفعة واحدة"
    )
    buttons = [
        [InlineKeyboardButton("📋 لصق لعدة مصادر دفعة واحدة", callback_data=f"bulkpastesrc|{source_id}|{back}")],
        [InlineKeyboardButton("🔙 رجوع للمصدر", callback_data=f"srcset|{source_id}|{back}")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def paste_source_settings(client, callback):
    _, target_source_id, back = callback.data.split("|", 2)
    saved = user_states.get(callback.from_user.id, {})
    from_source_id = saved.get("source_id") if saved.get("state") == "source_settings_copied" else None
    if not from_source_id:
        await callback.answer("ماكو إعدادات منسوخة. اضغط أولاً نسخ الإعدادات من مصدر آخر.", show_alert=True)
        return
    if str(from_source_id) == str(target_source_id):
        await callback.answer("هذا نفس المصدر المنسوخ.", show_alert=True)
        return
    copied = db.copy_source_settings(from_source_id, [target_source_id]) if hasattr(db, "copy_source_settings") else 0
    await callback.answer("تم لصق الإعدادات." if copied else "فشل لصق الإعدادات.", show_alert=True)
    callback.data = f"srcset|{target_source_id}|{back}"
    await source_settings_menu(client, callback)


async def bulk_paste_source_prompt(client, callback):
    """يفتح مربع إدخال نصي للصق إعدادات مصدر لعدة مصادر دفعة واحدة."""
    _, source_id, back = callback.data.split("|", 2)
    saved = user_states.get(callback.from_user.id, {})
    from_source = saved.get("source_id") if saved.get("state") == "source_settings_copied" else None
    if not from_source:
        await callback.answer("ماكو إعدادات منسوخة. ارجع واضغط نسخ الإعدادات أولاً.", show_alert=True)
        return
    user_states[callback.from_user.id] = {"state": "waiting_copy_source_settings", "source_id": from_source, "back": back}
    await safe_edit(
        callback,
        "أرسل المصادر التي تريد نسخ الإعدادات إليها.\nكل رابط/يوزر/ID بسطر مستقل:",
        InlineKeyboardMarkup([nav_row(f"srcset|{source_id}|{back}")])
    )

async def system_menu(client, callback):
    """القائمة الرئيسية لقسم النظام (خارج القنوات)."""
    buttons = [
        InlineKeyboardButton("🧪 الفحص الشامل", callback_data="full_check"),
        InlineKeyboardButton("🟢 حالة النظام", callback_data="system_status"),
        InlineKeyboardButton("🛠 إدارة التشغيل", callback_data="ops_menu"),
        InlineKeyboardButton("📝 إدارة السجل", callback_data="log_menu"),
        InlineKeyboardButton("🔔 التنبيهات", callback_data="notifications_menu"),
    ]
    rows = grid_buttons(buttons, 2)
    rows.append(nav_row("main_menu"))
    await safe_edit(callback, "🖥 **النظام**\n\n🧪 الفحص الشامل: يفحص الجلسة والبوت والقنوات والمصادر.\n🟢 حالة النظام: يعرض اتصال البوت والجلسة وأعداد القنوات.\n🛠 إدارة التشغيل: الصيانة واختبار كل القنوات وآخر الأخطاء.\n📝 إدارة السجل: عرض وحجم ومسح سجل البوت.\n🔔 التنبيهات: تشغيل/إيقاف إشعارات الفحوصات.", InlineKeyboardMarkup(rows))


async def system_status_menu(client, callback):
    ch_id = None
    if "|" in callback.data:
        ch_id = callback.data.split("|", 1)[1]
    channels = db.get_all_channels()
    public_count = len(db.get_public_sources())
    special_sources = set()
    for ch in channels:
        for src in ch.get("special_sources") or []:
            try:
                special_sources.add(int(src))
            except Exception:
                pass
    last_error = db.get_system_value("last_error", "لا يوجد") if hasattr(db, "get_system_value") else "لا يوجد"
    text = (
        "🟢 **حالة النظام**\n\n"
        f"• البوت: {'✅ متصل' if bot_client else '❌ غير معروف'}\n"
        f"• الجلسة: {'✅ متصلة' if user_client else '❌ غير معروف'}\n"
        f"• الوسيطة: `{config.MIDDLE_CHANNEL}`\n"
        f"• قنوات النشر: {len(channels)}\n"
        f"• المصادر العامة: {public_count}\n"
        f"• المصادر الخاصة: {len(special_sources)}\n"
        f"• مصادر الفحص الكلية: {len(get_polling_sources())}\n"
        f"• آخر خطأ: {last_error}\n\n🧪 فحص شامل: يعيد فحص كل مكونات النظام مباشرة."
    )
    full_btn = f"full_check|{ch_id}" if ch_id else "full_check"
    back_btn = f"sysset_{ch_id}" if ch_id else "system_menu"
    await safe_edit(callback, text, InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 فحص شامل", callback_data=full_btn)],
        nav_row(back_btn),
    ]))


async def full_check_menu(client, callback):
    ch_id = None
    if "|" in callback.data:
        ch_id = callback.data.split("|", 1)[1]
    lines = ["🧪 **الفحص الشامل**", ""]
    try:
        await user_client.get_me()
        lines.append("✅ الجلسة تعمل")
    except Exception as e:
        lines.append(f"❌ الجلسة: {e}")
    try:
        await bot_client.get_me()
        lines.append("✅ البوت يعمل")
    except Exception as e:
        lines.append(f"❌ البوت: {e}")
    try:
        await warm_middle_peer()
        lines.append("✅ الوسيطة تم فحصها")
    except Exception as e:
        lines.append(f"❌ الوسيطة: {e}")
    channels = db.get_all_channels()
    ok_ch = 0
    fail_ch = []
    for ch in channels[:80]:
        try:
            await hydrate_publish_channel(int(ch["id"]))
            ok_ch += 1
        except Exception as e:
            fail_ch.append(f"{entity_name(ch)}: {e}")
    lines.append(f"✅ قنوات النشر المتاحة: {ok_ch}/{len(channels)}")
    if fail_ch:
        lines.append("⚠️ قنوات فشلت:")
        lines.extend(["• " + x[:150] for x in fail_ch[:10]])
    sources = get_polling_sources()
    ok_src = 0
    fail_src = []
    for src in sources[:120]:
        try:
            await hydrate_source_channel(int(src))
            ok_src += 1
        except Exception as e:
            fail_src.append(f"{src}: {e}")
    lines.append(f"✅ المصادر المتاحة: {ok_src}/{len(sources)}")
    if fail_src:
        lines.append("⚠️ مصادر فشلت:")
        lines.extend(["• " + x[:150] for x in fail_src[:10]])
    await safe_edit(callback, "\n".join(lines)[:3900], InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 حالة النظام", callback_data=f"system_status|{ch_id}" if ch_id else "system_status")],
        nav_row(f"system_status|{ch_id}" if ch_id else "system_status"),
    ]))


async def warm_all_peers_after_import():
    await warm_middle_peer()
    for ch in db.get_all_channels():
        try:
            await hydrate_publish_channel(int(ch["id"]))
        except Exception as e:
            logger.warning(f"فشل تهيئة قناة نشر بعد الاستيراد {ch.get('id')}: {e}")
    for src in get_polling_sources():
        try:
            await hydrate_source_channel(int(src))
        except Exception as e:
            logger.warning(f"فشل تهيئة مصدر بعد الاستيراد {src}: {e}")



async def channel_quote_menu(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("القناة غير موجودة.")
        return
    qt = get_channel_quote_types_safe(ch_id)
    cfg = db.get_channel_config(ch_id) if hasattr(db, "get_channel_config") else {}
    title_quote = bool(cfg.get("title_quote"))
    sig_quote = bool(cfg.get("signature_quote"))
    text = (
        f"💬 **إعدادات الاقتباس لقناة:**\n{channel_display_name(ch_id)}\n\n"
        "اختر الأنواع التي تريد نشرها كاقتباس رسمي:\n\n"
        f"• العنوان: {'✅ مفعل' if title_quote else '❌ متوقف'}\n"
        f"• النصوص: {'✅ مفعل' if qt.get('text') else '❌ متوقف'}\n"
        f"• الصور: {'✅ مفعل' if qt.get('photo') else '❌ متوقف'}\n"
        f"• الفيديو: {'✅ مفعل' if qt.get('video') else '❌ متوقف'}\n"
        f"• الألبومات: {'✅ مفعل' if qt.get('album') else '❌ متوقف'}\n"
        f"• التوقيع: {'✅ مفعل' if sig_quote else '❌ متوقف'}\n\nاضغط النوع لتفعيله أو إيقافه كاقتباس رسمي في هذه القناة."
    )
    labels = {"text": "النصوص", "photo": "الصور", "video": "الفيديو", "album": "الألبومات"}
    buttons = [
        InlineKeyboardButton(f"{'✅' if title_quote else '❌'} العنوان", callback_data=f"ch_titlequote_{ch_id}"),
    ]
    for key in ["text", "photo", "video", "album"]:
        mark = "✅" if qt.get(key) else "❌"
        buttons.append(InlineKeyboardButton(f"{mark} {labels[key]}", callback_data=f"toggleqtype|{ch_id}|{key}"))
    buttons.append(InlineKeyboardButton(f"{'✅' if sig_quote else '❌'} التوقيع", callback_data=f"ch_sigquote_{ch_id}"))
    rows = grid_buttons(buttons, 2)
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"postset_{ch_id}"), InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")])
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def toggle_channel_quote_type(client, callback):
    try:
        _, ch_id, qtype = callback.data.split("|", 2)
    except Exception:
        await callback.answer("طلب غير صالح.", show_alert=True)
        return
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("القناة غير موجودة.")
        return
    current = get_channel_quote_types_safe(ch_id).get(qtype, False)
    if hasattr(db, "set_channel_quote_type"):
        db.set_channel_quote_type(ch_id, qtype, not current)
    else:
        db.update_channel(ch_id, "quote_publish", not current)
    await callback.answer("تم تحديث خيار الاقتباس.")
    callback.data = f"quotemenu_{ch_id}"
    await channel_quote_menu(client, callback)


async def toggle_channel_quote(client, callback):
    # توافق قديم: إذا وصل callback قديم، افتح قائمة الأنواع بدل تبديل عام.
    callback.data = callback.data.replace("togglequote_", "quotemenu_", 1)
    await channel_quote_menu(client, callback)


async def channel_hashtags_menu(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("القناة غير موجودة.")
        return
    tags = db.get_channel_hashtags(ch_id) if hasattr(db, "get_channel_hashtags") else ch.get("hashtags", [])
    shown = tags[:50]
    display = "\n".join(f"• `{t}`" for t in shown)
    if len(tags) > len(shown):
        display += f"\n… و{len(tags) - len(shown)} هاشتاك إضافي (يُعرض أول 50)."
    text = (
        f"🏷 **هاشتاكات قناة النشر:**\n{channel_display_name(ch)}\n\n"
        "تضاف تلقائياً أسفل المنشور لهذه القناة فقط.\n\n"
        "الحالية:\n" + (display if tags else "لا توجد.") + "\n\n➕ إضافة جماعية: تضيف هاشتاكات للقناة (كل واحد بسطر).\n🗑 حذف جماعي: يزيل هاشتاكات موجودة."
    )
    buttons = [
        InlineKeyboardButton("➕ إضافة جماعية", callback_data=f"addhashtags_{ch_id}"),
        InlineKeyboardButton("🗑 حذف جماعي", callback_data=f"delhashtags_{ch_id}"),
    ]
    rows = grid_buttons(buttons, 2)
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"postset_{ch_id}"), InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")])
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def add_channel_hashtags_prompt(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {"state": "waiting_channel_hashtags_add", "ch_id": ch_id}
    await safe_edit(callback, "أرسل هاشتاك أو مجموعة هاشتاكات.\nكل هاشتاك بسطر مستقل:", InlineKeyboardMarkup([nav_row(f"hashtags_{ch_id}")]))


async def del_channel_hashtags_prompt(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {"state": "waiting_channel_hashtags_del", "ch_id": ch_id}
    tags = db.get_channel_hashtags(ch_id) if hasattr(db, "get_channel_hashtags") else []
    shown = tags[:50]
    current = "\n".join(f"• {t}" for t in shown) if tags else "لا توجد هاشتاكات حالياً."
    if len(tags) > len(shown):
        current += f"\n… و{len(tags) - len(shown)} هاشتاك إضافي."
    await safe_edit(callback, "أرسل الهاشتاكات التي تريد حذفها.\nكل هاشتاك بسطر مستقل.\n\nالحالي:\n" + current, InlineKeyboardMarkup([nav_row(f"hashtags_{ch_id}")]))


async def test_publish_channel(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("القناة غير موجودة.")
        return
    try:
        text = compose_channel_post_text(f"✅ اختبار نشر ناجح\n{entity_name(ch)}", ch_id, ch.get("tail", ""))
        formatted, parse_mode, entities = format_outgoing_payload_for_channel(text, ch_id, "text")
        await safe_send_channel_message(int(ch_id), formatted, parse_mode=parse_mode, entities=entities)
        record_channel_success(ch_id)
        await callback.answer("تم إرسال اختبار النشر.")
        await notify_admins(f"تم اختبار النشر بنجاح إلى:\n{channel_display_name(ch)}")
    except Exception as e:
        await record_channel_failure_and_maybe_alert(ch_id, e)
        await callback.answer("فشل اختبار النشر.", show_alert=True)
        await notify_admins(f"فشل اختبار النشر إلى:\n{channel_display_name(ch)}\n\n{e}")


async def operations_menu(client, callback):
    ch_id = None
    if "|" in callback.data:
        ch_id = callback.data.split("|", 1)[1]
    maintenance = db.is_maintenance_mode() if hasattr(db, "is_maintenance_mode") else False
    text = (
        "🛠 **إدارة التشغيل**\n\n"
        f"وضع الصيانة: {'✅ مفعل' if maintenance else '❌ متوقف'}\n\n"
        "وضع الصيانة يوقف النشر، لكن يبقي فحص المصادر مستمر حتى لا تتراكم الأخبار.\n\n🛠 تبديل الصيانة: يوقف النشر ويبقي فحص المصادر مستمراً.\n🧪 اختبار كل القنوات: يفحص إمكانية النشر في كل القنوات.\n⚠️ آخر الأخطاء: يعرض آخر 20 خطأ مسجلاً."
    )
    buttons = [
        InlineKeyboardButton("🛠 تبديل الصيانة", callback_data=f"toggle_maintenance|{ch_id}" if ch_id else "toggle_maintenance"),
        InlineKeyboardButton("🧪 اختبار كل القنوات", callback_data=f"test_all_channels|{ch_id}" if ch_id else "test_all_channels"),
        InlineKeyboardButton("⚠️ آخر الأخطاء", callback_data=f"errors_menu|{ch_id}" if ch_id else "errors_menu"),
    ]
    rows = grid_buttons(buttons, 2)
    rows.append(nav_row(f"sysset_{ch_id}" if ch_id else "system_menu"))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def toggle_maintenance_mode(client, callback):
    ch_id = None
    if "|" in callback.data:
        ch_id = callback.data.split("|", 1)[1]
    current = db.is_maintenance_mode() if hasattr(db, "is_maintenance_mode") else False
    if hasattr(db, "set_maintenance_mode"):
        db.set_maintenance_mode(not current)
    await callback.answer("تم تشغيل وضع الصيانة." if not current else "تم إيقاف وضع الصيانة.")
    callback.data = f"ops_menu|{ch_id}" if ch_id else "ops_menu"
    await operations_menu(client, callback)



async def toggle_short_posts_filter(client, callback):
    ch_id = None
    if "|" in callback.data:
        ch_id = callback.data.split("|", 1)[1]
    if ch_id and hasattr(db, "get_channel_ignore_short_posts"):
        current = bool(db.get_channel_ignore_short_posts(ch_id))
        if hasattr(db, "set_channel_ignore_short_posts"):
            db.set_channel_ignore_short_posts(ch_id, not current)
    else:
        current = is_ignore_short_posts_enabled()
        if hasattr(db, "set_ignore_short_posts"):
            db.set_ignore_short_posts(not current)
    await callback.answer("تم تحديث فلتر المنشورات القصيرة للقناة." if ch_id else "تم تحديث فلتر المنشورات القصيرة العام.")
    callback.data = f"postset_{ch_id}" if ch_id else "ops_menu"
    await (post_settings_menu(client, callback) if ch_id else operations_menu(client, callback))


async def errors_menu(client, callback):
    ch_id = None
    if "|" in callback.data:
        ch_id = callback.data.split("|", 1)[1]
    errors = db.get_last_errors(20) if hasattr(db, "get_last_errors") else []
    text = "⚠️ **آخر الأخطاء:**\n\n⚙️ عرض آخر 20 خطأ مسجل في البوت.\n\n"
    if not errors:
        text += "لا توجد أخطاء مسجلة."
    else:
        rows_txt = []
        for e in reversed(errors[-20:]):
            rows_txt.append(f"• {_format_ts(e.get('ts'))}\n  {e.get('context')}\n  `{str(e.get('error'))[:180]}`")
        text += "\n\n".join(rows_txt)
    buttons = [
        [InlineKeyboardButton("🗑 مسح الأخطاء", callback_data=f"clear_errors|{ch_id}" if ch_id else "clear_errors")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"ops_menu|{ch_id}" if ch_id else "ops_menu"), InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ]
    await safe_edit(callback, text[:3900], InlineKeyboardMarkup(buttons))


async def clear_errors(client, callback):
    ch_id = None
    if "|" in callback.data:
        ch_id = callback.data.split("|", 1)[1]
    if hasattr(db, "clear_last_errors"):
        db.clear_last_errors()
    await callback.answer("تم مسح لوحة الأخطاء.")
    callback.data = f"errors_menu|{ch_id}" if ch_id else "errors_menu"
    await errors_menu(client, callback)


def _read_log_tail_lines(path, max_lines=500, chunk_size=8192):
    """يقرأ آخر max_lines سطر فقط من الملف دون تحميله كاملاً في الذاكرة."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            data = b""
            lines_found = 0
            pos = file_size
            while pos > 0 and lines_found <= max_lines:
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                data = chunk + data
                lines_found = data.count(b"\n")
            text = data.decode("utf-8", errors="ignore")
            lines = text.splitlines()
            return lines[-max_lines:]
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.error(f"فشل قراءة ملف السجل: {e}")
        return []


async def log_management_menu(client, callback):
    ch_id = None
    if "|" in callback.data:
        ch_id = callback.data.split("|", 1)[1]
    text = "📝 **إدارة السجل**\n\n👁️ عرض آخر 500 سطر: يقرأ آخر أسطر سجل البوت.\n🔄 تحديث السجل: يعيد قراءة السجل.\n📦 عرض حجم السجل: يعرض حجم ملف السجل بالميغابايت.\n🗑️ مسح السجل: يفرّغ ملف السجل فقط (البوت يستمر بالعمل)."
    buttons = [
        [InlineKeyboardButton("👁️ عرض آخر 500 سطر", callback_data=f"log_view|{ch_id}" if ch_id else "log_view")],
        [InlineKeyboardButton("🔄 تحديث السجل", callback_data=f"log_refresh|{ch_id}" if ch_id else "log_refresh")],
        [InlineKeyboardButton("📦 عرض حجم السجل", callback_data=f"log_size|{ch_id}" if ch_id else "log_size")],
        [InlineKeyboardButton("🗑️ مسح السجل", callback_data=f"log_clear_prompt|{ch_id}" if ch_id else "log_clear_prompt")],
        nav_row(f"sysset_{ch_id}" if ch_id else "system_menu"),
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def view_bot_log(client, callback):
    ch_id = None
    if "|" in callback.data:
        ch_id = callback.data.split("|", 1)[1]
    lines = _read_log_tail_lines(BOT_LOG_FILE, 500)
    if not lines:
        body = "لا يوجد سجل حالياً."
    else:
        body = "\n".join(lines)
    text = f"👁️ **آخر {len(lines)} سطر من السجل:**\n\n`{body}`"
    if len(text) > 3900:
        text = text[-3900:]
        text = f"👁️ **آخر أسطر السجل (مقتصّة لطول الرسالة):**\n\n`{text}`"
    buttons = [
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"log_view|{ch_id}" if ch_id else "log_view")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"log_menu|{ch_id}" if ch_id else "log_menu"), InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def show_log_size(client, callback):
    ch_id = None
    if "|" in callback.data:
        ch_id = callback.data.split("|", 1)[1]
    try:
        size_bytes = os.path.getsize(BOT_LOG_FILE)
        size_mb = size_bytes / (1024 * 1024)
        text = f"📦 **حجم ملف السجل:**\n\n{size_mb:.3f} MB"
    except FileNotFoundError:
        text = "📦 لا يوجد ملف سجل حالياً."
    except Exception as e:
        text = f"❌ تعذر قراءة حجم السجل: {e}"
    buttons = [
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"log_menu|{ch_id}" if ch_id else "log_menu"), InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def clear_log_prompt(client, callback):
    ch_id = None
    if "|" in callback.data:
        ch_id = callback.data.split("|", 1)[1]
    text = (
        "⚠️ **تأكيد مسح السجل**\n\n"
        "سيتم تفريغ ملف السجل فقط. البوت سيستمر بالعمل والكتابة بنفس الملف بدون أي إعادة تشغيل.\n\n"
        "هل تريد المتابعة؟"
    )
    buttons = [
        [InlineKeyboardButton("✅ نعم، امسح السجل", callback_data=f"log_clear_confirm|{ch_id}" if ch_id else "log_clear_confirm")],
        nav_row(f"log_menu|{ch_id}" if ch_id else "main_menu"),
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def confirm_clear_log(client, callback):
    ch_id = None
    if "|" in callback.data:
        ch_id = callback.data.split("|", 1)[1]
    try:
        with open(BOT_LOG_FILE, "w", encoding="utf-8"):
            pass
        await callback.answer("تم مسح السجل.")
    except Exception as e:
        logger.error(f"فشل مسح ملف السجل: {e}")
        await callback.answer("تعذر مسح السجل.", show_alert=True)
    callback.data = f"log_menu|{ch_id}" if ch_id else "log_menu"
    await log_management_menu(client, callback)


async def named_backup_prompt(client, callback):
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {"state": "waiting_named_backup"}
    await safe_edit(callback, "أرسل اسم النسخة الاحتياطية.\nمثال:\nstable_before_platform", InlineKeyboardMarkup([nav_row("main_menu")]))


async def test_all_channels(client, callback):
    ch_id = None
    if "|" in callback.data:
        ch_id = callback.data.split("|", 1)[1]
    channels = db.get_all_channels()
    ok = 0
    fail = 0
    for ch in channels:
        if ch.get("paused"):
            continue
        try:
            ch_id_int = int(ch["id"])
            text = compose_channel_post_text(f"✅ اختبار نشر جماعي ناجح\n{entity_name(ch)}", ch_id_int, ch.get("tail", ""))
            formatted, parse_mode, entities = format_outgoing_payload_for_channel(text, ch_id_int, "text")
            await safe_send_channel_message(ch_id_int, formatted, parse_mode=parse_mode, entities=entities)
            record_channel_success(ch_id_int)
            ok += 1
            await asyncio.sleep(get_publish_delay_for_channel(ch_id_int))
        except Exception as e:
            fail += 1
            await record_channel_failure_and_maybe_alert(ch.get("id"), e)
    await safe_edit(callback, f"🧪 **نتيجة اختبار كل القنوات:**\n\n✅ نجح: {ok}\n❌ فشل: {fail}", InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"ops_menu|{ch_id}" if ch_id else "ops_menu"), InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ]))
async def add_special_source_prompt(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {
        "state": "waiting_special_source",
        "ch_id": ch_id
    }
    await safe_edit(callback, "أرسل مصدر خاص واحد أو عدة مصادر خاصة.\nكل رابط/يوزر/ID بسطر مستقل:", InlineKeyboardMarkup([nav_row(f"srcset_{ch_id}")]))

async def delete_special_source_prompt(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("غير موجودة.")
        return
    sources = ch.get("special_sources", [])
    if not sources:
        await callback.answer("لا توجد مصادر.")
        return
    buttons = []
    for idx, src in enumerate(sources):
        name = entity_name(src, is_source=True)
        buttons.append([InlineKeyboardButton(f"🗑 حذف {name}", callback_data=f"confdelspec_{ch_id}_{idx}")])
    buttons.append(nav_row(f"specsrc_{ch_id}"))
    await safe_edit(callback, "اختر المصدر لحذفه:", InlineKeyboardMarkup(buttons))

async def confirm_delete_special_source(client, callback):
    parts = callback.data.split("_")
    ch_id = parts[1]
    idx = int(parts[2])

    ch = db.get_channel(ch_id)

    if not ch:
        await callback.answer("غير موجودة.")
        return

    sources = ch.get("special_sources", [])

    if idx < 0 or idx >= len(sources):
        await callback.answer("المصدر غير موجود.")
        return

    sources.pop(idx)
    db.update_channel(ch_id, "special_sources", sources)

    await callback.answer("تم الحذف.")
    await manage_special_sources(client, callback)

async def show_stats(client, callback):
    channels = db.get_all_channels()
    total_posts = sum(ch.get("posts_count", 0) for ch in channels)
    pub_src = len(db.get_public_sources())
    words = len(db.get_blocked_words())

    text = "📊 **الإحصائيات:**\n\n"
    text += f"• إجمالي المنشورات: **{total_posts}**\n"
    text += f"• قنوات النشر: {len(channels)}\n"
    text += f"• المصادر العامة: {pub_src}\n"
    text += f"• الكلمات المحظورة: {words}\n\n"

    if channels:
        text += "**تفصيل المنشورات حسب القناة:**\n"
        for ch in channels:
            text += f"• {entity_name(ch)}\n  ID: `{ch['id']}`\n  المنشورات: **{ch.get('posts_count', 0)}**\n"

    await safe_edit(
        callback,
        text,
        InlineKeyboardMarkup([nav_row("main_menu")])
    )

async def handle_text_input(client, message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    if uid not in user_states:
        return
    state = user_states[uid].get("state")
    text = message.text.strip()

    if state and state.startswith("blogger_"):
        await handle_blogger_text_input(client, message)
        return

    try:
        if state == "waiting_channel_id":
            results = []
            for raw in split_bulk_lines(text):
                try:
                    chat = await resolve_chat_info_timeout(raw, prefer_user=False)
                    bot_status = ""
                    bot_admin = False
                    check_note = ""
                    try:
                        bot_member = await bot_client.get_chat_member(int(chat.id), (await bot_client.get_me()).id)
                        bot_status = member_status_value(getattr(bot_member, "status", None))
                        bot_admin = is_bot_admin_status(bot_status)
                        check_note = "✅ البوت مشرف" if bot_admin else "❌ البوت ليس مشرفاً"
                    except Exception as verr:
                        bot_status = "unknown"
                        check_note = f"تعذر التحقق من البوت: {str(verr)[:60]}"
                    meta = chat_meta(chat, raw)
                    created = db.add_channel(chat.id, **meta)
                    db.update_channel(chat.id, "bot_admin", bot_admin)
                    db.update_channel(chat.id, "bot_status", bot_status)
                    results.append(("ok" if created else "exists", f"{meta['title']} | {check_note}", raw))
                except Exception as e:
                    results.append(("fail", raw, "انتهت المهلة أو تعذر جلب المعلومات" if isinstance(e, asyncio.TimeoutError) else str(e)))
            await message.reply(format_bulk_report("📢 نتيجة إضافة قنوات النشر", results))
            await show_channels_menu_from_message(message)
        elif state == "waiting_tail":
            ch_id = user_states[uid]["ch_id"]
            db.update_channel(ch_id, "tail", text)
            await message.reply("✅ تم حفظ التوقيع.")
            ch = db.get_channel(ch_id)
            if ch:
                await message.reply(f"إعدادات القناة: {entity_name(ch)}", reply_markup=channel_buttons(ch_id))
        elif state == "waiting_public_source":
            results = []
            for raw in split_bulk_lines(text):
                try:
                    chat = await resolve_chat_info_timeout(raw, prefer_user=True)
                    meta = chat_meta(chat, raw)
                    created = db.add_public_source(chat.id, **meta)
                    results.append(("ok" if created else "exists", meta["title"], raw))
                except Exception as e:
                    results.append(("fail", raw, "انتهت المهلة أو تعذر جلب المعلومات" if isinstance(e, asyncio.TimeoutError) else str(e)))
            await message.reply(format_bulk_report("🌐 نتيجة إضافة المصادر العامة", results))
            await show_public_sources_menu_from_message(message)
        elif state == "waiting_blocked_word":
            logger.info(f"handle_text_input: waiting_blocked_word from user {uid}")
            added = 0
            exists = 0
            for word in split_bulk_lines(text):
                if db.add_blocked_word(word):
                    added += 1
                else:
                    exists += 1
            logger.info(f"waiting_blocked_word: added={added}, exists={exists}")
            await message.reply(f"✅ تمت إضافة {added} كلمة.\n⚠️ موجودة مسبقاً/فارغة: {exists}")
            await show_blocked_words_menu_from_message(message)
        elif state == "waiting_channel_blocked_word":
            logger.info(f"handle_text_input: waiting_channel_blocked_word from user {uid}")
            ch_id = user_states[uid]["ch_id"]
            added = 0
            exists = 0
            for word in split_bulk_lines(text):
                if db.add_channel_blocked_word(ch_id, word):
                    added += 1
                else:
                    exists += 1
            logger.info(f"waiting_channel_blocked_word: channel={ch_id}, added={added}, exists={exists}")
            ch = db.get_channel(ch_id)
            await message.reply(
                f"✅ تمت إضافة {added} كلمة لقناة {entity_name(ch) if ch else ch_id}.\n⚠️ موجودة مسبقاً/فارغة: {exists}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚫 رجوع للكلمات المحظورة", callback_data=f"chwords|{ch_id}")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ])
            )
        elif state == "waiting_special_source":
            ch_id = user_states[uid]["ch_id"]
            ch = db.get_channel(ch_id)
            if not ch:
                await message.reply("❌ القناة غير موجودة.")
                return
            sources = ch.get("special_sources", [])
            results = []
            for raw in split_bulk_lines(text):
                try:
                    chat = await resolve_chat_info_timeout(raw, prefer_user=True)
                    meta = chat_meta(chat, raw)
                    db.update_source_meta(chat.id, **meta) if hasattr(db, "update_source_meta") else None
                    if int(chat.id) not in [int(x) for x in sources]:
                        sources.append(int(chat.id))
                        results.append(("ok", meta["title"], raw))
                    else:
                        results.append(("exists", meta["title"], raw))
                except Exception as e:
                    results.append(("fail", raw, "انتهت المهلة أو تعذر جلب المعلومات" if isinstance(e, asyncio.TimeoutError) else str(e)))
            db.update_channel(ch_id, "special_sources", sources)
            await message.reply(format_bulk_report("🔍 نتيجة إضافة المصادر المخصصة", results))
            await show_special_sources_menu_from_message(message, ch_id)
        elif state == "waiting_source_cleanup_add":
            source_id = user_states[uid]["source_id"]
            back = user_states[uid].get("back", "menu_public_src")
            terms = split_terms_lines(text)
            result = db.add_source_remove_terms(source_id, terms) if hasattr(db, "add_source_remove_terms") else {"added": 0, "exists": 0}
            await message.reply(
                f"✅ تمت إضافة {result.get('added', 0)} عنصر للتنظيف الذكي.\n⚠️ موجود مسبقاً/فارغ: {result.get('exists', 0)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🧹 رجوع للتنظيف الذكي", callback_data=f"clean_src|{source_id}|{back}")],
                    [InlineKeyboardButton("⚙️ إعدادات المصدر", callback_data=f"srcset|{source_id}|{back}")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ])
            )
        elif state == "waiting_source_cleanup_del":
            source_id = user_states[uid]["source_id"]
            back = user_states[uid].get("back", "menu_public_src")
            terms = split_terms_lines(text)
            result = db.remove_source_remove_terms(source_id, terms) if hasattr(db, "remove_source_remove_terms") else {"removed": 0, "missing": 0}
            await message.reply(
                f"✅ تم حذف {result.get('removed', 0)} عنصر من التنظيف الذكي.\n⚠️ غير موجود: {result.get('missing', 0)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🧹 رجوع للتنظيف الذكي", callback_data=f"clean_src|{source_id}|{back}")],
                    [InlineKeyboardButton("⚙️ إعدادات المصدر", callback_data=f"srcset|{source_id}|{back}")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ])
            )
        elif state == "waiting_global_cleanup_add":
            terms = split_terms_lines(text)
            result = db.add_global_remove_terms(terms) if hasattr(db, "add_global_remove_terms") else {"added": 0, "exists": 0}
            await message.reply(
                f"✅ تمت إضافة {result.get('added', 0)} عنصر لقائمة الحذف العامة.\n⚠️ موجود مسبقاً/فارغ: {result.get('exists', 0)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🧹 رجوع لقائمة الحذف العامة", callback_data="global_clean")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ])
            )
        elif state == "waiting_global_cleanup_del":
            terms = split_terms_lines(text)
            result = db.remove_global_remove_terms(terms) if hasattr(db, "remove_global_remove_terms") else {"removed": 0, "missing": 0}
            await message.reply(
                f"✅ تم حذف {result.get('removed', 0)} عنصر من قائمة الحذف العامة.\n⚠️ غير موجود: {result.get('missing', 0)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🧹 رجوع لقائمة الحذف العامة", callback_data="global_clean")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ])
            )
        elif state == "waiting_channel_delete_term_add":
            logger.info(f"handle_text_input: waiting_channel_delete_term_add from user {uid}")
            ch_id = user_states[uid]["ch_id"]
            terms = split_terms_lines(text)
            result = db.add_channel_delete_terms(ch_id, terms)
            logger.info(f"waiting_channel_delete_term_add: channel={ch_id}, result={result}")
            ch = db.get_channel(ch_id)
            await message.reply(
                f"✅ تمت إضافة {result.get('added', 0)} عنصر لقناة {entity_name(ch) if ch else ch_id}.\n⚠️ موجود مسبقاً/فارغ: {result.get('exists', 0)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🧹 رجوع لقائمة الكلمات المحذوفة", callback_data=f"chdelterms|{ch_id}")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ])
            )
        elif state == "waiting_channel_delete_term_del":
            ch_id = user_states[uid]["ch_id"]
            terms = split_terms_lines(text)
            result = db.remove_channel_delete_terms(ch_id, terms)
            ch = db.get_channel(ch_id)
            await message.reply(
                f"✅ تم حذف {result.get('removed', 0)} عنصر من قناة {entity_name(ch) if ch else ch_id}.\n⚠️ غير موجود: {result.get('missing', 0)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🧹 رجوع لقائمة الكلمات المحذوفة", callback_data=f"chdelterms|{ch_id}")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ])
            )
        elif state == "waiting_channel_speed":
            ch_id = user_states[uid]["ch_id"]
            value = text.strip()
            if value in {"0", "افتراضي", "default", "DEFAULT", ""}:
                ok = db.set_channel_publish_delay(ch_id, None) if hasattr(db, "set_channel_publish_delay") else False
                msg = "✅ تم إرجاع سرعة القناة للوضع الافتراضي."
            else:
                try:
                    delay = max(0.0, float(value))
                    ok = db.set_channel_publish_delay(ch_id, delay) if hasattr(db, "set_channel_publish_delay") else False
                    msg = f"✅ تم حفظ سرعة القناة: {delay} ثانية."
                except Exception:
                    ok = False
                    msg = "❌ أرسل رقم بالثواني، أو 0 للوضع الافتراضي."
            await message.reply(msg, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏱ رجوع لسرعة النشر", callback_data=f"speedmenu_{ch_id}")],
                [InlineKeyboardButton("⚙️ إعدادات القناة", callback_data=f"ch_{ch_id}")],
                [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
            ]))
        elif state == "waiting_copy_source_settings":
            from_source = user_states[uid]["source_id"]
            back = user_states[uid].get("back", "menu_public_src")
            targets = []
            failed = []
            for raw in split_bulk_lines(text):
                try:
                    chat = await resolve_chat_info_timeout(raw, prefer_user=True)
                    meta = chat_meta(chat, raw)
                    db.update_source_meta(chat.id, **meta) if hasattr(db, "update_source_meta") else None
                    targets.append(int(chat.id))
                except Exception as e:
                    try:
                        targets.append(int(raw.strip()))
                    except Exception:
                        failed.append(f"{raw}: {e}")
            copied = db.copy_source_settings(from_source, targets) if hasattr(db, "copy_source_settings") else 0
            msg = f"✅ تم نسخ إعدادات المصدر إلى {copied} مصدر."
            if failed:
                msg += "\n⚠️ فشل:\n" + "\n".join(failed[:10])
            await message.reply(msg, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ إعدادات المصدر", callback_data=f"srcset|{from_source}|{back}")],
                [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
            ]))

        elif state == "waiting_channel_hashtags_add":
            ch_id = user_states[uid]["ch_id"]
            terms = split_terms_lines(text)
            result = db.add_channel_hashtags(ch_id, terms) if hasattr(db, "add_channel_hashtags") else {"added": 0, "exists": 0}
            await message.reply(
                f"✅ تمت إضافة {result.get('added', 0)} هاشتاك.\n⚠️ موجود مسبقاً/فارغ: {result.get('exists', 0)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏷 رجوع للهاشتاكات", callback_data=f"hashtags_{ch_id}")],
                    [InlineKeyboardButton("⚙️ إعدادات القناة", callback_data=f"ch_{ch_id}")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ])
            )
        elif state == "waiting_channel_hashtags_del":
            ch_id = user_states[uid]["ch_id"]
            terms = split_terms_lines(text)
            result = db.remove_channel_hashtags(ch_id, terms) if hasattr(db, "remove_channel_hashtags") else {"removed": 0, "missing": 0}
            await message.reply(
                f"✅ تم حذف {result.get('removed', 0)} هاشتاك.\n⚠️ غير موجود: {result.get('missing', 0)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏷 رجوع للهاشتاكات", callback_data=f"hashtags_{ch_id}")],
                    [InlineKeyboardButton("⚙️ إعدادات القناة", callback_data=f"ch_{ch_id}")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ])
            )
        elif state == "waiting_named_backup":
            name = text.strip()
            path = db.create_named_backup(name) if hasattr(db, "create_named_backup") else ""
            await message.reply(
                f"✅ تم إنشاء Backup باسم:\n`{name}`\n\nالملف:\n`{path}`",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛠 رجوع لإدارة التشغيل", callback_data="ops_menu")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ])
            )
        # Multi-Bot Expansion: Add Session
        elif state == "waiting_session_add":
            parts = [p.strip() for p in text.split("|", 2)]
            if len(parts) < 3:
                await message.reply("❌ التنسيق خطأ. استخدم:\n`API_ID | API_HASH | SESSION_STRING`")
                return
            api_id, api_hash, session_string = parts[0], parts[1], parts[2]
            if not api_id.isdigit():
                await message.reply("❌ API_ID يجب أن يكون رقماً.")
                return
            ok = db.add_session(api_id, api_hash, session_string)
            if ok:
                await message.reply("✅ تمت إضافة الجلسة.", reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📱 إدارة الجلسات", callback_data="sessions_list")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ]))
            else:
                await message.reply("❌ فشل إضافة الجلسة. قد يكون المعرف موجوداً مسبقاً.")
        # Multi-Bot Expansion: Add AI Key
        elif state == "waiting_ai_key_add":
            parts = [p.strip() for p in text.split("|", 1)]
            if len(parts) < 2:
                await message.reply("❌ التنسيق خطأ. استخدم:\n`المزود | المفتاح`\nمثال: `gemini | AIzaSy...`")
                return
            provider, api_key = parts[0], parts[1]
            ok = db.add_ai_key(provider, api_key)
            if ok:
                await message.reply("✅ تمت إضافة مفتاح AI.", reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🧠 إدارة المفاتيح", callback_data="ai_list")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ]))
            else:
                await message.reply("❌ فشل إضافة المفتاح.")
        # Multi-Bot Expansion: Add Publishing Bot
        elif state == "waiting_bot_add":
            token = text.strip()
            if not db.bot_manager.validate_token_format(token):
                await message.reply("❌ التوكن غير صالح. يجب أن يحتوي على `:`")
                return
            # تحقق فوري من صحة التوكن عبر Telegram API
            ver = await verifier.validate_token(token)
            if not ver.get("valid"):
                await message.reply(f"❌ التوكن غير صالح: {ver.get('error', 'فشل الاتصال')}")
                return
            bot_username = ver.get("username", "")
            bot_name = ver.get("first_name", "")
            ok = db.bot_manager.add_bot(token, username=bot_username, name=bot_name) if hasattr(db, "bot_manager") else db.add_publishing_bot(token, username=bot_username, name=bot_name)
            if ok:
                # مسح الكاش لهذا التوكن لأنه جديد
                if hasattr(db, "cache_invalidate"):
                    db.cache_invalidate(f"token_valid|{token[:10]}")
                await message.reply("✅ تمت إضافة بوت النشر.", reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🤖 إدارة البوتات", callback_data="bots_list")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ]))
            else:
                await message.reply("❌ فشل إضافة البوت.")
        elif state == "waiting_bot_rename":
            bid = user_states[uid].get("bot_id", "")
            new_name = text.strip()
            if new_name:
                db.update_publishing_bot(bid, name=new_name)
                await message.reply("✅ تم تحديث الاسم.", reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🤖 رجوع", callback_data=f"bot_show_{bid}")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ]))
            else:
                await message.reply("❌ الاسم فارغ.")
        # Multi-Bot Expansion: Add Website
        elif state == "waiting_website_add":
            parts = [p.strip() for p in text.split("|", 1)]
            url = parts[0]
            selector = parts[1] if len(parts) > 1 else "body"
            if not url.startswith("http"):
                await message.reply("❌ الرابط يجب أن يبدأ بـ http:// أو https://")
                return
            ok = db.add_website(url, selector=selector)
            if ok:
                await message.reply("✅ تمت إضافة الموقع.", reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🌐 إدارة المواقع", callback_data="web_list")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ]))
            else:
                await message.reply("❌ فشل إضافة الموقع.")
        # Multi-Bot Expansion: Edit Website
        elif state == "waiting_website_edit":
            wid = user_states[uid].get("website_id", "")
            parts = [p.strip() for p in text.split("|", 1)]
            url = parts[0]
            selector = parts[1] if len(parts) > 1 else "body"
            if not url.startswith("http"):
                await message.reply("❌ الرابط يجب أن يبدأ بـ http:// أو https://")
                return
            ok = db.update_website(wid, url=url, selector=selector)
            if ok:
                await message.reply("✅ تم تحديث الموقع.", reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🌐 رجوع للموقع", callback_data=f"web_show_{wid}")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ]))
            else:
                await message.reply("❌ فشل تحديث الموقع.")
    except Exception as e:
        logger.error(f"خطأ في إدخال المستخدم: {e}")
        await message.reply(f"❌ فشل التنفيذ: {e}")
    finally:
        user_states.pop(uid, None)

def _to_int_set(values):
    result = set()
    for value in values or []:
        try:
            result.add(int(value))
        except Exception:
            pass
    return result


def get_special_source_map():
    """يرجع خريطة المصادر الخاصة: source_id -> set(channel_ids)."""
    mapping = {}
    for ch in db.get_all_channels():
        if ch.get("paused"):
            continue
        try:
            ch_id = int(ch["id"])
        except Exception:
            continue
        for src in ch.get("special_sources") or []:
            try:
                src_id = int(src)
            except Exception:
                continue
            mapping.setdefault(src_id, set()).add(ch_id)
    return mapping


def get_polling_sources():
    """يجمع مصادر الفحص: المصادر العامة + المصادر الخاصة، بدون تكرار."""
    sources = set()
    for src in db.get_public_sources() or []:
        try:
            sources.add(int(src))
        except Exception:
            pass
    for src in get_special_source_map().keys():
        sources.add(int(src))
    return sorted(sources)


def source_kind_label(source_id):
    """نوع المصدر للّوج: خاص يغلب على العام إذا مضاف بالمكانين."""
    source_id = int(source_id)
    if source_id in get_special_source_map():
        return "خاص"
    if source_id in _to_int_set(db.get_public_sources()):
        return "عام"
    return "غير معروف"


def get_targets_for_source(source_id):
    """يرجع قنوات النشر التي يجب أن تستقبل منشوراً من هذا المصدر.

    القاعدة:
    - إذا المصدر مضاف كمصدر خاص لأي قناة: ينشر فقط للقنوات التي أضافته.
    - إذا المصدر عام فقط: ينشر فقط للقنوات العامة التي لا تحتوي مصادر خاصة.
    - إذا المصدر موجود بالعام والخاص بالغلط: الخاص يغلب.
    """
    source_id = int(source_id)
    all_channels = db.get_all_channels()
    public_sources = _to_int_set(db.get_public_sources())
    special_map = get_special_source_map()
    target_ids = set()

    # الخاص يغلب على العام
    if source_id in special_map:
        target_ids.update(special_map.get(source_id, set()))
        logger.info(f"🟢 المصدر {source_id} خاص؛ القنوات المستهدفة: {sorted(target_ids)}")
        return target_ids

    # مصدر عام: فقط القنوات التي لا تمتلك مصادر خاصة
    if source_id in public_sources:
        for ch in all_channels:
            if ch.get("paused"):
                continue
            specials = ch.get("special_sources") or []
            if specials:
                continue
            try:
                target_ids.add(int(ch["id"]))
            except Exception as e:
                logger.error(f"تعذر تحويل قناة النشر إلى رقم: {ch.get('id')} | {e}")
        return target_ids

    return target_ids


def blocked_word_in_text(text):
    if not text:
        return None
    for word in db.get_blocked_words():
        if word and word in text:
            return word
    return None


def section_scope_for_channel(channel_id):
    """معرف قسم/قناة النشر المستخدم لنطاق Dedup المشترك. القسم الجديد ينشأ تلقائياً."""
    return f"ch_{int(channel_id)}"


def section_label_for_channel(channel_id):
    """تسمية القسم لأغراض اللوج (اسم القناة)، بدون أي Secrets."""
    try:
        ch = db.get_channel(channel_id)
        if ch and ch.get("name"):
            return str(ch["name"]).strip()[:40]
    except Exception:
        pass
    return str(channel_id)


def scopes_for_source(source_id):
    """نطاقات Dedup التي ينشر إليها المصدر (واحد لكل قناة نشر)."""
    return [section_scope_for_channel(t) for t in sorted(get_targets_for_source(source_id))]


def check_global_blocked_words_raw(raw_text, channel_ids=None):
    """يفحص الكلمات المحظورة على النص الخام قبل أي تنظيف أو معالجة.
    يطبق القائمة العامة، ثم قوائم القنوات المستهدفة فقط حتى لا يؤثر إعداد قسم
    على قسم آخر. يرجع الكلمة المحظورة أو None، ولا يستدعي أي AI."""
    if not raw_text:
        return None
    for word in (db.get_blocked_words() if hasattr(db, "get_blocked_words") else []):
        if word and word in raw_text:
            return word
    if not channel_ids or not hasattr(db, "get_channel_blocked_words"):
        return None
    try:
        seen = set()
        for channel_id in channel_ids:
            if channel_id in seen:
                continue
            seen.add(channel_id)
            for word in db.get_channel_blocked_words(channel_id) or []:
                if word and word in raw_text:
                    return word
    except Exception:
        pass
    return None


def unsupported_media_reason(message):
    """يرجع سبب التجاهل إذا كان المنشور يحتوي ملصق أو صورة متحركة/GIF."""
    if getattr(message, "sticker", None):
        return "ملصق"
    if getattr(message, "animation", None):
        return "صورة متحركة / GIF"
    return None


def mark_middle_auto_forward_window(seconds=4):
    """يمنع middle_channel_handler من نشر النسخة التي وصلت للوسيطة تلقائياً حتى لا تتكرر."""
    global _middle_auto_ignore_until
    _middle_auto_ignore_until = max(_middle_auto_ignore_until, time.monotonic() + seconds)


def is_middle_auto_forward_window_active():
    return time.monotonic() <= _middle_auto_ignore_until


async def publish_source_message(message, source_id, origin="updates"):
    raw_text = message.text or message.caption or ""
    source_id = int(source_id)
    content_type = content_type_for_message(message)
    message_id = getattr(message, "id", None)

    # تحديد القنوات المستهدفة فقط لتطبيق قوائم الحظر الخاصة بها؛ لا توجد معالجة للنص هنا.
    target_ids = get_targets_for_source(source_id)
    raw_blocked_word = check_global_blocked_words_raw(raw_text, channel_ids=target_ids)
    if raw_blocked_word:
        logger.info(f"⛔ Blocked before processing: blocked_word='{raw_blocked_word}' source={source_id} message_id={message_id}")
        if hasattr(db, "record_source_event"):
            db.record_source_event(source_id, "rejected", f"blocked before processing: {raw_blocked_word}", message_id)
        return True

    if hasattr(db, "is_maintenance_mode") and db.is_maintenance_mode():
        logger.info(f"🛠️ [{origin}] وضع الصيانة مفعل؛ تم تجاهل النشر وتحديث آخر رسالة للمصدر {source_id}")
        if hasattr(db, "record_source_event"):
            db.record_source_event(source_id, "ignored", "maintenance mode", getattr(message, "id", None))
        return True

    if is_source_paused(source_id):
        logger.info(f"⏸️ [{origin}] مصدر موقوف تم تجاهله: {source_id}")
        if hasattr(db, "record_source_event"):
            db.record_source_event(source_id, "ignored", "source paused", getattr(message, "id", None))
        return True

    if not is_content_allowed_for_source(source_id, content_type):
        logger.info(f"⛔ [{origin}] تم تجاهل منشور من {source_id} بسبب فلتر نوع المحتوى: {content_type}")
        if hasattr(db, "record_source_event"):
            db.record_source_event(source_id, "ignored", f"content type blocked: {content_type}", getattr(message, "id", None))
        return True

    if not target_ids:
        logger.info("🟡 لا توجد قنوات مستهدفة لهذا المصدر، تم اعتبار المنشور معالجاً حتى لا يتكرر.")
        return True

    raw_text = full_clean_text(raw_text, source_id=source_id)
    logger.info(f"📨 [{origin}] رسالة من {source_id} | type={content_type} | message_id={message_id} | نص: {str(raw_text)[:80]}...")

    # كلمات الحذف الخاصة بالمصدر/القناة تُطبق قبل Dedup، بينما قالب النشر والروابط
    # الخاصة بالقناة لا تدخل في هوية الحدث.
    dedup_text_by_target = {
        target: prepare_dedup_text(raw_text, source_id=source_id, channel_id=target)
        for target in target_ids
    }

    # حجز ذري لنفس رسالة المصدر بعد المحظورات وكلمات الحذف، وقبل Dedup والنشر.
    # المساران updates وpolling يتنافسان هنا؛ الخاسر يخرج ولا ينشر.
    if message_id is not None and hasattr(db, "claim_source_event"):
        try:
            claimed_now = db.claim_source_event(source_id, message_id)
        except Exception as exc:
            logger.exception(f"فشل claim للحدث؛ تم إيقاف النشر الآمن: source={source_id} message_id={message_id}: {exc}")
            return False
        if not claimed_now:
            logger.info(f"🔒 [{origin}] الحدث محجوز مسبقاً من مسار آخر: source={source_id} message_id={message_id} — تم إيقاف المسار الخاسر")
            if hasattr(db, "record_source_event"):
                db.record_source_event(source_id, "duplicate", "source event claim lost", message_id)
            return True

    if message_id is not None and hasattr(db, "has_recent_source_event"):
        try:
            if db.has_recent_source_event(source_id, message_id):
                logger.info(f"🔁 [{origin}] نفس الحدث من المصدر {source_id} تمت معالجته سابقاً: message_id={message_id}")
                if hasattr(db, "record_source_event"):
                    db.record_source_event(source_id, "duplicate", "same source event", message_id)
                return True
        except Exception:
            pass

    # ملاحظة: فحص الكلمة المحظورة الخاص بكل قناة ما زال يتم على حدة داخل حلقة
    # الإرسال أدناه (عبر clean_text_for_source)، لأن كل قناة لها قائمتها المستقلة.

    unsupported_reason = unsupported_media_reason(message)
    if unsupported_reason:
        logger.info(f"⛔ تم تجاهل المنشور لأنه يحتوي {unsupported_reason}")
        if hasattr(db, "record_source_event"):
            db.record_source_event(source_id, "ignored", f"unsupported: {unsupported_reason}", getattr(message, "id", None))
        return True

    if raw_text:
        if message.media:
            duplicated, duplicate_score = is_smart_duplicate(raw_text, threshold=0.75)
            duplicate_reason = "similarity"
        else:
            # Dedup مشترك حسب القسم: المقارنة مع النص بعد كلمات الحذف وقبل قالب النشر.
            duplicated = False
            duplicate_reason = "none"
            duplicate_score = 0.0
            for target in sorted(target_ids):
                candidate_text = dedup_text_by_target.get(target, "")
                if not candidate_text:
                    continue
                scope_id = section_scope_for_channel(target)
                duplicated, duplicate_reason, duplicate_score = is_hybrid_news_duplicate(
                    candidate_text, source_id=source_id, message_id=message_id, threshold=0.75, scope_id=scope_id
                )
                if duplicated:
                    event_fp = make_event_fp(candidate_text)
                    logger.info(f"🔁 Duplicate detected: scope={section_label_for_channel(target)} reason={duplicate_reason} score={duplicate_score:.3f} source={source_id} message_id={message_id}")
                    if hasattr(db, "record_source_event"):
                        db.record_source_event(source_id, "duplicate", f"section:{duplicate_reason}", message_id)
                    return True
                # حجز ذري وقائي للنص الجديد في هذا القسم (يمنع سباق المصادر المختلفة).
                event_fp = make_event_fp(candidate_text)
                if not check_section_claim(scope_id, event_fp or f"fp:new:{message_id}"):
                    logger.info(f"🔁 [{origin}] الخبر محجوز مسبقاً في قسم {section_label_for_channel(target)} من مصدر آخر: source={source_id} message_id={message_id}")
                    duplicated = True
                    break
            if duplicated:
                return True
        logger.info(f"✅ New event accepted: scopes={[section_label_for_channel(t) for t in target_ids]} source={source_id} message_id={message_id}")

    # تسجيل الحدث "مستلم" بعد اجتياز فحوصات التكرار —
    # تسجيله قبل الفحص كان يجعل أول منشور نصي يُكتشف كمكرر لنفسه.
    if hasattr(db, "record_source_event"):
        db.record_source_event(source_id, "received", content_type, message_id)

    if message.media:
        try:
            mark_middle_auto_forward_window()
            fwd = await forward_to_middle(message.chat.id, message.id)
            mark_middle_auto_forward_window()
            await asyncio.sleep(0.5)
            middle_messages = fwd if isinstance(fwd, list) else [fwd]
            middle_messages = [m for m in middle_messages if m]
            logger.info(f"✅ تم تمرير منشور ميديا إلى الوسيطة | ids={[m.id for m in middle_messages]}")
        except Exception as e:
            logger.error(f"فشل التوجيه للوسيطة من المصدر {source_id}: {e}")
            if hasattr(db, "release_source_event_claim") and message_id is not None:
                db.release_source_event_claim(source_id, message_id)
            await notify_admins(f"فشل توجيه رسالة من {source_id} إلى الوسيطة: {e}")
            return False

        any_success = False
        any_logical_rejection = False
        for target in target_ids:
            try:
                ch = db.get_channel(target)
                if not ch:
                    logger.warning(f"القناة {target} غير موجودة في قاعدة البيانات")
                    continue

                if not await _verify_channel_before_publish(target):
                    logger.warning(f"⛔ القناة {target} غير قابلة للوصول، تم تخطيها")
                    continue

                cleaned = clean_text_for_source(raw_text, source_id, channel_id=target)
                if cleaned is None:
                    logger.info("⛔ النص بعد التنظيف مرفوض لكلمة محظورة")
                    any_logical_rejection = True
                    continue
                final = compose_channel_post_text(cleaned, target, ch.get("tail", ""))
                formatted_caption, parse_mode, caption_entities = format_outgoing_payload_for_channel(final, target, content_type, news_text=cleaned, tail=ch.get("tail", "")) if final else (None, None, None)
                ok = await copy_middle_messages_to_target(target, middle_messages, formatted_caption, parse_mode=parse_mode, content_type=content_type, caption_entities=caption_entities)
                if ok:
                    db.increment_post_count(target)
                    record_channel_success(target)
                    any_success = True
                await asyncio.sleep(get_publish_delay_for_channel(target))

            except Exception as e:
                logger.error(f"نشر فاشل إلى {target}: {e}")
                await record_channel_failure_and_maybe_alert(target, e)
                await notify_admins(f"فشل النشر إلى {target}: {e}")

        if any_success and raw_text:
            for target in target_ids:
                remember_published_text(
                    dedup_text_by_target.get(target) or raw_text,
                    source_id=source_id, message_id=message_id,
                    scope_id=section_scope_for_channel(target), section_label=section_label_for_channel(target),
                )
        if not any_success and not any_logical_rejection and hasattr(db, "release_source_event_claim") and message_id is not None:
            db.release_source_event_claim(source_id, message_id)
        processed = any_success or any_logical_rejection
        if hasattr(db, "record_source_event"):
            db.record_source_event(source_id, "published" if any_success else "rejected" if any_logical_rejection else "error", "media" if any_success else "media publish failed" if not any_logical_rejection else "media rejected", getattr(message, "id", None), len(target_ids))
        if any_logical_rejection and not any_success:
            logger.info("✅ تم رفض المنشور منطقياً في كل القنوات، تم اعتباره معالجاً لتحديث last_seen.")
        return processed

    else:
        any_success = False
        any_logical_rejection = False
        for target in target_ids:
            try:
                ch = db.get_channel(target)
                if not ch:
                    logger.warning(f"القناة {target} غير موجودة في قاعدة البيانات")
                    continue

                if not await _verify_channel_before_publish(target):
                    logger.warning(f"⛔ القناة {target} غير قابلة للوصول، تم تخطيها")
                    continue

                cleaned = clean_text_for_source(raw_text, source_id, channel_id=target)
                if cleaned is None:
                    logger.info("⛔ النص بعد التنظيف مرفوض لكلمة محظورة")
                    any_logical_rejection = True
                    continue
                if raw_text and should_ignore_short_post_for_channel(cleaned, target):
                    logger.info(f"⛔ منشور قصير مرفوض للقناة {target}")
                    any_logical_rejection = True
                    continue

                final = compose_channel_post_text(cleaned, target, ch.get("tail", ""))

                if final:
                    try:
                        await hydrate_publish_channel(target)
                    except Exception as e:
                        logger.warning(f"⚠️ فشل تهيئة قناة النشر {target} قبل النص: {e}")
                    formatted, parse_mode, entities = format_outgoing_payload_for_channel(final, target, "text", news_text=cleaned, tail=ch.get("tail", ""))
                    sent_msg = await safe_send_channel_message(target, formatted, parse_mode=parse_mode, entities=entities)
                    if hasattr(db, "record_published_message") and getattr(sent_msg, "id", None):
                        db.record_published_message(target, sent_msg.id, "text")
                else:
                    logger.info("🟡 منشور نصي فارغ بعد التنظيف؛ لن يتم إرساله.")
                    continue

                db.increment_post_count(target)
                record_channel_success(target)
                any_success = True
                logger.info(f"✅ نُشر نص إلى {target}")
                await asyncio.sleep(get_publish_delay_for_channel(target))

            except Exception as e:
                logger.error(f"إرسال فاشل إلى {target}: {e}")
                await record_channel_failure_and_maybe_alert(target, e)
                await notify_admins(f"فشل الإرسال إلى {target}: {e}")

        if any_success and raw_text:
            for target in target_ids:
                remember_published_text(
                    dedup_text_by_target.get(target) or raw_text,
                    source_id=source_id, message_id=message_id,
                    scope_id=section_scope_for_channel(target), section_label=section_label_for_channel(target),
                )
        if not any_success and not any_logical_rejection and hasattr(db, "release_source_event_claim") and message_id is not None:
            db.release_source_event_claim(source_id, message_id)
        processed = any_success or any_logical_rejection
        if hasattr(db, "record_source_event"):
            db.record_source_event(source_id, "published" if any_success else "rejected" if any_logical_rejection else "error", "text" if any_success else "text publish failed" if not any_logical_rejection else "text rejected", getattr(message, "id", None), len(target_ids))
        if any_logical_rejection and not any_success:
            logger.info("✅ تم رفض النص منطقياً في كل القنوات، تم اعتباره معالجاً لتحديث last_seen.")
        return processed


async def publish_source_album(messages, source_id, origin="polling"):
    """ينشر مجموعة ميديا من المصدر إلى الوسيطة ثم إلى قنوات النشر بنفس ترتيب الرسائل."""
    if not messages:
        return True

    messages = sorted(messages, key=lambda m: m.id)
    first = messages[0]
    raw_text = first.caption or first.text or ""
    source_id = int(source_id)
    content_type = "album"

    if hasattr(db, "is_maintenance_mode") and db.is_maintenance_mode():
        logger.info(f"🛠️ [{origin}] وضع الصيانة مفعل؛ تم تجاهل الألبوم وتحديث آخر رسالة للمصدر {source_id}")
        if hasattr(db, "record_source_event"):
            db.record_source_event(source_id, "ignored", "maintenance mode", getattr(first, "id", None))
        return True

    if is_source_paused(source_id):
        logger.info(f"⏸️ [{origin}] مصدر موقوف تم تجاهله: {source_id}")
        if hasattr(db, "record_source_event"):
            db.record_source_event(source_id, "ignored", "source paused", ids[-1] if 'ids' in locals() and ids else None)
        return True

    if not is_content_allowed_for_source(source_id, content_type):
        logger.info(f"⛔ [{origin}] تم تجاهل ألبوم من {source_id} بسبب فلتر نوع المحتوى")
        if hasattr(db, "record_source_event"):
            db.record_source_event(source_id, "ignored", "content type blocked: album", ids[-1] if 'ids' in locals() and ids else None)
        return True

    # Early reject: فحص الكلمات المحظورة على النص الخام قبل أي معالجة (مثل النصوص).
    raw_album_blocked = check_global_blocked_words_raw(raw_text)
    if raw_album_blocked:
        logger.info(f"⛔ Blocked before processing: blocked_word='{raw_album_blocked}' source={source_id} album")
        if hasattr(db, "record_source_event"):
            db.record_source_event(source_id, "rejected", f"blocked before processing: {raw_album_blocked}", getattr(first, "id", None))
        return True

    raw_text = full_clean_text(raw_text, source_id=source_id)
    ids = [m.id for m in messages]

    album_event_id = ids[-1] if ids else None

    # حجز ذري دائم للألبوم (source_id:last_message_id) قبل أي فحص أو نشر —
    # يغلق تكرار الألبوم بين مسار updates وpolling ومنع سباق TOCTOU.
    if album_event_id is not None and hasattr(db, "claim_source_event"):
        try:
            album_claimed_now = db.claim_source_event(source_id, album_event_id)
        except Exception as exc:
            logger.exception(f"فشل claim للألبوم؛ تم إيقاف النشر الآمن: source={source_id} message_id={album_event_id}: {exc}")
            return False
        if not album_claimed_now:
            logger.info(f"🔒 [{origin}] الألبوم محجوز مسبقاً من مسار آخر: source={source_id} message_id={album_event_id}")
            if hasattr(db, "record_source_event"):
                db.record_source_event(source_id, "duplicate", "album event already claimed", album_event_id)
            return True

    if album_event_id is not None and hasattr(db, "has_recent_source_event"):
        try:
            if db.has_recent_source_event(source_id, album_event_id):
                logger.info(f"🔁 [{origin}] نفس الألبوم من المصدر {source_id} تمت معالجته سابقاً: message_id={album_event_id}")
                if hasattr(db, "record_source_event"):
                    db.record_source_event(source_id, "duplicate", "same source album event", album_event_id)
                return True
        except Exception:
            pass

    logger.info(f"📨 [{origin}] ألبوم من {source_id} | message_ids={ids} | نص: {str(raw_text)[:80]}...")

    target_ids = get_targets_for_source(source_id)
    if not target_ids:
        logger.info("🟡 لا توجد قنوات مستهدفة لهذا الألبوم، تم اعتباره معالجاً حتى لا يتكرر.")
        return True

    # كلمات الحذف الخاصة بالمصدر/القناة تُطبق قبل Dedup، بينما قالب النشر لا يدخل في البصمة.
    dedup_text_by_target = {
        target: prepare_dedup_text(raw_text, source_id=source_id, channel_id=target)
        for target in target_ids
    }

    for item in messages:
        unsupported_reason = unsupported_media_reason(item)
        if unsupported_reason:
            logger.info(f"⛔ تم تجاهل الألبوم لأنه يحتوي {unsupported_reason}")
            return True

    if raw_text:
        # Dedup مشترك حسب القسم: المقارنة مع نطاق كل قناة نشر مستهدفة (48 ساعة).
        target_ids_for_dedup = get_targets_for_source(source_id)
        duplicated = False
        for target in sorted(target_ids_for_dedup):
            candidate_text = dedup_text_by_target.get(target, "")
            if not candidate_text:
                continue
            scope_id = section_scope_for_channel(target)
            duplicated, dup_reason, dup_score = is_hybrid_news_duplicate(
                candidate_text, source_id=source_id, message_id=album_event_id, threshold=0.75, scope_id=scope_id
            )
            if duplicated:
                event_fp = make_event_fp(candidate_text)
                claim_won = check_section_claim(scope_id, event_fp or f"fp:{dup_reason}")
                logger.info(f"🔁 Duplicate detected: scope={section_label_for_channel(target)} reason={dup_reason} source={source_id} album claim_won={claim_won}")
                if hasattr(db, "record_source_event"):
                    db.record_source_event(source_id, "duplicate", f"section:{dup_reason}", album_event_id)
                return True
            event_fp = make_event_fp(candidate_text)
            if not check_section_claim(scope_id, event_fp or f"fp:new:{album_event_id}"):
                logger.info(f"🔁 [{origin}] ألبوم محجوز مسبقاً في قسم {section_label_for_channel(target)} من مصدر آخر: source={source_id}")
                duplicated = True
                break
        if duplicated:
            return True
        logger.info(f"✅ New album accepted: scopes={[section_label_for_channel(t) for t in target_ids_for_dedup]} source={source_id}")

    # تسجيل الألبوم "مستلم" بعد اجتياز فحوصات التكرار.
    if hasattr(db, "record_source_event"):
        db.record_source_event(source_id, "received", "album", album_event_id)

    try:
        mark_middle_auto_forward_window()
        fwd = await forward_to_middle(source_id, ids)
        mark_middle_auto_forward_window()
        await asyncio.sleep(0.8)
        middle_messages = fwd if isinstance(fwd, list) else [fwd]
        middle_messages = sorted([m for m in middle_messages if m], key=lambda m: m.id)
        logger.info(f"✅ تم تمرير الألبوم إلى الوسيطة | middle_ids={[m.id for m in middle_messages]}")
    except Exception as e:
        logger.error(f"فشل توجيه الألبوم للوسيطة من المصدر {source_id}: {e}")
        if hasattr(db, "release_source_event_claim") and album_event_id is not None:
            db.release_source_event_claim(source_id, album_event_id)
        await notify_admins(f"فشل توجيه ألبوم من {source_id} إلى الوسيطة: {e}")
        return False

    any_success = False
    for target in target_ids:
        try:
            ch = db.get_channel(target)
            if not ch:
                logger.warning(f"القناة {target} غير موجودة في قاعدة البيانات")
                continue

            if not await _verify_channel_before_publish(target):
                logger.warning(f"⛔ القناة {target} غير قابلة للوصول، تم تخطي الألبوم")
                continue

            cleaned = clean_text_for_source(raw_text, source_id, channel_id=target)
            if cleaned is None:
                logger.info("⛔ النص بعد التنظيف مرفوض لكلمة محظورة")
                continue
            final = compose_channel_post_text(cleaned, target, ch.get("tail", ""))
            formatted_caption, parse_mode, caption_entities = format_outgoing_payload_for_channel(final, target, "album", news_text=cleaned, tail=ch.get("tail", "")) if final else (None, None, None)
            ok = await copy_middle_messages_to_target(target, middle_messages, formatted_caption, parse_mode=parse_mode, content_type=content_type, caption_entities=caption_entities)
            if ok:
                db.increment_post_count(target)
                record_channel_success(target)
                any_success = True
            await asyncio.sleep(get_publish_delay_for_channel(target))

        except Exception as e:
            logger.error(f"نشر الألبوم فاشل إلى {target}: {e}")
            await record_channel_failure_and_maybe_alert(target, e)
            await notify_admins(f"فشل نشر ألبوم إلى {target}: {e}")

    if any_success and raw_text:
        for target in target_ids:
            remember_published_text(
                dedup_text_by_target.get(target) or raw_text, source_id=source_id, message_id=album_event_id,
                scope_id=section_scope_for_channel(target), section_label=section_label_for_channel(target),
            )
    if not any_success and hasattr(db, "release_source_event_claim") and album_event_id is not None:
        db.release_source_event_claim(source_id, album_event_id)
    if hasattr(db, "record_source_event"):
        db.record_source_event(source_id, "published" if any_success else "error", "album" if any_success else "album publish failed", album_event_id, len(target_ids))
    if not any_success:
        logger.warning(f"⚠️ تم تمرير الألبوم للوسيطة لكن فشل نشره للقنوات. سيبقى قابلاً لإعادة المحاولة: {getattr(first, 'media_group_id', '')}")
    return True


async def user_message_handler(client, message):
    pass  # log muted: user update received

    if not message.chat or message.chat.type not in ("channel", "supergroup"):
        return

    await publish_source_message(message, int(message.chat.id), origin="updates")


async def poll_public_sources_loop():
    """يفحص المصادر العامة والخاصة دورياً، لأن Updates لا تصل أحياناً على Hugging Face."""
    await asyncio.sleep(8)
    logger.info("🔁 بدأ نظام الفحص الدوري للمصادر العامة والخاصة Polling")

    while True:
        try:
            mark_runtime_activity("poll")
            poll_sources = get_polling_sources()
            if not poll_sources:
                await asyncio.sleep(25)
                continue

            for source in poll_sources:
                try:
                    source_id = int(source)
                except Exception:
                    logger.warning(f"مصدر غير رقمي تم تجاهله: {source}")
                    continue

                kind = source_kind_label(source_id)

                if is_source_paused(source_id):
                    continue

                try:
                    last_seen = db.get_last_source_message(source_id)
                    messages = []

                    async for msg in user_client.get_chat_history(source_id, limit=8):
                        if not msg or not getattr(msg, "id", None):
                            continue
                        messages.append(msg)
                    mark_runtime_activity("poll")

                    if not messages:
                        continue

                    newest_id = max(m.id for m in messages)

                    if last_seen is None:
                        db.set_last_source_message(source_id, newest_id)
                        logger.info(f"🔁 [{kind}] المصدر {source_id}: أول تشغيل، تم حفظ آخر رسالة {newest_id} بدون نشر القديم.")
                        continue

                    new_messages = [m for m in messages if m.id > int(last_seen)]
                    new_messages.sort(key=lambda m: m.id)

                    if not new_messages:
                        continue

                    logger.info(f"🔁 [{kind}] المصدر {source_id}: تم العثور على {len(new_messages)} منشور جديد.")

                    processed_ids = set()
                    i = 0
                    while i < len(new_messages):
                        msg = new_messages[i]
                        if msg.id in processed_ids:
                            i += 1
                            continue

                        media_group_id = getattr(msg, "media_group_id", None)
                        origin = f"polling][{kind}"

                        if media_group_id:
                            group = [m for m in new_messages if getattr(m, "media_group_id", None) == media_group_id]
                            group.sort(key=lambda m: m.id)
                            ok = await publish_source_album(group, source_id, origin=origin)
                            if ok:
                                for gm in group:
                                    processed_ids.add(gm.id)
                                db.set_last_source_message(source_id, max(gm.id for gm in group))
                            else:
                                logger.warning(f"⚠️ لم يتم تحديث last_seen للألبوم {media_group_id} حتى يعاد المحاولة لاحقاً")
                            await asyncio.sleep(1)
                        else:
                            ok = await publish_source_message(msg, source_id, origin=origin)
                            if ok:
                                processed_ids.add(msg.id)
                                db.set_last_source_message(source_id, msg.id)
                            else:
                                logger.warning(f"⚠️ لم يتم تحديث last_seen للرسالة {msg.id} حتى تعاد المحاولة لاحقاً")
                            await asyncio.sleep(1)
                        i += 1

                except Exception as e:
                    logger.exception(f"خطأ أثناء فحص المصدر [{kind}] {source}: {e}")
                    if is_transient_network_error(e):
                        await reconnect_user_client_if_needed(e)
                        await asyncio.sleep(10)
                    else:
                        await notify_admins(f"فشل فحص المصدر [{kind}] {source}: {e}")

            await asyncio.sleep(25)

        except Exception as e:
            logger.exception(f"خطأ عام في حلقة Polling: {e}")
            await asyncio.sleep(30)


async def publish_middle_messages_to_all(middle_messages):
    """ينشر منشوراً أو ألبوماً منشوراً يدوياً في الوسيطة إلى كل قنوات النشر."""
    if not isinstance(middle_messages, (list, tuple)):
        middle_messages = [middle_messages]
    middle_messages = sorted([m for m in middle_messages if m], key=lambda m: m.id)
    if not middle_messages:
        return

    first = middle_messages[0]
    raw_text = full_clean_text(first.text or first.caption or "")

    if hasattr(db, "is_maintenance_mode") and db.is_maintenance_mode():
        logger.info("🛠️ وضع الصيانة مفعل؛ تم تجاهل النشر اليدوي من الوسيطة.")
        return

    for item in middle_messages:
        unsupported_reason = unsupported_media_reason(item)
        if unsupported_reason:
            logger.info(f"⛔ تم تجاهل رسالة الوسيطة لأنها تحتوي {unsupported_reason}")
            return

    # فحص الكلمة المحظورة صار لكل قناة على حدة داخل الحلقة أدناه (clean_text(channel_id=target)).

    all_channels = db.get_all_channels()
    is_album = len(middle_messages) > 1

    for ch in all_channels:
        if ch.get("paused"):
            continue

        target = int(ch["id"])

        if not await _verify_channel_before_publish(target):
            logger.warning(f"⛔ القناة {target} غير قابلة للوصول، تم تخطي النشر اليدوي")
            continue

        try:
            cleaned = clean_text(raw_text, channel_id=target) if raw_text else ""
            if cleaned is None:
                continue
            if raw_text and not is_album and not first.media and should_ignore_short_post_for_channel(cleaned, target):
                logger.info(f"⛔ منشور وسيطة قصير مرفوض للقناة {target}")
                continue

            final = compose_channel_post_text(cleaned, target, ch.get("tail", ""))

            if is_album:
                formatted_caption, parse_mode, caption_entities = format_outgoing_payload_for_channel(final, target, "album", news_text=cleaned, tail=ch.get("tail", "")) if final else (None, None, None)
                ok = await copy_middle_messages_to_target(target, middle_messages, formatted_caption, parse_mode=parse_mode, content_type="album", caption_entities=caption_entities)
                if not ok:
                    continue
            elif first.media:
                try:
                    await hydrate_publish_channel(target)
                except Exception as e:
                    logger.warning(f"⚠️ فشل تهيئة قناة النشر {target} قبل نسخة الوسيطة: {e}")
                middle_ctype = published_content_type_for_message(first, False)
                formatted_caption, parse_mode, caption_entities = format_outgoing_payload_for_channel(final, target, middle_ctype, news_text=cleaned, tail=ch.get("tail", "")) if final else (None, None, None)
                copy_kwargs = dict(
                    chat_id=target,
                    from_chat_id=config.MIDDLE_CHANNEL,
                    message_id=first.id,
                    caption=formatted_caption if formatted_caption else None,
                    parse_mode=None if caption_entities else parse_mode
                )
                if caption_entities:
                    copy_kwargs["caption_entities"] = caption_entities
                try:
                    sent = await _retry_on_flood(lambda: bot_client.copy_message(**copy_kwargs), label=f"middle→{target}")
                except TypeError:
                    copy_kwargs.pop("caption_entities", None)
                    copy_kwargs["parse_mode"] = parse_mode
                    sent = await bot_client.copy_message(**copy_kwargs)
                sent_msg = sent
                if hasattr(db, "record_published_message") and getattr(sent_msg, "id", None):
                    db.record_published_message(target, sent_msg.id, published_content_type_for_message(first, False))
            else:
                try:
                    await hydrate_publish_channel(target)
                except Exception as e:
                    logger.warning(f"⚠️ فشل تهيئة قناة النشر {target} قبل نص الوسيطة: {e}")
                formatted, parse_mode, entities = format_outgoing_payload_for_channel(final if final else ".", target, "text", news_text=cleaned, tail=ch.get("tail", ""))
                sent_msg = await safe_send_channel_message(target, formatted, parse_mode=parse_mode, entities=entities)
                if hasattr(db, "record_published_message") and getattr(sent_msg, "id", None):
                    db.record_published_message(target, sent_msg.id, "text")

            db.increment_post_count(target)
            record_channel_success(target)
            mark_runtime_activity("publish")
            logger.info(f"✅ نُشر من الوسيطة إلى {target}")
            await asyncio.sleep(get_publish_delay_for_channel(target))

        except Exception as e:
            logger.error(f"نشر فاشل من الوسيطة إلى {target}: {e}")
            await record_channel_failure_and_maybe_alert(target, e)
            await notify_admins(f"فشل النشر من الوسيطة إلى {target}: {e}")


async def flush_middle_album(media_group_id):
    """يجمع ألبوم الوسيطة اليدوي ثم ينشره كألبوم واحد."""
    await asyncio.sleep(2.0)
    messages = _middle_album_buffers.pop(media_group_id, [])
    _middle_album_tasks.pop(media_group_id, None)
    if not messages:
        return
    logger.info(f"📥 ألبوم في الوسيطة، جارٍ النشر كألبوم واحد | count={len(messages)}")
    await publish_middle_messages_to_all(messages)


async def middle_channel_handler(client, message):
    if int(message.chat.id) != int(config.MIDDLE_CHANNEL):
        return

    if is_middle_auto_forward_window_active():
        logger.info(f"🟡 تم تجاهل رسالة وسيطة تلقائية لمنع التكرار | message_id={message.id}")
        return

    media_group_id = getattr(message, "media_group_id", None)
    if media_group_id:
        key = str(media_group_id)
        _middle_album_buffers.setdefault(key, []).append(message)
        if key not in _middle_album_tasks:
            _middle_album_tasks[key] = asyncio.create_task(flush_middle_album(key))
        return

    logger.info("📥 رسالة في الوسيطة، جارٍ النشر...")
    await publish_middle_messages_to_all([message])

# ============================================================
# Multi-Bot Expansion: Secrets Management UI
# ============================================================

async def secrets_menu(client, callback):
    text = "🔐 **الأسرار والإعدادات**\n\n📱 الجلسات: حسابات Telegram المستخدمة للقراءة.\n🤖 بوتات النشر: البوتات التي تنشر في القنوات.\n🧠 مفاتيح AI: مزودو الذكاء الاصطناعي ومفاتيحهم.\n🌐 مواقع الويب: مصادر الجلب عبر الروابط.\n🗑 سلة المحذوفات: استعادة أو حذف العناصر نهائياً."
    buttons = [
        [InlineKeyboardButton("📱 الجلسات", callback_data="sessions_list"), InlineKeyboardButton("🤖 بوتات النشر", callback_data="bots_list")],
        [InlineKeyboardButton("🧠 مفاتيح AI", callback_data="ai_list"), InlineKeyboardButton("🌐 مواقع الويب", callback_data="web_list")],
        [InlineKeyboardButton("🗑 سلة المحذوفات", callback_data="trash_menu")],
        nav_row("main_menu"),
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def _show_secrets_list(client, callback, items, title, add_cb, item_cb_prefix, toggle_prefix, del_prefix, test_prefix, kind=""):
    if not items:
        text = f"{title}\n\nلا توجد عناصر."
        buttons = [[InlineKeyboardButton("➕ إضافة", callback_data=add_cb)], nav_row("secrets_menu")]
    else:
        text = f"{title} ({len(items)}):\n\n✅ العناصر المفعلة تعمل في النشر أو الجلب.\n❌ العناصر المعطلة محفوظة لكنها لا تعمل حالياً.\n"
        btns = []
        for item in items:
            name = item.get("name", item.get("id", ""))
            enabled = "✅" if item.get("enabled", True) else "❌"
            btns.append(InlineKeyboardButton(f"{enabled} {name}", callback_data=f"{item_cb_prefix}{item.get('id')}"))
        rows = grid_buttons(btns, 2)
        rows.append([InlineKeyboardButton("➕ إضافة", callback_data=add_cb)])
        rows.append(nav_row("secrets_menu"))
        await safe_edit(callback, text, InlineKeyboardMarkup(rows))
        return
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


# --- Sessions ---

async def sessions_list_menu(client, callback):
    items = db.get_all_sessions()
    text = "📱 **الجلسات**\n\n✅ الجلسة المفعلة متاحة لقراءة المصادر.\n❌ الجلسة المعطلة لا تُستخدم حتى تعيد تشغيلها.\n\n"
    if not items:
        text += "لا توجد جلسات."
        buttons = [[InlineKeyboardButton("➕ إضافة جلسة", callback_data="session_add")], nav_row("secrets_menu")]
        await safe_edit(callback, text, InlineKeyboardMarkup(buttons))
        return
    btns = []
    for s in items:
        status = "✅" if s.get("enabled", True) else "❌"
        btns.append(InlineKeyboardButton(f"{status} {s.get('name', s['id'])}", callback_data=f"session_show_{s['id']}"))
    rows = grid_buttons(btns, 2)
    rows.append([InlineKeyboardButton("➕ إضافة جلسة", callback_data="session_add")])
    rows.append(nav_row("secrets_menu"))
    text += f"العدد: {len(items)}"
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def add_session_prompt(client, callback):
    uid = callback.from_user.id
    user_states.pop(uid, None)
    user_states[uid] = {"state": "waiting_session_add"}
    await safe_edit(callback, "✏️ أرسل بيانات الجلسة بهذا التنسيق:\n\n`API_ID | API_HASH | SESSION_STRING`\n\nفي سطر واحد.", InlineKeyboardMarkup([nav_row("sessions_list")]))


async def show_session_settings(client, callback):
    sid = callback.data.split("_", 2)[2]
    s = db.get_session(sid)
    if not s:
        await callback.answer("الجلسة غير موجودة.")
        return
    deps = db.get_dependencies_for("session", sid)
    deps_text = "\n".join(f"• {entity_name(d)}" for d in deps[:10]) if deps else "لا توجد"
    stats = db.get_session_stats(sid)
    text = (
        f"📱 **{s.get('name', sid)}**\n"
        f"🆔 `{sid}`\n"
        f"🔢 API ID: `{'***' if s.get('api_id') else '?'}`\n"
        f"🔑 الحالة: {'✅ مفعل' if s.get('enabled', True) else '❌ معطل'}\n"
        f"📊 الاستخدام: {stats.get('usage_count', 0)}\n"
        f"❌ الأخطاء: {stats.get('error_count', 0)}\n"
        f"🕐 آخر استخدام: {_format_ts(stats.get('last_used'))}\n"
        f"📡 الحالة: {s.get('status', 'idle')}\n\n⏯️ تشغيل/إيقاف: تفعيل أو تعطيل استخدام الجلسة.\n🧪 اختبار: التحقق من اتصال الجلسة دون تغيير إعداداتها.\n🗑 حذف: نقل الجلسة إلى سلة المحذوفات.\n\n"
        f"**القنوات المستخدمة:**\n{deps_text}"
    )
    buttons = [
        [InlineKeyboardButton("⏯️ تشغيل/إيقاف", callback_data=f"session_toggle_{sid}")],
        [InlineKeyboardButton("🧪 اختبار", callback_data=f"session_test_{sid}")],
        [InlineKeyboardButton("🗑 حذف", callback_data=f"session_delete_{sid}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="sessions_list"), InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def toggle_session(client, callback):
    sid = callback.data.split("_", 2)[2]
    s = db.get_session(sid)
    if not s:
        await callback.answer("غير موجودة.")
        return
    db.set_session_enabled(sid, not s.get("enabled", True))
    await callback.answer("تم التحديث.")
    callback.data = f"session_show_{sid}"
    await show_session_settings(client, callback)


async def delete_session_with_deps(client, callback):
    sid = callback.data.split("_", 2)[2]
    s = db.get_session(sid)
    if not s:
        await callback.answer("غير موجودة.")
        return
    deps = db.get_dependencies_for("session", sid)
    if deps:
        dep_text = "\n".join(f"• {entity_name(d)}" for d in deps[:10])
        text = (
            f"⚠️ **لا يمكن حذف {s.get('name', sid)}**\n\n"
            f"هذه الجلسة مستخدمة من قبل:\n{dep_text}\n\n"
            f"قم بإزالتها من هذه القنوات أولاً."
        )
        buttons = [nav_row(f"session_show_{sid}")]
        await safe_edit(callback, text, InlineKeyboardMarkup(buttons))
        return
    # Move to trash
    db.delete_session(sid)
    await callback.answer("✅ تم نقل الجلسة إلى سلة المحذوفات.")
    await sessions_list_menu(client, callback)


async def test_session(client, callback):
    sid = callback.data.split("_", 2)[2]
    s = db.get_session(sid)
    if not s:
        await callback.answer("غير موجودة.")
        return
    await callback.answer(f"جاري اختبار {s.get('name', sid)}...", show_alert=False)
    try:
        from pyrogram import Client as PClient
        test_client = PClient(
            f"test_session_{sid}",
            api_id=s.get("api_id", 0),
            api_hash=s.get("api_hash", ""),
            session_string=s.get("session_string", ""),
            in_memory=True
        )
        await test_client.start()
        me = await test_client.get_me()
        await test_client.stop()
        db.record_session_usage(sid)
        await callback.answer(f"✅ {s.get('name', sid)}: اتصال ناجح كـ {me.first_name or me.id}", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ فشل: {str(e)[:100]}", show_alert=True)


# --- AI Keys ---

async def ai_list_menu(client, callback):
    items = db.get_all_ai_keys()
    text = "🧠 **مفاتيح AI**\n\n✅ المفتاح المفعّل متاح لطلبات الذكاء الاصطناعي.\n❌ المفتاح المعطّل محفوظ لكنه لا يُستخدم.\n\n"
    if not items:
        text += "لا توجد مفاتيح."
        buttons = [[InlineKeyboardButton("➕ إضافة مفتاح", callback_data="ai_add")], nav_row("secrets_menu")]
        await safe_edit(callback, text, InlineKeyboardMarkup(buttons))
        return
    btns = []
    for k in items:
        status = "✅" if k.get("enabled", True) else "❌"
        btns.append(InlineKeyboardButton(f"{status} {k.get('name', k['id'])}", callback_data=f"ai_show_{k['id']}"))
    rows = grid_buttons(btns, 2)
    rows.append([InlineKeyboardButton("➕ إضافة مفتاح", callback_data="ai_add")])
    rows.append(nav_row("secrets_menu"))
    text += f"العدد: {len(items)}"
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def add_ai_key_prompt(client, callback):
    uid = callback.from_user.id
    user_states.pop(uid, None)
    user_states[uid] = {"state": "waiting_ai_key_add"}
    await safe_edit(callback, "✏️ أرسل بيانات مفتاح AI بهذا التنسيق:\n\n`المزود | المفتاح`\n\nالمزود مثال: `gemini` أو `openai`\nمثال: `gemini | AIzaSy...`", InlineKeyboardMarkup([nav_row("ai_list")]))


async def show_ai_key_settings(client, callback):
    kid = callback.data.split("_", 2)[2]
    k = db.get_ai_key(kid)
    if not k:
        await callback.answer("غير موجود.")
        return
    deps = db.get_dependencies_for("ai_key", kid)
    deps_text = "\n".join(f"• {entity_name(d)}" for d in deps[:10]) if deps else "لا توجد"
    stats = db.get_ai_key_stats(kid)
    text = (
        f"🧠 **{k.get('name', kid)}**\n"
        f"🆔 `{kid}`\n"
        f"🏢 المزود: {k.get('provider', '?')}\n"
        f"🔑 الحالة: {'✅ مفعل' if k.get('enabled', True) else '❌ معطل'}\n"
        f"📊 الاستخدام: {stats.get('usage_count', 0)}\n"
        f"❌ الأخطاء: {stats.get('error_count', 0)}\n"
        f"🕐 آخر استخدام: {_format_ts(stats.get('last_used'))}\n\n"
        f"⏯️ تشغيل/إيقاف: التحكم في استخدام مفتاح {k.get('name', kid)}.\n🧪 اختبار: التحقق من اتصال المزود.\n🗑 حذف: نقل المفتاح إلى سلة المحذوفات.\n\n"
        f"**القنوات المستخدمة:**\n{deps_text}"
    )
    buttons = [
        [InlineKeyboardButton("⏯️ تشغيل/إيقاف", callback_data=f"ai_toggle_{kid}")],
        [InlineKeyboardButton("🧪 اختبار", callback_data=f"ai_test_{kid}")],
        [InlineKeyboardButton("🗑 حذف", callback_data=f"ai_delete_{kid}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="ai_list"), InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def toggle_ai_key(client, callback):
    kid = callback.data.split("_", 2)[2]
    k = db.get_ai_key(kid)
    if not k:
        await callback.answer("غير موجود.")
        return
    db.set_ai_key_enabled(kid, not k.get("enabled", True))
    await callback.answer("تم التحديث.")
    callback.data = f"ai_show_{kid}"
    await show_ai_key_settings(client, callback)


async def delete_ai_key_with_deps(client, callback):
    kid = callback.data.split("_", 2)[2]
    k = db.get_ai_key(kid)
    if not k:
        await callback.answer("غير موجود.")
        return
    deps = db.get_dependencies_for("ai_key", kid)
    if deps:
        dep_text = "\n".join(f"• {entity_name(d)}" for d in deps[:10])
        text = f"⚠️ **لا يمكن حذف {k.get('name', kid)}**\n\nمستخدم من قبل:\n{dep_text}\n\nقم بإزالتها من هذه القنوات أولاً."
        buttons = [nav_row(f"ai_show_{kid}")]
        await safe_edit(callback, text, InlineKeyboardMarkup(buttons))
        return
    db.delete_ai_key(kid)
    await callback.answer("✅ تم النقل إلى سلة المحذوفات.")
    await ai_list_menu(client, callback)


async def test_ai_key(client, callback):
    kid = callback.data.split("_", 2)[2]
    k = db.get_ai_key(kid)
    if not k:
        await callback.answer("غير موجود.")
        return
    provider = k.get("provider", "").lower()
    api_key = k.get("api_key", "")
    if not api_key:
        await callback.answer("❌ لا يوجد مفتاح.", show_alert=True)
        return
    await callback.answer(f"جاري اختبار {k.get('name', kid)}...", show_alert=False)
    try:
        if provider == "gemini":
            import httpx
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={api_key}"
            async with httpx.AsyncClient(timeout=10) as hc:
                resp = await hc.post(url, json={"contents": [{"parts": [{"text": "hi"}]}]})
                if resp.status_code == 200:
                    db.record_ai_key_usage(kid)
                    await callback.answer("✅ اتصال ناجح!", show_alert=True)
                else:
                    await callback.answer(f"❌ فشل: {resp.status_code}", show_alert=True)
        else:
            await callback.answer(f"✅ مزود {provider} مسجل.", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ فشل: {str(e)[:100]}", show_alert=True)


# --- Publishing Bots ---

async def bots_list_menu(client, callback):
    items = db.get_all_publishing_bots()
    text = "🤖 **بوتات النشر**\n\n✅ البوت المفعّل متاح للنشر في القنوات المرتبطة.\n❌ البوت المعطّل لا ينشر حتى تعيد تشغيله.\n\n"
    if not items:
        text += "لا توجد بوتات."
        buttons = [[InlineKeyboardButton("➕ إضافة بوت", callback_data="bot_add")], nav_row("secrets_menu")]
        await safe_edit(callback, text, InlineKeyboardMarkup(buttons))
        return
    btns = []
    for b in items:
        status = "✅" if b.get("enabled", True) else "❌"
        btns.append(InlineKeyboardButton(f"{status} {b.get('name', b['id'])}", callback_data=f"bot_show_{b['id']}"))
    rows = grid_buttons(btns, 2)
    rows.append([InlineKeyboardButton("➕ إضافة بوت", callback_data="bot_add")])
    rows.append(nav_row("secrets_menu"))
    text += f"العدد: {len(items)}"
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def add_bot_prompt(client, callback):
    uid = callback.from_user.id
    user_states.pop(uid, None)
    user_states[uid] = {"state": "waiting_bot_add"}
    await safe_edit(callback, "✏️ أرسل توكن البوت:\n\nمثال:\n`123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`", InlineKeyboardMarkup([nav_row("bots_list")]))


async def show_bot_settings(client, callback):
    bid = callback.data.split("_", 2)[2]
    b = db.get_publishing_bot(bid)
    if not b:
        await callback.answer("غير موجود.")
        return
    deps_raw = db.get_dependencies_for("publishing_bot", bid) if hasattr(db, "get_dependencies_for") else []
    # استخدام BotChannelMapper للحصول على القنوات
    if hasattr(db, "mapper") and hasattr(db.mapper, "get_channels_for_bot"):
        mapped_ids = db.mapper.get_channels_for_bot(bid)
        deps = [d for d in deps_raw if str(d.get("id", "")) in mapped_ids] if deps_raw else []
        if not deps_raw:
            deps = [db.get_channel(cid) for cid in mapped_ids if db.get_channel(cid)]
    else:
        deps = deps_raw
    deps_verified = verifier.get_cached_verifications_for_bot(bid)
    deps_lines = []
    for d in deps:
        ch_id = d.get("id", "")
        ch_name = entity_name(d)
        v = deps_verified.get(str(ch_id), {})
        vstatus = v.get("verified", False)
        can_post = v.get("can_post", False)
        last_check = v.get("last_check", 0)
        if vstatus:
            age = f" (منذ {int((time.time() - last_check) / 60)}د)" if last_check else ""
            perm = "نشر:✅" if can_post else "نشر:❌"
            deps_lines.append(f"✅ {ch_name} | {perm}{age}")
        else:
            deps_lines.append(f"❌ {ch_name} | غير موثوق")
    deps_text = "\n".join(deps_lines) if deps_lines else "لا توجد"
    stats = b.get("stats", {}) or {}
    text = (
        f"🤖 **{b.get('name', bid)}**\n"
        f"🆔 `{bid}`\n"
        f"👤 @{b.get('username', '?')}\n"
        f"🔑 الحالة: {'✅ مفعل' if b.get('enabled', True) else '❌ معطل'}\n"
        f"📊 إجمالي النشرات: {b.get('publish_count', 0)}\n"
        f"   📝 نصوص: {stats.get('text', 0)}\n"
        f"   🖼 صور: {stats.get('photo', 0)}\n"
        f"   🎥 فيديو: {stats.get('video', 0)}\n"
        f"   🗂 البومات: {stats.get('album', 0)}\n"
        f"❌ الأخطاء: {b.get('error_count', 0)}\n"
        f"🕐 آخر نشر: {_format_ts(b.get('last_publish'))}\n\n"
        f"⏯️ تشغيل/إيقاف: التحكم في استخدام البوت للنشر.\n✏️ إعادة تسمية: تغيير الاسم الظاهر للبوت فقط.\n🔍 فحص القنوات: التحقق من صلاحيات النشر في القنوات المرتبطة.\n🧪 اختبار: التحقق من توكن البوت واتصاله.\n🗑 حذف: نقل البوت إلى سلة المحذوفات.\n\n"
        f"**القنوات المستخدمة:**\n{deps_text}"
    )
    buttons = [
        [InlineKeyboardButton("⏯️ تشغيل/إيقاف", callback_data=f"bot_toggle_{bid}")],
        [InlineKeyboardButton("✏️ إعادة تسمية", callback_data=f"bot_rename_{bid}")],
        [InlineKeyboardButton("🔍 فحص القنوات", callback_data=f"bot_verify_{bid}")],
        [InlineKeyboardButton("🧪 اختبار", callback_data=f"bot_test_{bid}")],
        [InlineKeyboardButton("🗑 حذف", callback_data=f"bot_delete_{bid}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="bots_list"), InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def toggle_bot(client, callback):
    bid = callback.data.split("_", 2)[2]
    b = db.get_publishing_bot(bid)
    if not b:
        await callback.answer("غير موجود.")
        return
    db.set_publishing_bot_enabled(bid, not b.get("enabled", True))
    await callback.answer("تم التحديث.")
    callback.data = f"bot_show_{bid}"
    await show_bot_settings(client, callback)


async def delete_bot_with_deps(client, callback):
    bid = callback.data.split("_", 2)[2]
    b = db.get_publishing_bot(bid)
    if not b:
        await callback.answer("غير موجود.")
        return
    # استخدام BotChannelMapper
    if hasattr(db, "mapper"):
        dep_ch_ids = db.mapper.get_channels_for_bot(bid)
        deps = [db.get_channel(cid) for cid in dep_ch_ids if db.get_channel(cid)]
    else:
        deps = db.get_dependencies_for("publishing_bot", bid)
    if deps:
        dep_text = "\n".join(f"• {entity_name(d)}" for d in deps[:10])
        text = f"⚠️ **لا يمكن حذف {b.get('name', bid)}**\n\nمستخدم من قبل:\n{dep_text}\n\nقم بإزالتها من هذه القنوات أولاً."
        buttons = [nav_row(f"bot_show_{bid}")]
        await safe_edit(callback, text, InlineKeyboardMarkup(buttons))
        return
    db.delete_publishing_bot(bid)
    await callback.answer("✅ تم النقل إلى سلة المحذوفات.")
    await bots_list_menu(client, callback)


async def test_bot(client, callback):
    bid = callback.data.split("_", 2)[2]
    b = db.get_publishing_bot(bid)
    if not b:
        await callback.answer("غير موجود.")
        return
    token = db.bot_manager.get_token(bid) if hasattr(db, "bot_manager") else b.get("token", "")
    if not token:
        await callback.answer("❌ لا يوجد توكن.", show_alert=True)
        return
    await callback.answer(f"جاري اختبار {b.get('name', bid)}...", show_alert=False)
    ver = await verifier.validate_token(token)
    if ver.get("valid"):
        username = f"@{ver['username']}" if ver.get("username") else ver.get("id", "")
        db.update_publishing_bot(bid, username=ver.get("username", ""))
        db.record_bot_publish(bid)
        await callback.answer(f"✅ {b.get('name', bid)}: {username}", show_alert=True)
    else:
        await callback.answer(f"❌ فشل: {ver.get('error', 'غير معروف')}", show_alert=True)


async def verify_bot_channels(client, callback):
    bid = callback.data.split("_", 2)[2]
    b = db.get_publishing_bot(bid)
    if not b:
        await callback.answer("غير موجود.")
        return
    token = db.bot_manager.get_token(bid) if hasattr(db, "bot_manager") else b.get("token", "")
    if not token:
        await callback.answer("❌ لا يوجد توكن.", show_alert=True)
        return
    await callback.answer(f"🔍 جاري فحص القنوات للبوت {b.get('name', bid)}...", show_alert=False)
    # استخدام BotChannelMapper للحصول على القنوات المرتبطة
    if hasattr(db, "mapper"):
        channel_ids = db.mapper.get_channels_for_bot(bid)
    else:
        raw_deps = db.get_dependencies_for("publishing_bot", bid)
        channel_ids = [d.get("id", "") for d in raw_deps]
    if not channel_ids:
        await callback.answer("لا توجد قنوات مربوطة.", show_alert=True)
        return
    ok_count = 0
    fail_count = 0
    for ch_id in channel_ids:
        ch = db.get_channel(ch_id) if hasattr(db, "get_channel") else None
        ch_name = entity_name(ch) if ch else ch_id
        try:
            ver = await verifier.check_bot_in_channel(bid, ch_id, force=True)
            if ver.get("verified") and ver.get("can_post"):
                ok_count += 1
            else:
                fail_count += 1
        except Exception as e:
            fail_count += 1
    msg = f"🔍 نتائج فحص {b.get('name', bid)}:\n✅ موثوق: {ok_count}\n❌ غير موثوق: {fail_count}"
    await callback.answer(msg, show_alert=True)
    callback.data = f"bot_show_{bid}"
    await show_bot_settings(client, callback)


async def rename_bot_prompt(client, callback):
    bid = callback.data.split("_", 2)[2]
    b = db.get_publishing_bot(bid)
    if not b:
        await callback.answer("غير موجود.")
        return
    uid = callback.from_user.id
    user_states[uid] = {"state": "waiting_bot_rename", "bot_id": bid}
    await safe_edit(callback, f"✏️ أرسل الاسم الجديد للبوت **{b.get('name', bid)}**:\n\nالاسم الحالي: `{b.get('name', bid)}`\nاليوزر: @{b.get('username', '')}", InlineKeyboardMarkup([nav_row(f"bot_show_{bid}")]))


# --- Websites ---

async def web_list_menu(client, callback):
    items = db.get_all_websites()
    text = "🌐 **مواقع الويب**\n\n✅ الموقع المفعّل يدخل ضمن دورات الجلب.\n❌ الموقع المعطّل محفوظ لكنه لا يُجلب.\n\n"
    if not items:
        text += "لا توجد مواقع."
        buttons = [[InlineKeyboardButton("➕ إضافة موقع", callback_data="web_add")], nav_row("secrets_menu")]
        await safe_edit(callback, text, InlineKeyboardMarkup(buttons))
        return
    btns = []
    for w in items:
        status = "✅" if w.get("enabled", True) else "❌"
        btns.append(InlineKeyboardButton(f"{status} {w.get('name', w['id'])}", callback_data=f"web_show_{w['id']}"))
    rows = grid_buttons(btns, 2)
    rows.append([InlineKeyboardButton("➕ إضافة موقع", callback_data="web_add")])
    rows.append(nav_row("secrets_menu"))
    text += f"العدد: {len(items)}"
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def add_website_prompt(client, callback):
    uid = callback.from_user.id
    user_states.pop(uid, None)
    user_states[uid] = {"state": "waiting_website_add"}
    await safe_edit(callback, "✏️ أرسل رابط الموقع:\n\nمثال:\n`https://example.com`\n\nيمكنك إضافة `| محدد` لاختيار عناصر محددة (CSS selector)\nمثال:\n`https://example.com | article.news`", InlineKeyboardMarkup([nav_row("web_list")]))


async def show_website_settings(client, callback):
    wid = callback.data.split("_", 2)[2]
    w = db.get_website(wid)
    if not w:
        await callback.answer("غير موجود.")
        return
    deps = db.get_dependencies_for("website", wid)
    deps_text = "\n".join(f"• {entity_name(d)}" for d in deps[:10]) if deps else "لا توجد"
    text = (
        f"🌐 **{w.get('name', wid)}**\n"
        f"🆔 `{wid}`\n"
        f"🔗 الرابط: {w.get('url', '?')}\n"
        f"🎯 المحدد: `{w.get('selector', 'body')}`\n"
        f"🔑 الحالة: {'✅ مفعل' if w.get('enabled', True) else '❌ معطل'}\n"
        f"❌ الأخطاء: {w.get('error_count', 0)}\n"
        f"🕐 آخر جلب: {_format_ts(w.get('last_fetch'))}\n\n"
        "⏯️ تشغيل/إيقاف: التحكم في جلب هذا الموقع.\n✏️ تعديل: تغيير الرابط أو المحدد.\n🧪 اختبار: جلب الموقع والتحقق من استجابته.\n🗑 حذف: نقل الموقع إلى سلة المحذوفات.\n\n"
        f"**القنوات المستخدمة:**\n{deps_text}"
    )
    buttons = [
        [InlineKeyboardButton("⏯️ تشغيل/إيقاف", callback_data=f"web_toggle_{wid}")],
        [InlineKeyboardButton("✏️ تعديل", callback_data=f"web_edit_{wid}")],
        [InlineKeyboardButton("🧪 اختبار", callback_data=f"web_test_{wid}")],
        [InlineKeyboardButton("🗑 حذف", callback_data=f"web_delete_{wid}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="web_list"), InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def toggle_website(client, callback):
    wid = callback.data.split("_", 2)[2]
    w = db.get_website(wid)
    if not w:
        await callback.answer("غير موجود.")
        return
    db.set_website_enabled(wid, not w.get("enabled", True))
    await callback.answer("تم التحديث.")
    callback.data = f"web_show_{wid}"
    await show_website_settings(client, callback)


async def edit_website_prompt(client, callback):
    wid = callback.data.split("_", 2)[2]
    w = db.get_website(wid)
    if not w:
        await callback.answer("غير موجود.")
        return
    uid = callback.from_user.id
    user_states.pop(uid, None)
    user_states[uid] = {"state": "waiting_website_edit", "website_id": wid}
    await safe_edit(callback, f"✏️ أرسل البيانات الجديدة للموقع:\n\n`الرابط | المحدد`\n\nالحالي:\nالرابط: {w.get('url')}\nالمحدد: `{w.get('selector', 'body')}`", InlineKeyboardMarkup([nav_row(f"web_show_{wid}")]))


async def delete_website_with_deps(client, callback):
    wid = callback.data.split("_", 2)[2]
    w = db.get_website(wid)
    if not w:
        await callback.answer("غير موجود.")
        return
    deps = db.get_dependencies_for("website", wid)
    if deps:
        dep_text = "\n".join(f"• {entity_name(d)}" for d in deps[:10])
        text = f"⚠️ **لا يمكن حذف {w.get('name', wid)}**\n\nمستخدم من قبل:\n{dep_text}\n\nقم بإزالتها من هذه القنوات أولاً."
        buttons = [nav_row(f"web_show_{wid}")]
        await safe_edit(callback, text, InlineKeyboardMarkup(buttons))
        return
    db.delete_website(wid)
    await callback.answer("✅ تم النقل إلى سلة المحذوفات.")
    await web_list_menu(client, callback)


async def test_website(client, callback):
    wid = callback.data.split("_", 2)[2]
    w = db.get_website(wid)
    if not w:
        await callback.answer("غير موجود.")
        return
    await callback.answer(f"جاري اختبار {w.get('name', wid)}...", show_alert=False)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as hc:
            resp = await hc.get(w.get("url", ""), headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                content_len = len(resp.text)
                db.update_website(wid, last_fetch=int(time.time()))
                await callback.answer(f"✅ متاح! {content_len} حرف", show_alert=True)
            else:
                await callback.answer(f"❌ HTTP {resp.status_code}", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ فشل: {str(e)[:100]}", show_alert=True)


# --- Trash ---

async def trash_menu(client, callback):
    items = db.get_trash_items()
    text = "🗑 **سلة المحذوفات**\n\n♻️ الاستعادة: يعيد العنصر إلى قائمته السابقة.\n🗑 الحذف النهائي: يزيل العنصر نهائياً ولا يمكن التراجع عنه.\n\n"
    if not items:
        text += "السلة فارغة."
        buttons = [nav_row("secrets_menu")]
        await safe_edit(callback, text, InlineKeyboardMarkup(buttons))
        return
    type_labels = {"session": "📱 جلسة", "ai_key": "🧠 مفتاح AI", "publishing_bot": "🤖 بوت", "website": "🌐 موقع"}
    rows = []
    for idx, item in enumerate(items[:30]):
        t = item.get("type", "")
        label = type_labels.get(t, t)
        name = item.get("data", {}).get("name", item.get("original_id", ""))
        tid = item.get("id", "")
        rows.append([
            InlineKeyboardButton(f"♻️ {label}: {name}", callback_data=f"trash_restore_{tid}"),
            InlineKeyboardButton(f"🗑 حذف", callback_data=f"trash_permdel_{tid}"),
        ])
    rows.append([InlineKeyboardButton("🗑 حذف نهائي للكل", callback_data="trash_empty_prompt")])
    rows.append(nav_row("secrets_menu"))
    text += f"العدد: {len(items)}"
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def trash_restore_item(client, callback):
    tid = callback.data.split("_", 2)[2]
    ok = db.restore_from_trash(tid)
    if ok:
        await callback.answer("✅ تمت الاستعادة.")
    else:
        await callback.answer("❌ فشل الاستعادة.", show_alert=True)
    await trash_menu(client, callback)


async def trash_permanent_delete_prompt(client, callback):
    tid = callback.data.split("_", 2)[2]
    text = "⚠️ **تأكيد الحذف النهائي**\n\nهل تريد حذف هذا العنصر نهائياً؟ لا يمكن التراجع."
    buttons = [
        [InlineKeyboardButton("✅ نعم، احذف نهائياً", callback_data=f"trash_permconfirm_{tid}")],
        nav_row("trash_menu"),
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def trash_permanent_delete_confirm(client, callback):
    tid = callback.data.split("_", 2)[2]
    ok = db.permanent_delete_from_trash(tid)
    await callback.answer("✅ تم الحذف النهائي." if ok else "❌ فشل.", show_alert=True)
    await trash_menu(client, callback)


async def trash_empty_prompt(client, callback):
    text = "⚠️ **تفريغ سلة المحذوفات**\n\nسيتم حذف جميع العناصر نهائياً. لا يمكن التراجع."
    buttons = [
        [InlineKeyboardButton("✅ نعم، امسح الكل", callback_data="trash_empty_confirm")],
        nav_row("trash_menu"),
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def trash_empty_confirm(client, callback):
    db.empty_trash()
    await callback.answer("✅ تم تفريغ السلة.")
    await trash_menu(client, callback)


# --- Channel Extended Settings ---

async def channel_extended_settings(client, callback):
    ch_id = callback.data.split("_", 2)[2]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("غير موجودة.")
        return
    cfg = db.get_channel_config(ch_id)
    disable_preview = db.get_channel_disable_preview(ch_id) if hasattr(db, "get_channel_disable_preview") else False
    text = (
        f"⚙️ **الإعدادات المتقدمة:**\n{entity_name(ch)}\n\n"
        f"💬 اقتباس العنوان: {'✅ مفعل' if cfg.get('title_quote') else '❌ متوقف'}\n"
        f"💬 اقتباس التوقيع: {'✅ مفعل' if cfg.get('signature_quote') else '❌ متوقف'}\n"
        f"🔗 إخفاء معاينة الروابط: {'✅ مفعل' if disable_preview else '❌ متوقف'}\n"
        f"📱 الجلسات المخصصة: {len(cfg.get('assigned_sessions', []))}\n"
        f"🤖 البوتات المخصصة: {len(cfg.get('assigned_bots', []))}\n"
        f"🧠 AI المخصص: {len(cfg.get('assigned_ai', []))}\n"
        f"🌐 مواقع مخصصة: {len(cfg.get('websites', []))}\n\n"
        "💬 الاقتباس: التحكم في تنسيق العنوان والتوقيع.\n🔗 المعاينة: إظهار أو إخفاء معاينة الروابط.\n📱/🤖/🧠/🌐 التخصيص: اختيار الموارد التي تستخدمها هذه القناة.\n"
    )
    buttons = [
        [InlineKeyboardButton(f"💬 اقتباس العنوان: {'✅' if cfg.get('title_quote') else '❌'}", callback_data=f"ch_titlequote_{ch_id}")],
        [InlineKeyboardButton(f"💬 اقتباس التوقيع: {'✅' if cfg.get('signature_quote') else '❌'}", callback_data=f"ch_sigquote_{ch_id}")],
        [InlineKeyboardButton(f"🔗 معاينة: {'✅' if not disable_preview else '❌'}", callback_data=f"ch_preview_{ch_id}")],
        [InlineKeyboardButton("📱 الجلسات", callback_data=f"assign_sessions_{ch_id}"), InlineKeyboardButton("🤖 البوتات", callback_data=f"assign_bots_{ch_id}")],
        [InlineKeyboardButton("🧠 AI", callback_data=f"assign_ai_{ch_id}"), InlineKeyboardButton("🌐 مواقع", callback_data=f"assign_websites_{ch_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"ch_{ch_id}"), InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def toggle_channel_title_quote(client, callback):
    ch_id = callback.data.split("_", 2)[2]
    cfg = db.get_channel_config(ch_id)
    db.set_channel_title_quote(ch_id, not cfg.get("title_quote", False))
    await callback.answer("تم التحديث.")
    callback.data = f"quotemenu_{ch_id}"
    await channel_quote_menu(client, callback)


async def toggle_channel_signature_quote(client, callback):
    ch_id = callback.data.split("_", 2)[2]
    cfg = db.get_channel_config(ch_id)
    db.set_channel_signature_quote(ch_id, not cfg.get("signature_quote", False))
    await callback.answer("تم التحديث.")
    callback.data = f"quotemenu_{ch_id}"
    await channel_quote_menu(client, callback)


async def toggle_channel_preview(client, callback):
    ch_id = callback.data.split("_", 2)[2]
    cur = db.get_channel_disable_preview(ch_id) if hasattr(db, "get_channel_disable_preview") else False
    db.set_channel_disable_preview(ch_id, not cur)
    await callback.answer("تم التحديث.")
    callback.data = f"postset_{ch_id}"
    await post_settings_menu(client, callback)


# ============================================================
# General Channel Settings (الإعدادات العامة للقناة)
# ============================================================

async def general_settings_menu(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("القناة غير موجودة.")
        return
    buttons = [
        InlineKeyboardButton("📋 ملخص الإعدادات", callback_data=f"genset_summary_{ch_id}"),
        InlineKeyboardButton("📄 نسخ الإعدادات", callback_data=f"genset_copy_{ch_id}"),
        InlineKeyboardButton("📥 لصق الإعدادات", callback_data=f"genset_paste_{ch_id}"),
        InlineKeyboardButton("♻️ إعادة التعيين", callback_data=f"genset_reset_{ch_id}"),
        InlineKeyboardButton("🤖 التحقق من البوت", callback_data=f"chbotcheck|{ch_id}"),
        InlineKeyboardButton(f"{'⏸️' if ch.get('paused') else '▶️'} تشغيل/إيقاف القناة", callback_data=f"toggle_{ch_id}"),
        InlineKeyboardButton("📱 الجلسات", callback_data=f"assign_sessions_{ch_id}"),
        InlineKeyboardButton("🤖 البوتات", callback_data=f"assign_bots_{ch_id}"),
        InlineKeyboardButton("🧠 AI", callback_data=f"assign_ai_{ch_id}"),
        InlineKeyboardButton("🌐 المواقع", callback_data=f"assign_websites_{ch_id}"),
        InlineKeyboardButton("🗑 حذف القناة", callback_data=f"delchannel_{ch_id}"),
    ]
    rows = grid_buttons(buttons, 2)
    rows.append(nav_row(f"ch_{ch_id}"))
    ch_state = '⏸️ متوقفة' if ch.get('paused') else '▶️ تعمل'
    await safe_edit(callback, f"⚙️ **الإعدادات العامة**\n{channel_display_name(ch_id)}\n\nالحالة: {ch_state}\n\n📋 الملخص: عرض الإعدادات الحالية.\n📄 نسخ / 📥 لصق: نقل الإعدادات بين القنوات.\n♻️ إعادة التعيين: استرجاع القيم الافتراضية.\n🤖 التحقق: فحص صلاحية بوت القناة.\n▶️/⏸️ تشغيل/إيقاف: التحكم في استقبال القناة للمنشورات.\n📱 الجلسات / 🤖 البوتات / 🧠 AI / 🌐 المواقع: إدارة الموارد المخصصة.\n🗑 حذف القناة: إزالة القناة بعد التأكيد.", InlineKeyboardMarkup(rows))


# ============================================================
# 🖥 النظام — خاص بكل قناة على حدة
# ============================================================

async def system_channel_menu(client, callback):
    ch_id = callback.data.split("_", 1)[1]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("القناة غير موجودة.")
        return
    buttons = [
        InlineKeyboardButton("🧪 اختبار القناة", callback_data=f"testset_{ch_id}"),
        InlineKeyboardButton("🔍 الفحص الشامل", callback_data=f"full_check|{ch_id}"),
        InlineKeyboardButton("📊 حالة النظام", callback_data=f"system_status|{ch_id}"),
        InlineKeyboardButton("▶️ إدارة التشغيل", callback_data=f"ops_menu|{ch_id}"),
        InlineKeyboardButton("📝 إدارة السجل", callback_data=f"log_menu|{ch_id}"),
        InlineKeyboardButton("🔔 الإشعارات", callback_data=f"notifications_menu|{ch_id}"),
    ]
    rows = grid_buttons(buttons, 2)
    rows.append(nav_row(f"ch_{ch_id}"))
    await safe_edit(callback, f"🖥 **النظام**\n{channel_display_name(ch_id)}\n\n🧪 اختبار القناة: تجربة إعدادات القناة.\n🔍 الفحص الشامل: فحص الموارد والصلاحيات.\n📊 حالة النظام: عرض الحالة والإحصائيات.\n▶️ إدارة التشغيل: الصيانة واختبار القنوات والأخطاء.\n📝 إدارة السجل: عرض أو تحديث أو مسح السجل.\n🔔 الإشعارات: التحكم في تنبيهات النظام.", InlineKeyboardMarkup(rows))


async def general_settings_copy(client, callback):
    """نسخ إعدادات القناة إلى الحافظة."""
    ch_id = callback.data.split("_", 2)[2]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("غير موجودة.")
        return
    clip = {
        "bold_publish": ch.get("bold_publish", True),
        "tail": ch.get("tail", ""),
        "tail_enabled": ch.get("tail_enabled", True),
        "tail_min_words": ch.get("tail_min_words", 20),
        "tail_position": ch.get("tail_position", "bottom"),
        "quote_types": ch.get("quote_types", {"text": False, "photo": False, "video": False, "album": False}),
        "publish_delay": ch.get("publish_delay"),
        "hashtags": ch.get("hashtags", []),
        "disable_web_page_preview": ch.get("disable_web_page_preview", False),
        "link_remove_tg": ch.get("link_remove_tg", False),
        "link_remove_tg_user": ch.get("link_remove_tg_user", False),
        "link_remove_web": ch.get("link_remove_web", False),
    }
    if hasattr(db, "set_settings_clipboard"):
        db.set_settings_clipboard(clip)
    await callback.answer("✅ تم نسخ إعدادات هذه القناة.", show_alert=True)


async def general_settings_paste(client, callback):
    """لصق إعدادات القناة من الحافظة مع تأكيد."""
    ch_id = callback.data.split("_", 2)[2]
    clip = db.get_settings_clipboard() if hasattr(db, "get_settings_clipboard") else None
    if not clip:
        await callback.answer("❌ لا توجد إعدادات منسوخة. انسخ أولاً.", show_alert=True)
        return
    text = (
        f"⚠️ **هل تريد استبدال إعدادات هذه القناة؟**\n\n"
        f"{entity_name(db.get_channel(ch_id))}\n\n"
        f"سيتم لصق آخر إعدادات تم نسخها."
    )
    buttons = [
        [InlineKeyboardButton("✅ نعم", callback_data=f"genset_paste_confirm_{ch_id}")],
        nav_row(f"genset_{ch_id}"),
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def general_settings_paste_confirm(client, callback):
    """تأكيد لصق الإعدادات."""
    ch_id = callback.data.split("_", 3)[3]
    clip = db.get_settings_clipboard() if hasattr(db, "get_settings_clipboard") else None
    if not clip:
        await callback.answer("❌ لا توجد إعدادات.", show_alert=True)
        return
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("غير موجودة.")
        return
    for key in ("bold_publish", "tail", "tail_enabled", "tail_min_words", "tail_position", "quote_types", "publish_delay", "hashtags", "disable_web_page_preview", "link_remove_tg", "link_remove_tg_user", "link_remove_web"):
        if key in clip:
            db.update_channel(ch_id, key, clip[key])
    await callback.answer("✅ تم لصق الإعدادات بنجاح.", show_alert=True)
    callback.data = f"genset_{ch_id}"
    await general_settings_menu(client, callback)


async def general_settings_reset(client, callback):
    """إعادة تعيين إعدادات القناة إلى الافتراضية مع تأكيد."""
    ch_id = callback.data.split("_", 2)[2]
    text = (
        f"⚠️ **إعادة تعيين إعدادات القناة؟**\n\n"
        f"{entity_name(db.get_channel(ch_id))}\n\n"
        f"سيتم إرجاع جميع الإعدادات إلى القيم الافتراضية.\n"
        f"لن يتم حذف القناة أو المصادر أو الربط."
    )
    buttons = [
        [InlineKeyboardButton("✅ نعم", callback_data=f"genset_reset_confirm_{ch_id}")],
        nav_row(f"genset_{ch_id}"),
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def general_settings_reset_confirm(client, callback):
    """تأكيد إعادة التعيين."""
    ch_id = callback.data.split("_", 3)[3]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("غير موجودة.")
        return
    db.update_channel(ch_id, "bold_publish", True)
    db.update_channel(ch_id, "tail", "")
    db.update_channel(ch_id, "tail_enabled", True)
    db.update_channel(ch_id, "tail_min_words", 20)
    if hasattr(db, "set_channel_tail_position"):
        db.set_channel_tail_position(ch_id, "bottom")
    if hasattr(db, "set_channel_quote_publish"):
        db.set_channel_quote_publish(ch_id, False)
    db.update_channel(ch_id, "publish_delay", None)
    if hasattr(db, "set_channel_disable_preview"):
        db.set_channel_disable_preview(ch_id, False)
    db.update_channel(ch_id, "link_remove_tg", False)
    db.update_channel(ch_id, "link_remove_tg_user", False)
    db.update_channel(ch_id, "link_remove_web", False)
    await callback.answer("♻️ تم إعادة تعيين الإعدادات.", show_alert=True)
    callback.data = f"genset_{ch_id}"
    await general_settings_menu(client, callback)


async def general_settings_summary(client, callback):
    ch_id = callback.data.split("_", 2)[2]
    ch = db.get_channel(ch_id)
    if not ch:
        await callback.answer("غير موجودة.")
        return
    bold = ch.get("bold_publish", True)
    tail = ch.get("tail", "")
    tail_enabled = ch.get("tail_enabled", True)
    tail_min = ch.get("tail_min_words", 20)
    tail_pos = ch.get("tail_position", "bottom")
    quote_types = get_channel_quote_types_safe(ch_id)
    hashtags = ch.get("hashtags", [])
    delay = ch.get("publish_delay")
    sources = ch.get("special_sources", [])
    if hasattr(db, "mapper"):
        bot_count = len(db.mapper.get_bots_for_channel(ch_id))
    else:
        cfg = db.get_channel_config(ch_id) if hasattr(db, "get_channel_config") else {}
        bot_count = len(cfg.get("assigned_bots", []))

    enabled_count = 0
    disabled_count = 0
    lines = [f"📊 **ملخص إعدادات {entity_name(ch)}**\n"]

    lines.append("\n📝 **المنشورات**")
    if bold:
        lines.append("✅ الخط السميك"); enabled_count += 1
    else:
        lines.append("❌ الخط السميك"); disabled_count += 1
    lines.append(f"{'✅' if quote_types.get('text') else '❌'} اقتباس النصوص")
    if quote_types.get('text'): enabled_count += 1
    else: disabled_count += 1
    lines.append(f"{'✅' if quote_types.get('photo') else '❌'} اقتباس الصور")
    if quote_types.get('photo'): enabled_count += 1
    else: disabled_count += 1
    lines.append(f"{'✅' if quote_types.get('video') else '❌'} اقتباس الفيديو")
    if quote_types.get('video'): enabled_count += 1
    else: disabled_count += 1
    lines.append(f"{'✅' if quote_types.get('album') else '❌'} اقتباس الألبومات")
    if quote_types.get('album'): enabled_count += 1
    else: disabled_count += 1
    lines.append(f"{'✅' if hashtags else '❌'} الهاشتاكات ({len(hashtags)})")
    if hashtags: enabled_count += 1
    else: disabled_count += 1
    lines.append(f"{'✅' if delay is None else '⚠️'} سرعة النشر: {delay or 'افتراضي'}")
    enabled_count += 1

    lines.append(f"\n🔗 **الروابط**")
    lines.append(f"{'✅' if ch.get('link_remove_tg') else '❌'} حذف روابط تيليجرام")
    if ch.get("link_remove_tg"): enabled_count += 1
    else: disabled_count += 1
    lines.append(f"{'✅' if ch.get('link_remove_tg_user') else '❌'} حذف يوزرات @")
    if ch.get("link_remove_tg_user"): enabled_count += 1
    else: disabled_count += 1
    lines.append(f"{'✅' if ch.get('link_remove_web') else '❌'} حذف روابط المواقع")
    if ch.get("link_remove_web"): enabled_count += 1
    else: disabled_count += 1

    lines.append(f"\n🔖 **التوقيع**")
    lines.append(f"{'✅' if tail_enabled else '❌'} تشغيل")
    if tail_enabled: enabled_count += 1
    else: disabled_count += 1
    lines.append(f"{'⬆️ أعلى' if tail_pos == 'top' else '⬇️ أسفل'} المنشور")
    enabled_count += 1
    if tail_min >= 20:
        lines.append(f"✅ شرط {tail_min} كلمة"); enabled_count += 1
    else:
        lines.append(f"❌ شرط الكلمات"); disabled_count += 1
    if tail:
        lines.append(f"📝 النص: {tail[:30]}{'...' if len(tail) > 30 else ''}")

    lines.append(f"\n📚 **المصادر**")
    lines.append(f"{len(sources)} مصدر مخصص")
    lines.append(f"{bot_count} بوت نشر")

    lines.append(f"\n-----------------------")
    lines.append(f"🟢 مفعل: {enabled_count}")
    lines.append(f"🔴 متوقف: {disabled_count}")

    buttons = [
        nav_row(f"genset_{ch_id}"),
    ]
    await safe_edit(callback, "\n".join(lines), InlineKeyboardMarkup(buttons))


async def ui_setting_info_menu(client, callback):
    """صفحة شرح وتحكم موحدة لإعدادات Boolean؛ لا تنفذ التغيير عند فتحها."""
    parts = callback.data.split("|", 3)
    if len(parts) != 4:
        await callback.answer("طلب غير صالح.", show_alert=True)
        return
    _, kind, target, back = parts
    ch_id = target if target != "global" else None
    back_target = back.replace("~", "|") if back else (_peek_prev_back(callback) or "main_menu")
    back_token = back_target.replace("|", "~")
    state = False
    if kind == "short_posts":
        state = is_ignore_short_posts_enabled_for_channel(ch_id) if ch_id else is_ignore_short_posts_enabled()
        title, purpose = "📝 النصوص القصيرة", "يحدد هل تُمنع المنشورات النصية القصيرة من النشر في هذه القناة."
        on_desc, off_desc = "يتم منع نشر المنشورات النصية القصيرة.", "تُنشر المنشورات النصية القصيرة بشكل طبيعي."
    elif kind == "bold":
        ch = db.get_channel(ch_id) or {}
        state = bool(ch.get("bold_publish", True))
        title, purpose = "🖊 الخط السميك", "يحدد استخدام الخط السميك عند تنسيق منشورات هذه القناة."
        on_desc, off_desc = "تُنشر النصوص المدعومة بالخط السميك.", "تُنشر النصوص دون تفعيل الخط السميك."
    elif kind == "title_quote":
        cfg = db.get_channel_config(ch_id) if ch_id and hasattr(db, "get_channel_config") else {}
        state = bool(cfg.get("title_quote"))
        title, purpose = "💬 اقتباس العنوان", "يحدد هل يظهر عنوان المنشور بصيغة اقتباس Telegram."
        on_desc, off_desc = "يظهر العنوان داخل اقتباس.", "يُنشر العنوان بصيغة عادية."
    elif kind == "signature_quote":
        cfg = db.get_channel_config(ch_id) if ch_id and hasattr(db, "get_channel_config") else {}
        state = bool(cfg.get("signature_quote"))
        title, purpose = "💬 اقتباس التوقيع", "يحدد هل يظهر التوقيع بصيغة اقتباس Telegram."
        on_desc, off_desc = "يظهر التوقيع داخل اقتباس.", "يُنشر التوقيع بصيغة عادية."
    elif kind == "preview":
        disabled = db.get_channel_disable_preview(ch_id) if ch_id and hasattr(db, "get_channel_disable_preview") else False
        state = not bool(disabled)
        title, purpose = "🔗 معاينة الروابط", "يحدد هل تظهر معاينة الروابط عند نشر منشورات هذه القناة."
        on_desc, off_desc = "تظهر معاينة الروابط.", "تُنشر الروابط دون معاينة."
    elif kind == "maintenance":
        state = bool(db.is_maintenance_mode()) if hasattr(db, "is_maintenance_mode") else False
        title, purpose = "🛠 وضع الصيانة", "يوقف النشر مع إبقاء فحص المصادر مستمراً."
        on_desc, off_desc = "يتوقف النشر وتستمر عملية فحص المصادر.", "يعود النشر إلى العمل الطبيعي."
    elif kind == "notification":
        settings = db.get_notification_settings() if hasattr(db, "get_notification_settings") else {}
        state = bool(settings.get(target, True))
        title = "🔔 " + str(getattr(db, "NOTIFICATION_TYPES", {}).get(target, target))
        purpose = "يحدد هل يرسل البوت هذا النوع من التنبيهات للمشرفين."
        on_desc, off_desc = "يتم إرسال هذا التنبيه عند حدوثه.", "لا يتم إرسال هذا النوع من التنبيهات."
    elif kind.startswith("quote_"):
        qtype = kind.split("_", 1)[1]
        state = bool(get_channel_quote_types_safe(ch_id).get(qtype, False))
        labels = {"text": "النصوص", "photo": "الصور", "video": "الفيديو", "album": "الألبومات"}
        title, purpose = "💬 اقتباس " + labels.get(qtype, qtype), "يحدد هل يُنشر هذا النوع بصيغة اقتباس رسمي في هذه القناة."
        on_desc, off_desc = "يُنشر هذا النوع داخل اقتباس رسمي.", "يُنشر هذا النوع بصيغته العادية."
    elif kind == "tail":
        state = bool(db.get_channel_tail_enabled(ch_id)) if hasattr(db, "get_channel_tail_enabled") else True
        title, purpose = "🔖 التوقيع", "يحدد هل يضاف توقيع القناة إلى المنشورات."
        on_desc, off_desc = "يُضاف التوقيع إلى المنشورات وفق الإعدادات الحالية.", "لا يُضاف التوقيع إلى المنشورات."
    elif kind == "quote_type":
        try:
            ch_id, qtype = target.split("~", 1)
        except ValueError:
            await callback.answer("إعداد اقتباس غير صالح.", show_alert=True)
            return
        state = bool(get_channel_quote_types_safe(ch_id).get(qtype, False))
        labels = {"text": "النصوص", "photo": "الصور", "video": "الفيديو", "album": "الألبومات"}
        title = "💬 اقتباس " + labels.get(qtype, qtype)
        purpose = "يحدد هل يُنشر هذا النوع بصيغة اقتباس رسمية في هذه القناة."
        on_desc, off_desc = "يُنشر هذا النوع داخل اقتباس رسمي.", "يُنشر هذا النوع بصيغته العادية."
    elif kind == "source_enabled":
        state = not bool(db.is_source_paused(target))
        title, purpose = "🟢 تشغيل المصدر", "يحدد هل يستمر هذا المصدر في استقبال المنشورات."
        on_desc, off_desc = "يستمر استقبال منشورات المصدر.", "يتوقف استقبال منشورات المصدر مؤقتاً."
    elif kind == "source_emoji":
        state = bool(db.get_source_remove_emoji(target))
        title, purpose = "🙂 إزالة الإيموجي", "يحدد هل تُزال الإيموجيات من منشورات هذا المصدر."
        on_desc, off_desc = "تُزال الإيموجيات من منشورات المصدر.", "تبقى الإيموجيات في منشورات المصدر."
    elif kind == "source_content":
        try:
            source_id, ctype = target.split("~", 1)
        except ValueError:
            await callback.answer("فلتر محتوى غير صالح.", show_alert=True)
            return
        state = bool(db.get_source_content_types(source_id).get(ctype, True))
        title, purpose = "📰 نوع المحتوى", "يحدد هل يستقبل المصدر هذا النوع من المنشورات."
        on_desc, off_desc = "يتم استقبال هذا النوع من المصدر.", "يتم تجاهل هذا النوع من المصدر."
    elif kind.startswith("link_"):
        key = kind
        state = bool((db.get_channel(ch_id) or {}).get(key, False))
        labels = {"link_remove_tg": "روابط Telegram", "link_remove_tg_user": "مستخدمو Telegram", "link_remove_web": "روابط المواقع"}
        title, purpose = "🔗 " + labels.get(key, key), "يحدد هل يُزال هذا النوع من الروابط من منشورات القناة."
        on_desc, off_desc = "تُزال هذه الروابط من المنشورات.", "تبقى هذه الروابط في المنشورات."
    elif kind == "tail_min":
        cfg = db.get_channel_config(ch_id) if hasattr(db, "get_channel_config") else {}
        state = int(cfg.get("tail_min_words", 20) or 0) > 0
        title, purpose = "🔢 الحد الأدنى للتوقيع", "يحدد هل يُطبّق الحد الأدنى للكلمات قبل إضافة التوقيع."
        on_desc, off_desc = "يُضاف التوقيع عند بلوغ الحد الأدنى الحالي.", "لا يُطبّق حد أدنى للكلمات."
    elif kind == "tail_pos":
        position = db.get_channel_tail_position(ch_id) if hasattr(db, "get_channel_tail_position") else "bottom"
        state = position == "top"
        title, purpose = "📍 مكان التوقيع", "يحدد موضع التوقيع في أعلى المنشور أو أسفله."
        on_desc, off_desc = "يوضع التوقيع أعلى المنشور.", "يوضع التوقيع أسفل المنشور."
    elif kind == "pause":
        ch = db.get_channel(ch_id) or {}
        state = not bool(ch.get("paused", False))
        title, purpose = "⏯️ تشغيل القناة", "يحدد هل تستمر القناة في معالجة ونشر المنشورات."
        on_desc, off_desc = "تستمر القناة في العمل والنشر.", "تتوقف القناة مؤقتاً عن المعالجة والنشر."
    elif kind == "assign":
        try:
            rtype, ch_id, item_id = target.split("~", 2)
        except ValueError:
            await callback.answer("تعيين مورد غير صالح.", show_alert=True)
            return
        info = _RESOURCE_MAP.get(rtype)
        if not info:
            await callback.answer("نوع مورد غير معروف.", show_alert=True)
            return
        if rtype == "bots" and hasattr(db, "mapper"):
            state = bool(db.mapper.is_assigned(item_id, ch_id))
        else:
            cfg = db.get_channel_config(ch_id) or {}
            state = str(item_id) in [str(x) for x in cfg.get(info["cfg_key"], [])]
        title, purpose = "🔧 تعيين المورد", "يحدد هل هذا المورد مرتبط بهذه القناة."
        on_desc, off_desc = "يُستخدم المورد مع هذه القناة.", "لا يُستخدم المورد مع هذه القناة."
    elif kind == "session":
        item = db.get_session(target) or {}
        state = bool(item.get("enabled", True))
        title, purpose = "🔐 الجلسة", "يحدد هل تكون جلسة Telegram متاحة للتشغيل."
        on_desc, off_desc = "تبقى الجلسة متاحة للتشغيل.", "تتوقف الجلسة عن التشغيل."
    elif kind == "ai_key":
        item = db.get_ai_key(target) or {}
        state = bool(item.get("enabled", True))
        title, purpose = "🤖 مفتاح الذكاء الاصطناعي", "يحدد هل يمكن استخدام هذا المفتاح في عمليات AI."
        on_desc, off_desc = "يمكن استخدام المفتاح.", "لا يُستخدم المفتاح."
    elif kind == "publishing_bot":
        item = db.get_publishing_bot(target) or {}
        state = bool(item.get("enabled", True))
        title, purpose = "🤖 بوت النشر", "يحدد هل يمكن استخدام بوت النشر هذا."
        on_desc, off_desc = "يبقى البوت متاحاً للنشر.", "يتوقف استخدام البوت للنشر."
    elif kind == "website":
        item = db.get_website(target) or {}
        state = bool(item.get("enabled", True))
        title, purpose = "🌐 الموقع", "يحدد هل يمكن استخدام مصدر الموقع هذا."
        on_desc, off_desc = "يبقى الموقع متاحاً للاستخدام.", "يتوقف استخدام الموقع."
    else:
        await callback.answer("إعداد غير معروف.", show_alert=True)
        return
    current = "✅ مفعّل" if state else "❌ متوقف"
    text = f"{title}\n\nوظيفة الإعداد:\n{purpose}\n\nالحالة الحالية:\n{current}\n\nعند التشغيل:\n{on_desc}\n\nعند الإيقاف:\n{off_desc}"
    rows = [[InlineKeyboardButton("✅ تشغيل", callback_data=f"ui_set|{kind}|{target}|{back_token}|1")], [InlineKeyboardButton("❌ إيقاف", callback_data=f"ui_set|{kind}|{target}|{back_token}|0")], [InlineKeyboardButton("🔙 رجوع", callback_data=back_target)]]
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def ui_setting_set(client, callback):
    """يحفظ اختيار المستخدم ثم يعيد فتح صفحة الإعداد نفسها بالحالة الجديدة."""
    parts = callback.data.split("|", 4)
    if len(parts) != 5:
        await callback.answer("طلب غير صالح.", show_alert=True)
        return
    _, kind, target, back, desired_raw = parts
    back = back.replace("~", "|") if back else (_peek_prev_back(callback) or "main_menu")
    desired = desired_raw == "1"
    ch_id = target if target != "global" else None
    if kind == "short_posts":
        current = is_ignore_short_posts_enabled_for_channel(ch_id) if ch_id else is_ignore_short_posts_enabled()
        if current != desired:
            if ch_id and hasattr(db, "set_channel_ignore_short_posts"):
                db.set_channel_ignore_short_posts(ch_id, desired)
            elif hasattr(db, "set_ignore_short_posts"):
                db.set_ignore_short_posts(desired)
        label = "منع النصوص القصيرة"
        result = "سيتم منع المنشورات النصية القصيرة في هذه القناة." if desired else "سيتم نشر المنشورات النصية القصيرة بشكل طبيعي."
    elif kind == "bold":
        ch = db.get_channel(ch_id) or {}
        current = bool(ch.get("bold_publish", True))
        if current != desired:
            db.update_channel(ch_id, "bold_publish", desired)
        label, result = "الخط السميك", "سيُستخدم الخط السميك عند توفره." if desired else "لن يُفعّل الخط السميك."
    elif kind == "title_quote":
        cfg = db.get_channel_config(ch_id) if hasattr(db, "get_channel_config") else {}
        current = bool(cfg.get("title_quote"))
        if current != desired and hasattr(db, "set_channel_title_quote"):
            db.set_channel_title_quote(ch_id, desired)
        label, result = "اقتباس العنوان", "سيظهر العنوان داخل اقتباس." if desired else "سيُنشر العنوان بصيغة عادية."
    elif kind == "signature_quote":
        cfg = db.get_channel_config(ch_id) if hasattr(db, "get_channel_config") else {}
        current = bool(cfg.get("signature_quote"))
        if current != desired and hasattr(db, "set_channel_signature_quote"):
            db.set_channel_signature_quote(ch_id, desired)
        label, result = "اقتباس التوقيع", "سيظهر التوقيع داخل اقتباس." if desired else "سيُنشر التوقيع بصيغة عادية."
    elif kind == "preview":
        current = not bool(db.get_channel_disable_preview(ch_id)) if hasattr(db, "get_channel_disable_preview") else True
        if current != desired and hasattr(db, "set_channel_disable_preview"):
            db.set_channel_disable_preview(ch_id, not desired)
        label, result = "معاينة الروابط", "ستظهر معاينة الروابط." if desired else "ستُنشر الروابط دون معاينة."
    elif kind == "maintenance":
        current = bool(db.is_maintenance_mode()) if hasattr(db, "is_maintenance_mode") else False
        if current != desired and hasattr(db, "set_maintenance_mode"):
            db.set_maintenance_mode(desired)
        label, result = "وضع الصيانة", "توقف النشر واستمر فحص المصادر." if desired else "عاد النشر إلى العمل الطبيعي."
    elif kind == "notification":
        settings = db.get_notification_settings() if hasattr(db, "get_notification_settings") else {}
        current = bool(settings.get(target, True))
        if current != desired and hasattr(db, "set_notification_setting"):
            db.set_notification_setting(target, desired)
        label, result = "التنبيه", "سيتم إرسال التنبيه." if desired else "لن يتم إرسال التنبيه."
    elif kind.startswith("quote_"):
        qtype = kind.split("_", 1)[1]
        current = bool(get_channel_quote_types_safe(ch_id).get(qtype, False))
        if current != desired and hasattr(db, "set_channel_quote_type"):
            db.set_channel_quote_type(ch_id, qtype, desired)
        label, result = "اقتباس النوع", "سيُنشر النوع داخل اقتباس رسمي." if desired else "سيُنشر النوع بصيغته العادية."
    elif kind == "tail":
        current = bool(db.get_channel_tail_enabled(ch_id)) if hasattr(db, "get_channel_tail_enabled") else True
        if current != desired and hasattr(db, "set_channel_tail_enabled"):
            db.set_channel_tail_enabled(ch_id, desired)
        label, result = "التوقيع", "سيُضاف التوقيع إلى المنشورات." if desired else "لن يُضاف التوقيع إلى المنشورات."
    elif kind == "quote_type":
        try:
            ch_id, qtype = target.split("~", 1)
        except ValueError:
            await callback.answer("إعداد اقتباس غير صالح.", show_alert=True)
            return
        current = bool(get_channel_quote_types_safe(ch_id).get(qtype, False))
        if current != desired and hasattr(db, "set_channel_quote_type"):
            db.set_channel_quote_type(ch_id, qtype, desired)
        label, result = "اقتباس النوع", "سيُنشر النوع داخل اقتباس رسمي." if desired else "سيُنشر النوع بصيغته العادية."
    elif kind == "source_enabled":
        current = not bool(db.is_source_paused(target))
        if current != desired:
            db.set_source_paused(target, not desired)
        label, result = "تشغيل المصدر", "يستمر استقبال منشورات المصدر." if desired else "يتوقف استقبال منشورات المصدر مؤقتاً."
    elif kind == "source_emoji":
        current = bool(db.get_source_remove_emoji(target))
        if current != desired:
            db.set_source_remove_emoji(target, desired)
        label, result = "إزالة الإيموجي", "تُزال الإيموجيات من منشورات المصدر." if desired else "تبقى الإيموجيات في منشورات المصدر."
    elif kind == "source_content":
        try:
            source_id, ctype = target.split("~", 1)
        except ValueError:
            await callback.answer("فلتر محتوى غير صالح.", show_alert=True)
            return
        current = bool(db.get_source_content_types(source_id).get(ctype, True))
        if current != desired:
            ok = db.set_source_content_type(source_id, ctype, desired)
            if ok is False:
                await callback.answer("لا يمكن إيقاف آخر نوع محتوى.", show_alert=True)
                callback.data = f"ui_info|{kind}|{target}|{back.replace('|', '~')}"
                await ui_setting_info_menu(client, callback)
                return
        label, result = "نوع المحتوى", "يتم استقبال هذا النوع من المصدر." if desired else "يتم تجاهل هذا النوع من المصدر."
    elif kind.startswith("link_"):
        key = kind
        ch = db.get_channel(ch_id) or {}
        current = bool(ch.get(key, False))
        if current != desired:
            db.update_channel(ch_id, key, desired)
        label, result = "فلتر الروابط", "تُزال هذه الروابط من المنشورات." if desired else "تبقى هذه الروابط في المنشورات."
    elif kind == "tail_min":
        current = int(db.get_channel_tail_min_words(ch_id) if hasattr(db, "get_channel_tail_min_words") else 20) >= 20
        if current != desired and hasattr(db, "set_channel_tail_min_words"):
            db.set_channel_tail_min_words(ch_id, 20 if desired else 0)
        label, result = "الحد الأدنى للتوقيع", "يُطبّق حد 20 كلمة للتوقيع." if desired else "لا يُطبّق حد أدنى للكلمات."
    elif kind == "tail_pos":
        current = (db.get_channel_tail_position(ch_id) if hasattr(db, "get_channel_tail_position") else "bottom") == "top"
        if current != desired and hasattr(db, "set_channel_tail_position"):
            db.set_channel_tail_position(ch_id, "top" if desired else "bottom")
        label, result = "مكان التوقيع", "يوضع التوقيع أعلى المنشور." if desired else "يوضع التوقيع أسفل المنشور."
    elif kind == "pause":
        ch = db.get_channel(ch_id) or {}
        current = not bool(ch.get("paused", False))
        if current != desired:
            db.update_channel(ch_id, "paused", not desired)
        label, result = "تشغيل القناة", "تستمر القناة في العمل والنشر." if desired else "تتوقف القناة مؤقتاً عن المعالجة والنشر."
    elif kind == "assign":
        try:
            rtype, ch_id, item_id = target.split("~", 2)
        except ValueError:
            await callback.answer("تعيين مورد غير صالح.", show_alert=True)
            return
        info = _RESOURCE_MAP.get(rtype)
        if not info:
            await callback.answer("نوع مورد غير معروف.", show_alert=True)
            return
        if rtype == "bots" and hasattr(db, "mapper"):
            current = bool(db.mapper.is_assigned(item_id, ch_id))
        else:
            cfg = db.get_channel_config(ch_id) or {}
            current = str(item_id) in [str(x) for x in cfg.get(info["cfg_key"], [])]
        if current != desired:
            if rtype == "bots" and hasattr(db, "mapper"):
                if desired:
                    db.mapper.assign(item_id, ch_id)
                    token = db.bot_manager.get_token(item_id) if hasattr(db, "bot_manager") else ""
                    if token:
                        try:
                            await verifier.check_bot_in_channel(item_id, ch_id, force=True)
                        except Exception:
                            pass
                else:
                    db.mapper.unassign(item_id, ch_id)
            else:
                values = list(cfg.get(info["cfg_key"], []))
                if desired and str(item_id) not in [str(x) for x in values]:
                    values.append(item_id)
                elif not desired:
                    values = [x for x in values if str(x) != str(item_id)]
                db.update_channel_config(ch_id, **{info["cfg_key"]: values})
        label, result = "تعيين المورد", "سيُستخدم المورد مع هذه القناة." if desired else "لن يُستخدم المورد مع هذه القناة."
    elif kind == "session":
        item = db.get_session(target) or {}
        current = bool(item.get("enabled", True))
        if current != desired:
            db.set_session_enabled(target, desired)
        label, result = "الجلسة", "تبقى الجلسة متاحة للتشغيل." if desired else "تتوقف الجلسة عن التشغيل."
    elif kind == "ai_key":
        item = db.get_ai_key(target) or {}
        current = bool(item.get("enabled", True))
        if current != desired:
            db.set_ai_key_enabled(target, desired)
        label, result = "مفتاح الذكاء الاصطناعي", "يمكن استخدام المفتاح." if desired else "لا يُستخدم المفتاح."
    elif kind == "publishing_bot":
        item = db.get_publishing_bot(target) or {}
        current = bool(item.get("enabled", True))
        if current != desired:
            db.set_publishing_bot_enabled(target, desired)
        label, result = "بوت النشر", "يبقى البوت متاحاً للنشر." if desired else "يتوقف استخدام البوت للنشر."
    elif kind == "website":
        item = db.get_website(target) or {}
        current = bool(item.get("enabled", True))
        if current != desired:
            db.set_website_enabled(target, desired)
        label, result = "الموقع", "يبقى الموقع متاحاً للاستخدام." if desired else "يتوقف استخدام الموقع."
    else:
        await callback.answer("إعداد غير معروف.", show_alert=True)
        return
    await callback.answer(f"✅ تم {'تشغيل' if desired else 'إيقاف'} {label}.", show_alert=True)
    callback.data = f"ui_info|{kind}|{target}|{back.replace('|', '~')}"
    await ui_setting_info_menu(client, callback)
async def action_info_menu(client, callback):
    """صفحة شرح عامة للإجراءات قبل التنفيذ، مع الحفاظ على callback التنفيذي الأصلي."""
    parts = callback.data.split("|", 2)
    if len(parts) != 3:
        await callback.answer("طلب غير صالح.", show_alert=True)
        return
    _, action, payload = parts
    descriptions = {
        "testpub": ("🧪 اختبار نشر القناة", "يرسل منشور اختبار فعلياً إلى هذه القناة للتحقق من صلاحية النشر وتطبيق تنسيق القناة الحالي.", "▶️ إرسال اختبار النشر"),
        "testsrc": ("🧪 اختبار المصدر", "يفحص إمكانية الوصول إلى المصدر ويعرض نوعه وآخر رسالة متاحة والقنوات المستهدفة دون تغيير إعداداته.", "▶️ اختبار المصدر"),
        "chbotcheck": ("🤖 فحص بوت القناة", "يتحقق من وجود بوت النشر داخل القناة وصلاحياته، ثم يعرض الحالة الفعلية.", "▶️ بدء فحص البوت"),
        "test_all_channels": ("🧪 اختبار كل القنوات", "ينفذ اختبار نشر للقنوات غير المتوقفة ويعرض عدد القنوات الناجحة والفاشلة.", "▶️ اختبار كل القنوات"),
        "full_check": ("🔍 الفحص الشامل", "يفحص الجلسة والبوت والوسيطة وقنوات النشر والمصادر دون تغيير إعداداتها.", "▶️ بدء الفحص الشامل"),
        "preview": ("👁 معاينة المنشور", "يعرض تقريراً يوضح كيف ستطبق إعدادات القناة الحالية على منشور تجريبي قبل النشر.", "▶️ عرض المعاينة"),
        "clear_errors": ("🗑 مسح الأخطاء", "يمسح سجل الأخطاء المعروض في لوحة الأخطاء فقط، ولا يغيّر إعدادات النشر أو السجل التشغيلي العام.", "▶️ مسح سجل الأخطاء"),
        "stats": ("📊 الإحصائيات", "يعرض إجمالي المنشورات والقنوات والمصادر والكلمات المحظورة وتفصيل المنشورات حسب القناة.", "▶️ عرض الإحصائيات"),
        "export": ("📥 تصدير البيانات", "ينشئ ملف JSON يحتوي إعدادات وبيانات البوت الحالية ويرسله كنسخة احتياطية.", "▶️ تصدير البيانات"),
        "srcstats": ("📊 إحصائيات المصدر", "يعرض أرقام الاستلام والنشر والرفض والتجاهل والتكرار والأخطاء وآخر حدث للمصدر.", "▶️ عرض إحصائيات المصدر"),
        "srclog": ("📋 سجل المصدر", "يعرض آخر العمليات المسجلة لهذا المصدر مع الوقت ونوع الحدث ورقم الرسالة والسبب.", "▶️ عرض سجل المصدر"),
        "session_test": ("🧪 اختبار الجلسة", "يتحقق من اتصال جلسة Telegram المحددة دون تغيير إعداد تفعيلها.", "▶️ اختبار الجلسة"),
        "ai_test": ("🧪 اختبار مفتاح AI", "يتحقق من اتصال مزود الذكاء الاصطناعي للمفتاح المحدد دون تغيير حالته.", "▶️ اختبار المفتاح"),
        "bot_test": ("🧪 اختبار بوت النشر", "يتحقق من توكن بوت النشر واتصاله، مع تحديث إحصائية الاستخدام عند نجاح الاختبار وفق الدالة الأصلية.", "▶️ اختبار البوت"),
        "bot_verify": ("🔍 فحص قنوات البوت", "يفحص صلاحيات بوت النشر في القنوات المرتبطة به ويعرض عدد القنوات الموثوقة وغير الموثوقة.", "▶️ فحص القنوات"),
        "web_test": ("🧪 اختبار الموقع", "يجلب الموقع المحدد ويتحقق من استجابته ويعرض رمز HTTP أو عدد الأحرف عند النجاح.", "▶️ اختبار الموقع"),
        "test": ("🧪 اختبار القناة", "ينفذ اختباراً للقناة للتحقق من إمكانية النشر.", "▶️ تنفيذ الاختبار"),
        "import": ("📥 استيراد البيانات", "يستورد إعدادات البوت من ملف JSON مدعوم. ⚠️ سيتم استبدال أو تحديث البيانات وفق سلوك الاستيراد الحالي، وسيبقى انتظار الملف عبر نفس MessageHandler وuser_state.", "📥 متابعة الاستيراد"),
        "copysrc": ("📋 نسخ إعدادات المصدر", "يحفظ إعدادات هذا المصدر في user_state لتتمكن من لصقها في مصدر آخر أو عدة مصادر. لن يبدأ النسخ إلى مصادر أخرى من هذه الصفحة.", "📋 متابعة نسخ الإعدادات"),
        "pastesrc": ("📋 لصق إعدادات المصدر", "يلصق الإعدادات المنسوخة في هذا المصدر باستخدام user_state الحالي ثم يعرض نتيجة العملية الأصلية.", "📋 تنفيذ اللصق"),
        "bulkpastesrc": ("📋 لصق الإعدادات لعدة مصادر", "يفتح نفس MessageHandler الحالي لانتظار قائمة المصادر، مع الحفاظ على user_state وآلية الإدخال الأصلية.", "📋 متابعة اللصق المتعدد"),
        "restore": ("♻️ استعادة العنصر", "يعيد العنصر من سلة المحذوفات إلى حالته السابقة. سيُستخدم مسار الاستعادة الأصلي ثم تظهر نتيجة العملية وتعود إلى السلة.", "♻️ متابعة الاستعادة"),
        "delete_session": ("🗑 حذف الجلسة", "ينقل الجلسة إلى سلة المحذوفات إذا لم تكن مستخدمة. سيجري فحص dependencies الأصلي قبل التنفيذ ولن يتم تجاوز تحذير الاستخدام.", "🗑 متابعة حذف الجلسة"),
        "delete_ai": ("🗑 حذف مفتاح AI", "ينقل مفتاح AI إلى سلة المحذوفات إذا لم يكن مستخدماً. سيبقى فحص dependencies الأصلي كما هو.", "🗑 متابعة حذف المفتاح"),
        "delete_bot": ("🗑 حذف بوت النشر", "ينقل بوت النشر إلى سلة المحذوفات إذا لم يكن مرتبطاً بقنوات. سيبقى فحص dependencies الأصلي كما هو.", "🗑 متابعة حذف البوت"),
        "delete_web": ("🗑 حذف الموقع", "ينقل الموقع إلى سلة المحذوفات وفق سلوكه الحالي، مع الحفاظ على أي فحص dependencies موجود في الدالة الأصلية.", "🗑 متابعة حذف الموقع"),
        "delete_channel": ("🗑 حذف قناة النشر", "يفتح نفس قائمة اختيار القناة ثم يبقي زر التأكيد الحالي قبل الحذف الفعلي.", "🗑 متابعة حذف القناة"),
        "purge": ("🗑 حذف المنشورات", "يفتح صفحة اختيار/تأكيد نوع المنشورات ثم يحافظ على تأكيد الحذف الحالي قبل التنفيذ.", "🗑 متابعة حذف المنشورات"),
        "trash_permdel": ("🗑 الحذف النهائي من السلة", "يحذف العنصر نهائياً من سلة المحذوفات ولا يمكن التراجع عن العملية. ستبقى صفحة التأكيد الحالية.", "🗑 متابعة الحذف النهائي"),
        "trash_empty": ("🗑 تفريغ سلة المحذوفات", "يحذف جميع عناصر السلة نهائياً ولا يمكن التراجع. ستبقى صفحة التأكيد الحالية.", "🗑 متابعة تفريغ السلة"),
    }
    title, desc, button = descriptions.get(action, ("ℹ️ شرح العملية", "راجع وظيفة العملية قبل تنفيذها.", "▶️ تنفيذ العملية"))
    execute_token, back_token = (payload.split("^", 1) + [None])[:2] if "^" in payload else (payload, None)
    back = back_token.replace("~", "|") if back_token else (_peek_prev_back(callback) or "main_menu")
    text = f"{title}\n\nوظيفة العملية:\n{desc}\n\nلن يتم التنفيذ حتى تضغط زر التنفيذ."
    await safe_edit(callback, text, InlineKeyboardMarkup([
        [InlineKeyboardButton(button, callback_data=f"ui_action_exec|{action}|{execute_token}^{back.replace('|', '~')}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=back)],
    ]))


async def action_execute_menu(client, callback):
    """ينفذ Action محدداً عبر دالته الأصلية، ثم يعرض نتيجتها أو يعيد صفحة المورد."""
    parts = callback.data.split("|", 2)
    if len(parts) != 3 or "^" not in parts[2]:
        await callback.answer("طلب تنفيذ غير صالح.", show_alert=True)
        return
    _, action, payload = parts
    execute_token, back_token = payload.split("^", 1)
    execute_data = execute_token.replace("~", "|")
    back_data = back_token.replace("~", "|")
    executors = {
        "testpub": test_publish_channel,
        "testsrc": test_source,
        "chbotcheck": channel_bot_check,
        "test_all_channels": test_all_channels,
        "full_check": full_check_menu,
        "preview": preview_post,
        "clear_errors": clear_errors,
        "stats": show_stats,
        "export": export_callback,
        "srcstats": source_stats_menu,
        "srclog": source_log_menu,
        "session_test": test_session,
        "ai_test": test_ai_key,
        "bot_test": test_bot,
        "bot_verify": verify_bot_channels,
        "web_test": test_website,
        "import": import_callback,
        "copysrc": copy_source_settings_prompt,
        "pastesrc": paste_source_settings,
        "bulkpastesrc": bulk_paste_source_prompt,
        "restore": trash_restore_item,
        "delete_session": delete_session_with_deps,
        "delete_ai": delete_ai_key_with_deps,
        "delete_bot": delete_bot_with_deps,
        "delete_web": delete_website_with_deps,
        "delete_channel": delete_channel_prompt,
        "purge": purge_published_prompt,
        "trash_permdel": trash_permanent_delete_prompt,
        "trash_empty": trash_empty_prompt,
    }
    if action not in executors:
        await callback.answer("هذا الإجراء غير متاح.", show_alert=True)
        return
    callback.data = execute_data
    await executors[action](client, callback)
    return_handlers = {
        "testpub": test_settings_menu,
        "export": backup_menu,
        "session_test": show_session_settings,
        "ai_test": show_ai_key_settings,
        "bot_test": show_bot_settings,
        "web_test": show_website_settings,
    }
    if action in return_handlers:
        callback.data = back_data
        await return_handlers[action](client, callback)



def register_bot_handlers(app: Client):
    app.add_handler(MessageHandler(start, filters.command("start")))
    app.add_handler(MessageHandler(handle_import, filters.document))
    register_blogger_handlers(app)

    async def callback_dispatcher(client, callback):
        data = callback.data
        if str(data).startswith("ui_ctx|"):
            expanded = _expand_ui_callback_data(data)
            if expanded is None:
                await callback.answer("انتهت صلاحية هذا الزر. افتح القائمة من جديد.", show_alert=True)
                return
            data = expanded
            callback.data = expanded

        if data.startswith("section_menu|"):
            await section_menu(client, callback)
            return
        if data.startswith(("news:", "sports:", "blogger:")):
            await section_control_callback(client, callback)
            return
        if data == "main_menu":
            await safe_edit(callback, "القائمة الرئيسية:", main_keyboard)
        elif data == "back_stack":
            previous = _back_step(callback)
            if previous is None:
                await callback.answer("لا توجد صفحة سابقة في هذه الجلسة.", show_alert=True)
                return
            callback.data = previous
            if str(previous).startswith("ui_ctx|"):
                expanded = _expand_ui_callback_data(previous)
                if expanded is None:
                    await callback.answer("انتهت صلاحية هذا الزر. افتح القائمة من جديد.", show_alert=True)
                    return
                callback.data = expanded
            await callback_dispatcher(client, callback)
        else:
            _push_back(callback)
        if data.startswith("ui_info|"):
            await ui_setting_info_menu(client, callback)
        elif data.startswith("ui_set|"):
            await ui_setting_set(client, callback)
        elif data.startswith("ui_action_exec|"):
            await action_execute_menu(client, callback)
        elif data.startswith("ui_action|"):
            await action_info_menu(client, callback)
        elif data in BLOGGER_CALLBACKS:
            await BLOGGER_CALLBACKS[data](client, callback)
        elif data.startswith("togglebold_"):
            ch_id = data.rsplit("_", 1)[1]
            callback.data = f"ui_info|bold|{ch_id}|postset_{ch_id}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("toggle_short_posts|"):
            ch_id = data.split("|", 1)[1]
            callback.data = f"ui_info|short_posts|{ch_id}|postset_{ch_id}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("ch_titlequote_"):
            ch_id = data.rsplit("_", 1)[1]
            callback.data = f"ui_info|title_quote|{ch_id}|quotemenu_{ch_id}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("ch_sigquote_"):
            ch_id = data.rsplit("_", 1)[1]
            callback.data = f"ui_info|signature_quote|{ch_id}|quotemenu_{ch_id}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("ch_preview_"):
            ch_id = data.rsplit("_", 1)[1]
            callback.data = f"ui_info|preview|{ch_id}|postset_{ch_id}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("blogger_"):
            from modules.blogger.ui import DYNAMIC_PREFIXES
            matched = False
            for prefix, handler_name in DYNAMIC_PREFIXES.items():
                if data.startswith(prefix):
                    import importlib
                    mod = importlib.import_module("modules.blogger.ui")
                    handler = getattr(mod, handler_name)
                    await handler(client, callback)
                    matched = True
                    break
            if not matched:
                await callback.answer("أمر غير معروف.")
        elif data == "menu_channels":
            await menu_channels(client, callback)
        elif data.startswith("ch_extended_"):
            await channel_extended_settings(client, callback)
        elif data.startswith("ch_titlequote_"):
            await toggle_channel_title_quote(client, callback)
        elif data.startswith("ch_sigquote_"):
            await toggle_channel_signature_quote(client, callback)
        elif data.startswith("ch_preview_"):
            await toggle_channel_preview(client, callback)
        elif data.startswith("postset_"):
            await post_settings_menu(client, callback)
        elif data.startswith("srcset_"):
            await source_settings_channel_menu(client, callback)
        elif data.startswith("tails_"):
            await tail_settings_menu(client, callback)
        elif data.startswith("testset_"):
            await test_settings_menu(client, callback)
        elif data.startswith("preview_"):
            ch_id = data.split("_", 1)[1]
            callback.data = f"ui_action|preview|preview_{ch_id}^testset_{ch_id}"
            await action_info_menu(client, callback)
        elif data.startswith("tailtoggle_"):
            ch_id = data.rsplit("_", 1)[1]
            callback.data = f"ui_info|tail|{ch_id}|tails_{ch_id}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("tailmintoggle_"):
            ch_id = data.rsplit("_", 1)[1]
            callback.data = f"ui_info|tail_min|{ch_id}|tails_{ch_id}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("tailpos_"):
            ch_id = data.rsplit("_", 1)[1]
            callback.data = f"ui_info|tail_pos|{ch_id}|tails_{ch_id}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("genset_copy_"):
            await general_settings_copy(client, callback)
        elif data.startswith("genset_paste_confirm_"):
            await general_settings_paste_confirm(client, callback)
        elif data.startswith("genset_paste_"):
            await general_settings_paste(client, callback)
        elif data.startswith("genset_reset_confirm_"):
            await general_settings_reset_confirm(client, callback)
        elif data.startswith("genset_reset_"):
            await general_settings_reset(client, callback)
        elif data.startswith("genset_summary_"):
            await general_settings_summary(client, callback)
        elif data.startswith("genset_"):
            await general_settings_menu(client, callback)
        elif data.startswith("sysset_"):
            await system_channel_menu(client, callback)
        elif data == "system_menu":
            await system_menu(client, callback)
        elif data.startswith("purgepage_"):
            await purge_published_menu(client, callback)
        elif data.startswith("chwordadd|"):
            await channel_add_blocked_word_prompt(client, callback)
        elif data.startswith("chworddelidx|"):
            await confirm_channel_del_blocked_word(client, callback)
        elif data.startswith("chworddel|"):
            await channel_del_blocked_word_prompt(client, callback)
        elif data.startswith("chwords|"):
            await channel_blocked_words_menu(client, callback)
        elif data.startswith("chlinks|"):
            await channel_links_menu(client, callback)
        elif data.startswith("chbotcheck|"):
            ch_id = data.split("|", 1)[1]
            callback.data = f"ui_action|chbotcheck|chbotcheck~{ch_id}^ch_{ch_id}"
            await action_info_menu(client, callback)
        elif data.startswith("chlinktg|") or data.startswith("chlinktguser|") or data.startswith("chlinkweb|"):
            prefix, ch_id = data.split("|", 1)
            kind = {
                "chlinktg": "link_remove_tg",
                "chlinktguser": "link_remove_tg_user",
                "chlinkweb": "link_remove_web",
            }[prefix]
            callback.data = f"ui_info|{kind}|{ch_id}|chlinks~{ch_id}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("chdeltermadd|"):
            await channel_add_delete_term_prompt(client, callback)
        elif data.startswith("chdeltermdel|"):
            await channel_del_delete_term_prompt(client, callback)
        elif data.startswith("chdelterms|"):
            await channel_delete_terms_menu(client, callback)
        elif data.startswith("ch_"):
            await channel_settings(client, callback)
        elif data == "add_channel":
            await add_channel_prompt(client, callback)
        elif data.startswith("togglebold_"):
            await toggle_channel_bold(client, callback)
        elif data.startswith("quotemenu_"):
            await channel_quote_menu(client, callback)
        elif data.startswith("toggleqtype|"):
            _, ch_id, qtype = data.split("|", 2)
            callback.data = f"ui_info|quote_type|{ch_id}~{qtype}|quotemenu_{ch_id}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("togglequote_"):
            # Compatibility/navigation alias: this opens the quote menu and is not a Boolean setter.
            await toggle_channel_quote(client, callback)
        elif data.startswith("hashtags_"):
            await channel_hashtags_menu(client, callback)
        elif data.startswith("addhashtags_"):
            await add_channel_hashtags_prompt(client, callback)
        elif data.startswith("delhashtags_"):
            await del_channel_hashtags_prompt(client, callback)
        elif data.startswith("testpub_"):
            ch_id = data.split("_", 1)[1]
            callback.data = f"ui_action|testpub|testpub_{ch_id}^testset_{ch_id}"
            await action_info_menu(client, callback)
        elif data.startswith("purgepub|"):
            execute_token = data.replace("|", "~")
            _, ch_id, kind = data.split("|", 2)
            callback.data = f"ui_action|purge|{execute_token}^purgepage_{ch_id}"
            await action_info_menu(client, callback)
        elif data.startswith("confirmpurge|"):
            await confirm_purge_published(client, callback)
        elif data == "toggle_maintenance" or data.startswith("toggle_maintenance|"):
            ch_id = data.split("|", 1)[1] if "|" in data else None
            back = f"ops_menu~{ch_id}" if ch_id else "ops_menu"
            callback.data = f"ui_info|maintenance|global|{back}"
            await ui_setting_info_menu(client, callback)
        elif data == "toggle_short_posts" or data.startswith("toggle_short_posts|"):
            ch_id = data.split("|", 1)[1] if "|" in data else "global"
            back = f"ops_menu~{ch_id}" if ch_id != "global" else "ops_menu"
            callback.data = f"ui_info|short_posts|{ch_id}|{back}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("toggle_notif_"):
            key = data.split("toggle_notif_", 1)[1].split("|", 1)[0]
            notif_ch = data.split("|", 1)[1] if "|" in data else None
            callback.data = f"ui_info|notification|{key}|notifications_menu~{notif_ch}" if notif_ch else f"ui_info|notification|{key}|notifications_menu"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("legacy_toggle_notif_"):
            key = data.split("legacy_toggle_notif_", 1)[1]
            notif_ch = data.split("|", 1)[1] if "|" in data else None
            if key in db.NOTIFICATION_TYPES:
                settings = db.get_notification_settings()
                db.set_notification_setting(key, not settings.get(key, True))
                await callback.answer("تم التبديل.")
                callback.data = f"notifications_menu|{notif_ch}" if notif_ch else "notifications_menu"
                await notifications_menu(client, callback)
            else:
                await callback.answer("غير معروف.")
        elif data.startswith("toggle_assign_"):
            parts = data.split("_", 4)
            if len(parts) == 5:
                _, _, rtype, ch_id, item_id = parts
                callback.data = f"ui_info|assign|{rtype}~{ch_id}~{item_id}|assign_{rtype}_{ch_id}"
                await ui_setting_info_menu(client, callback)
            else:
                await toggle_assign_resource(client, callback)
        elif data.startswith("toggle_"):
            ch_id = data.split("_", 1)[1]
            callback.data = f"ui_info|pause|{ch_id}|ch_{ch_id}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("delchannel_"):
            ch_id = data.split("_", 1)[1]
            callback.data = f"ui_action|delete_channel|delchannel_{ch_id}^genset_{ch_id}"
            await action_info_menu(client, callback)
        elif data.startswith("confirm_del_"):
            await confirm_delete_channel(client, callback)
        elif data.startswith("tailmenu_"):
            await tail_menu(client, callback)
        elif data.startswith("edittail_"):
            await edit_tail_prompt(client, callback)
        elif data.startswith("deltail_"):
            await delete_tail(client, callback)
        elif data == "menu_public_src":
            await menu_public_sources(client, callback)
        elif data == "add_public_src":
            await add_public_src_prompt(client, callback)
        elif data == "del_public_src":
            await del_public_src_prompt(client, callback)
        elif data.startswith("del_pub_idx_"):
            await confirm_del_public_src(client, callback)
        elif data == "menu_blocked":
            await menu_blocked_words(client, callback)
        elif data == "add_blocked_word":
            await add_blocked_word_prompt(client, callback)
        elif data == "del_blocked_word":
            await del_blocked_word_prompt(client, callback)
        elif data.startswith("delword_idx_"):
            await confirm_del_blocked_word(client, callback)
        elif data.startswith("specsrc_"):
            await manage_special_sources(client, callback)
        elif data.startswith("addspecsrc_"):
            await add_special_source_prompt(client, callback)
        elif data.startswith("delspecsrc_"):
            await delete_special_source_prompt(client, callback)
        elif data.startswith("confdelspec_"):
            await confirm_delete_special_source(client, callback)
        elif data.startswith("srcset|"):
            await source_settings_menu(client, callback)
        elif data.startswith("togglesource|"):
            _, source_id, back = data.split("|", 2)
            back_token = back.replace("|", "~")
            callback.data = f"ui_info|source_enabled|{source_id}|srcset~{source_id}~{back_token}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("toggleemoji|"):
            _, source_id, back = data.split("|", 2)
            back_token = back.replace("|", "~")
            callback.data = f"ui_info|source_emoji|{source_id}|srcset~{source_id}~{back_token}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("contentmenu|"):
            await source_content_menu(client, callback)
        elif data.startswith("togglectype|"):
            _, source_id, ctype, back = data.split("|", 3)
            back_token = back.replace("|", "~")
            callback.data = f"ui_info|source_content|{source_id}~{ctype}|contentmenu~{source_id}~{back_token}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("clean_src|"):
            await source_cleanup_menu(client, callback)
        elif data.startswith("addclean|"):
            await add_source_cleanup_prompt(client, callback)
        elif data.startswith("delclean|"):
            await del_source_cleanup_prompt(client, callback)
        elif data == "global_clean":
            await global_cleanup_menu(client, callback)
        elif data == "addglobalclean":
            await add_global_cleanup_prompt(client, callback)
        elif data == "delglobalclean":
            await del_global_cleanup_prompt(client, callback)
        elif data.startswith("speedmenu_"):
            await channel_speed_menu(client, callback)
        elif data.startswith("setspeed|"):
            await set_channel_speed(client, callback)
        elif data.startswith("customspeed_"):
            await custom_channel_speed_prompt(client, callback)
        elif data.startswith("srcstats|"):
            _, source_id, back = data.split("|", 2)
            execute_token = data.replace("|", "~")
            back_token = f"srcset~{source_id}~{back.replace('|', '~')}"
            callback.data = f"ui_action|srcstats|{execute_token}^{back_token}"
            await action_info_menu(client, callback)
        elif data.startswith("srclog|"):
            _, source_id, back = data.split("|", 2)
            execute_token = data.replace("|", "~")
            back_token = f"srcset~{source_id}~{back.replace('|', '~')}"
            callback.data = f"ui_action|srclog|{execute_token}^{back_token}"
            await action_info_menu(client, callback)
        elif data.startswith("testsrc|"):
            _, source_id, back = data.split("|", 2)
            execute_token = data.replace("|", "~")
            back_token = f"srcset~{source_id}~{back.replace('|', '~')}"
            callback.data = f"ui_action|testsrc|{execute_token}^{back_token}"
            await action_info_menu(client, callback)
        elif data.startswith("copysrc|"):
            _, source_id, back = data.split("|", 2)
            execute_token = data.replace("|", "~")
            back_token = f"srcset~{source_id}~{back.replace('|', '~')}"
            callback.data = f"ui_action|copysrc|{execute_token}^{back_token}"
            await action_info_menu(client, callback)
        elif data.startswith("pastesrc|"):
            _, source_id, back = data.split("|", 2)
            execute_token = data.replace("|", "~")
            back_token = f"srcset~{source_id}~{back.replace('|', '~')}"
            callback.data = f"ui_action|pastesrc|{execute_token}^{back_token}"
            await action_info_menu(client, callback)
        elif data.startswith("bulkpastesrc|"):
            _, source_id, back = data.split("|", 2)
            execute_token = data.replace("|", "~")
            back_token = f"srcset~{source_id}~{back.replace('|', '~')}"
            callback.data = f"ui_action|bulkpastesrc|{execute_token}^{back_token}"
            await action_info_menu(client, callback)
        elif data == "system_status" or data.startswith("system_status|"):
            await system_status_menu(client, callback)
        elif data == "full_check" or data.startswith("full_check|"):
            ch_id = data.split("|", 1)[1] if "|" in data else None
            execute_token = data.replace("|", "~")
            back_token = f"system_status~{ch_id}" if ch_id else "system_status"
            callback.data = f"ui_action|full_check|{execute_token}^{back_token}"
            await action_info_menu(client, callback)
        elif data == "ops_menu" or data.startswith("ops_menu|"):
            await operations_menu(client, callback)
        elif data == "errors_menu" or data.startswith("errors_menu|"):
            await errors_menu(client, callback)
        elif data == "clear_errors" or data.startswith("clear_errors|"):
            ch_id = data.split("|", 1)[1] if "|" in data else None
            execute_token = data.replace("|", "~")
            back_token = f"errors_menu~{ch_id}" if ch_id else "errors_menu"
            callback.data = f"ui_action|clear_errors|{execute_token}^{back_token}"
            await action_info_menu(client, callback)
        elif data == "named_backup_prompt":
            await named_backup_prompt(client, callback)
        elif data == "test_all_channels" or data.startswith("test_all_channels|"):
            ch_id = data.split("|", 1)[1] if "|" in data else None
            execute_token = data.replace("|", "~")
            back_token = f"ops_menu~{ch_id}" if ch_id else "ops_menu"
            callback.data = f"ui_action|test_all_channels|{execute_token}^{back_token}"
            await action_info_menu(client, callback)
        elif data == "stats":
            callback.data = "ui_action|stats|stats^main_menu"
            await action_info_menu(client, callback)
        elif data == "backup_menu":
            await backup_menu(client, callback)
        elif data == "export_data":
            callback.data = "ui_action|export|export_data^backup_menu"
            await action_info_menu(client, callback)
        elif data == "import_data":
            callback.data = "ui_action|import|import_data^backup_menu"
            await action_info_menu(client, callback)
        elif data == "log_menu" or data.startswith("log_menu|"):
            await log_management_menu(client, callback)
        elif data.startswith("log_view"):
            await view_bot_log(client, callback)
        elif data.startswith("log_refresh"):
            await view_bot_log(client, callback)
        elif data.startswith("log_size"):
            await show_log_size(client, callback)
        elif data.startswith("log_clear_prompt"):
            await clear_log_prompt(client, callback)
        elif data.startswith("log_clear_confirm"):
            await confirm_clear_log(client, callback)
        # Multi-Bot Expansion: Secrets
        elif data == "secrets_menu":
            await secrets_menu(client, callback)
        elif data == "sessions_list":
            await sessions_list_menu(client, callback)
        elif data == "session_add":
            await add_session_prompt(client, callback)
        elif data.startswith("session_show_"):
            await show_session_settings(client, callback)
        elif data.startswith("session_toggle_"):
            sid = data.split("session_toggle_", 1)[1]
            callback.data = f"ui_info|session|{sid}|session_show_{sid}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("session_delete_"):
            sid = data.split("session_delete_", 1)[1]
            callback.data = f"ui_action|delete_session|session_delete_{sid}^session_show_{sid}"
            await action_info_menu(client, callback)
        elif data.startswith("session_test_"):
            sid = data.split("session_test_", 1)[1]
            callback.data = f"ui_action|session_test|session_test_{sid}^session_show_{sid}"
            await action_info_menu(client, callback)
        elif data == "ai_list":
            await ai_list_menu(client, callback)
        elif data == "ai_add":
            await add_ai_key_prompt(client, callback)
        elif data.startswith("ai_show_"):
            await show_ai_key_settings(client, callback)
        elif data.startswith("ai_toggle_"):
            kid = data.split("ai_toggle_", 1)[1]
            callback.data = f"ui_info|ai_key|{kid}|ai_show_{kid}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("ai_delete_"):
            kid = data.split("ai_delete_", 1)[1]
            callback.data = f"ui_action|delete_ai|ai_delete_{kid}^ai_show_{kid}"
            await action_info_menu(client, callback)
        elif data.startswith("ai_test_"):
            kid = data.split("ai_test_", 1)[1]
            callback.data = f"ui_action|ai_test|ai_test_{kid}^ai_show_{kid}"
            await action_info_menu(client, callback)
        elif data == "bots_list":
            await bots_list_menu(client, callback)
        elif data == "bot_add":
            await add_bot_prompt(client, callback)
        elif data.startswith("bot_rename_"):
            await rename_bot_prompt(client, callback)
        elif data.startswith("bot_verify_"):
            bid = data.split("bot_verify_", 1)[1]
            callback.data = f"ui_action|bot_verify|bot_verify_{bid}^bot_show_{bid}"
            await action_info_menu(client, callback)
        elif data.startswith("bot_show_"):
            await show_bot_settings(client, callback)
        elif data.startswith("bot_toggle_"):
            bid = data.split("bot_toggle_", 1)[1]
            callback.data = f"ui_info|publishing_bot|{bid}|bot_show_{bid}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("bot_delete_"):
            bid = data.split("bot_delete_", 1)[1]
            callback.data = f"ui_action|delete_bot|bot_delete_{bid}^bot_show_{bid}"
            await action_info_menu(client, callback)
        elif data.startswith("bot_test_"):
            bid = data.split("bot_test_", 1)[1]
            callback.data = f"ui_action|bot_test|bot_test_{bid}^bot_show_{bid}"
            await action_info_menu(client, callback)
        elif data == "web_list":
            await web_list_menu(client, callback)
        elif data == "web_add":
            await add_website_prompt(client, callback)
        elif data.startswith("web_show_"):
            await show_website_settings(client, callback)
        elif data.startswith("web_toggle_"):
            wid = data.split("web_toggle_", 1)[1]
            callback.data = f"ui_info|website|{wid}|web_show_{wid}"
            await ui_setting_info_menu(client, callback)
        elif data.startswith("web_edit_"):
            await edit_website_prompt(client, callback)
        elif data.startswith("web_delete_"):
            wid = data.split("web_delete_", 1)[1]
            callback.data = f"ui_action|delete_web|web_delete_{wid}^web_show_{wid}"
            await action_info_menu(client, callback)
        elif data.startswith("web_test_"):
            wid = data.split("web_test_", 1)[1]
            callback.data = f"ui_action|web_test|web_test_{wid}^web_show_{wid}"
            await action_info_menu(client, callback)
        elif data == "trash_menu":
            await trash_menu(client, callback)
        elif data.startswith("trash_restore_"):
            tid = data.split("trash_restore_", 1)[1]
            callback.data = f"ui_action|restore|trash_restore_{tid}^trash_menu"
            await action_info_menu(client, callback)
        elif data.startswith("trash_permdel_"):
            tid = data.split("trash_permdel_", 1)[1]
            callback.data = f"ui_action|trash_permdel|trash_permdel_{tid}^trash_menu"
            await action_info_menu(client, callback)
        elif data.startswith("trash_permconfirm_"):
            await trash_permanent_delete_confirm(client, callback)
        elif data == "trash_empty_prompt":
            callback.data = "ui_action|trash_empty|trash_empty_prompt^trash_menu"
            await action_info_menu(client, callback)
        elif data == "trash_empty_confirm":
            await trash_empty_confirm(client, callback)
        elif data == "notifications_menu" or data.startswith("notifications_menu|"):
            await notifications_menu(client, callback)
        elif data.startswith("toggle_assign_"):
            await toggle_assign_resource(client, callback)
        elif data.startswith("assign_"):
            await assign_resource_menu(client, callback)
        else:
            await callback.answer("غير معروف.")

    app.add_handler(CallbackQueryHandler(callback_dispatcher))
    app.add_handler(MessageHandler(handle_text_input, filters.text & filters.private))

def register_user_handlers(app: Client):
    # نلتقط كل رسائل حساب المستخدم ثم نفلتر داخل user_message_handler
    # هذا يساعدنا نعرف هل SESSION_STRING يلتقط المصادر العامة أو لا
    app.add_handler(MessageHandler(user_message_handler))

def register_middle_handlers(app: Client):
    app.add_handler(MessageHandler(middle_channel_handler, filters.chat(config.MIDDLE_CHANNEL)))

NOTIFICATION_CHECK_INTERVAL = 300  # 5 دقائق
NOTIFICATION_COOLDOWN = 3600  # إعادة التنبيه بعد ساعة


async def notify_admins_custom(text, check_key):
    """إرسال إشعار لكل المشرفين مع مراعاة cooldown."""
    now = time.time()
    last_ts = _last_alert_ts.get(check_key, 0)
    if now - last_ts < NOTIFICATION_COOLDOWN:
        return
    _last_alert_ts[check_key] = now
    for uid in config.ADMINS:
        try:
            await bot_client.send_message(uid, text)
        except Exception as e:
            logger.warning(f"فشل إرسال إشعار {check_key} للمشرف {uid}: {e}")


async def _check_sessions_health():
    """التأكد من أن Sessions شغالة."""
    for s in db.get_all_sessions():
        status = s.get("status", "")
        enabled = s.get("enabled", True)
        if not enabled or status in ("stopped", "error"):
            await notify_admins_custom(
                f"⚠️ **Session متوقفة:** `{s.get('name', s['id'])}`\n"
                f"الحالة: {status}\n"
                f"يرجى مراجعة إدارة الجلسات.",
                "session_stopped"
            )


async def _check_ai_key_errors():
    """التأكد من أن مفاتيح AI سليمة."""
    for k in db.get_all_ai_keys():
        stats = db.get_ai_key_stats(k["id"])
        errs = stats.get("error_count", 0)
        enabled = stats.get("enabled", True)
        if not enabled or errs > 3:
            await notify_admins_custom(
                f"⚠️ **مفتاح AI به مشكلة:** `{k.get('name', k['id'])}`\n"
                f"الأخطاء: {errs}\n"
                f"المزوّد: {stats.get('provider', '?')}",
                "ai_key_error"
            )


async def _check_sources_stopped():
    """التأكد من أن المصادر العامة ليست متوقفة."""
    for src in db.get_all_public_sources_with_meta():
        sid = src.get("id") or src.get("_id")
        if sid is None:
            continue
        meta = db.get_source_meta(sid)
        paused = meta.get("paused", False)
        if paused:
            await notify_admins_custom(
                f"⚠️ **مصدر متوقف:** `{meta.get('name', sid)}`\n"
                f"تم إيقافه يدوياً أو تلقائياً.",
                "source_stopped"
            )


async def _check_channels_idle():
    """التأكد من أن القنوات تنشر بانتظام."""
    now = time.time()
    for ch in db.get_all_channels():
        if ch.get("paused", False):
            continue
        cid = ch["id"]
        try:
            with db.lock:
                data = db._read()
            pm = data.get("published_messages", {}).get(str(cid), {})
            latest_ts = 0
            for msgs in pm.values():
                if isinstance(msgs, list) and msgs:
                    last_msg = msgs[-1]
                    if isinstance(last_msg, dict):
                        latest_ts = max(latest_ts, last_msg.get("ts", 0))
            if latest_ts and now - latest_ts > 3600:
                name = ch.get("name", cid)
                await notify_admins_custom(
                    f"⏰ **قناة لم تنشر منذ أكثر من ساعة:** `{name}`\n"
                    f"آخر نشر: {time.strftime('%Y-%m-%d %H:%M', time.localtime(latest_ts))}",
                    "channel_idle_hour"
                )
        except Exception:
            pass


async def _check_backup_fresh():
    """التأكد من أن النسخ الاحتياطي حديث."""
    try:
        backups = db.get_named_backups()
        if not backups:
            await notify_admins_custom(
                "⚠️ **لا توجد نسخ احتياطية!**\n"
                "يرجى إنشاء نسخة احتياطية قريباً.",
                "backup_failed"
            )
            return
        last = backups[-1]
        last_ts = last.get("ts", 0)
        now = time.time()
        if now - last_ts > 86400:  # أكثر من يوم
            await notify_admins_custom(
                f"⚠️ **آخر نسخة احتياطية قديمة:** {time.strftime('%Y-%m-%d %H:%M', time.localtime(last_ts))}\n"
                f"يرجى إنشاء نسخة احتياطية جديدة.",
                "backup_failed"
            )
    except Exception as e:
        await notify_admins_custom(
            f"⚠️ **فشل التحقق من النسخ الاحتياطية:** {e}",
            "backup_failed"
        )


async def _check_db_health():
    """التأكد من سلامة قاعدة البيانات."""
    try:
        result = db.verify_or_recover_storage()
        if not result.get("ok"):
            msg = result.get("message", "خطأ غير معروف في قاعدة البيانات")
            await notify_admins_custom(
                f"❗ **مشكلة بقاعدة البيانات:** {msg}",
                "db_issue"
            )
    except Exception as e:
        await notify_admins_custom(
            f"❗ **استثناء أثناء فحص قاعدة البيانات:** {e}",
            "db_issue"
        )


async def notification_checks_loop():
    """الحلقة الخلفية لفحص التنبيهات كل 5 دقائق."""
    CHECKS = [
        ("session_stopped", _check_sessions_health),
        ("ai_key_error", _check_ai_key_errors),
        ("source_stopped", _check_sources_stopped),
        ("channel_idle_hour", _check_channels_idle),
        ("backup_failed", _check_backup_fresh),
        ("db_issue", _check_db_health),
    ]
    await asyncio.sleep(60)  # انتظار دقيقة بعد بدء البوت
    while True:
        try:
            settings = db.get_notification_settings()
            for key, check_fn in CHECKS:
                if settings.get(key, True):
                    try:
                        await check_fn()
                    except Exception as e:
                        logger.warning(f"خطأ في فحص {key}: {e}")
        except Exception as e:
            logger.warning(f"خطأ في حلقة التنبيهات: {e}")
        await asyncio.sleep(NOTIFICATION_CHECK_INTERVAL)


BOT_VERIFY_INTERVAL = 3600  # إعادة التحقق كل ساعة


async def _auto_sync_channel_info(ch_id, ch_name=""):
    """مزامنة معلومات القناة مع Telegram."""
    try:
        chat = await bot_client.get_chat(int(ch_id))
        title = getattr(chat, "title", "") or ""
        username = getattr(chat, "username", "") or ""
        link = getattr(chat, "invite_link", "") or ""
        if title:
            old = db.get_channel(ch_id) or {}
            updates = {}
            if old.get("name") != title:
                updates["name"] = title
            if old.get("username") != username:
                updates["username"] = username
            if old.get("link") != link:
                updates["link"] = link
            if updates:
                for k, v in updates.items():
                    db.update_channel(ch_id, k, v)
                logger.info(f"🔄 تم تحديث معلومات القناة {ch_id}: {updates}")
    except Exception as e:
        logger.warning(f"⚠️ فشل مزامنة القناة {ch_id}: {e}")


async def _auto_detect_bot_changes(b, old_ver, new_ver, ch_id, ch_name):
    """كشف التغييرات في حالة البوت وإبلاغ المشرفين."""
    if not old_ver or not new_ver:
        return
    old_ok = old_ver.get("verified", False) and old_ver.get("can_post", False)
    new_ok = new_ver.get("verified", False) and new_ver.get("can_post", False)
    if old_ok and not new_ok:
        msg = (f"⚠️ **تغيير في صلاحية البوت**\n\n"
               f"🤖 {b.get('name', '')}\n"
               f"📢 {ch_name}\n"
               f"الحالة السابقة: ✅ موثوق\n"
               f"الحالة الجديدة: ❌ غير موثوق\n"
               f"السبب: {new_ver.get('status', 'غير معروف')}")
        await notify_admins(msg)
    elif not old_ok and new_ok:
        msg = (f"✅ **تمت استعادة صلاحية البوت**\n\n"
               f"🤖 {b.get('name', '')}\n"
               f"📢 {ch_name}\n"
               f"أصبح البوت قادراً على النشر مرة أخرى.")
        await notify_admins(msg)


async def bot_channel_verify_loop():
    """حلقة دورية: التحقق من البوتات في القنوات + المزامنة التلقائية مع Telegram."""
    await asyncio.sleep(120)  # انتظار دقيقتين بعد بدء البوت
    while True:
        try:
            bots = db.get_all_publishing_bots()
            for b in bots:
                bid = b.get("id", "")
                token = db.bot_manager.get_token(bid) if hasattr(db, "bot_manager") else b.get("token", "")
                bname = b.get("name", bid)
                if not token:
                    continue
                # التحقق من صحة التوكن نفسه (هل البوت ما زال فعالاً)
                try:
                    token_ver = await verifier.validate_token(token)
                    if not token_ver.get("valid"):
                        msg = f"⚠️ **بوت غير صالح**\n\n🤖 {bname}\nالتوكن لم يعد صالحاً: {token_ver.get('error', 'غير معروف')}"
                        await notify_admins(msg)
                        continue
                except Exception:
                    pass
                # استخدام BotChannelMapper للحصول على القنوات
                if hasattr(db, "mapper"):
                    channel_ids = db.mapper.get_channels_for_bot(bid)
                else:
                    deps = db.get_dependencies_for("publishing_bot", bid)
                    channel_ids = [d.get("id", "") for d in deps]
                for ch_id in channel_ids:
                    if not ch_id:
                        continue
                    try:
                        # مزامنة معلومات القناة أولاً
                        ch = db.get_channel(ch_id)
                        await _auto_sync_channel_info(ch_id, entity_name(ch) if ch else ch_id)
                        # التحقق من وجود البوت في القناة
                        old_ver = db.get_bot_channel_verification(bid, ch_id) if hasattr(db, "get_bot_channel_verification") else {}
                        ver = await verifier.check_bot_in_channel(bid, ch_id, force=True)
                        # كشف التغييرات
                        if old_ver:
                            await _auto_detect_bot_changes(b, old_ver, ver, ch_id, entity_name(ch) if ch else ch_id)
                    except Exception:
                        pass
                    await asyncio.sleep(2)  # تجنب ضغط API
        except Exception as e:
            logger.warning(f"خطأ في حلقة فحص البوتات: {e}")
        await asyncio.sleep(BOT_VERIFY_INTERVAL)


# ============================================================
# UI: تعيين الموارد للقناة (بوتات، جلسات، AI، مواقع)
# ============================================================

_RESOURCE_MAP = {
    "bots": {"label": "🤖 بوتات النشر", "getter": "get_all_publishing_bots", "cfg_key": "assigned_bots"},
    "sessions": {"label": "📱 الجلسات", "getter": "get_all_sessions", "cfg_key": "assigned_sessions"},
    "ai": {"label": "🧠 مفاتيح AI", "getter": "get_all_ai_keys", "cfg_key": "assigned_ai"},
    "websites": {"label": "🌐 مواقع الويب", "getter": "get_all_websites", "cfg_key": "websites"},
}


def _get_resource_items(rtype):
    getter_name = _RESOURCE_MAP.get(rtype, {}).get("getter")
    if not getter_name:
        return []
    getter = getattr(db, getter_name, None)
    if not getter:
        return []
    try:
        return getter()
    except Exception:
        return []


async def assign_resource_menu(client, callback):
    """قائمة تعيين مورد معين لقناة."""
    parts = callback.data.split("_", 2)
    rtype = parts[1]
    ch_id = parts[2]
    info = _RESOURCE_MAP.get(rtype)
    if not info:
        await callback.answer("غير معروف.")
        return
    if rtype == "bots" and hasattr(db, "mapper"):
        assigned = set(db.mapper.get_bots_for_channel(ch_id))
    else:
        cfg = db.get_channel_config(ch_id)
        assigned = set(str(x) for x in cfg.get(info["cfg_key"], []))
    items = _get_resource_items(rtype)
    ch_name = entity_name(db.get_channel(ch_id))

    if rtype == "bots":
        # عرض خاص للبوتات: اسم + يوزر + إحصائيات + تشغيل/إيقاف
        lines = [f"🤖 **بوتات النشر** — {ch_name}\n", "✅ معيّن / 🔲 غير معيّن: اضغط البوت لتعيينه لهذه القناة أو إلغاء تعيينه. 🟢/🔴 يوضح حالة البوت.\n"]
        if not items:
            lines.append("لا توجد بوتات متاحة.")
        btns = []
        for item in items:
            item_id = str(item.get("id", ""))
            name = item.get("name", item_id)
            username = item.get("username", "?")
            enabled = item.get("enabled", True)
            stats = item.get("stats", {}) or {}
            pub = int(item.get("publish_count", 0))
            assigned_mark = "✅" if item_id in assigned else "🔲"
            enabled_mark = "🟢" if enabled else "🔴"
            lines.append(
                f"{assigned_mark} {enabled_mark} {name} (@{username})\n"
                f"   📊 {pub} منشور | نصوص:{stats.get('text',0)} صور:{stats.get('photo',0)} فيديو:{stats.get('video',0)} البوم:{stats.get('album',0)}"
            )
            btns.append(InlineKeyboardButton(f"{'✅' if item_id in assigned else '🔲'} {name} {'🟢' if enabled else '🔴'}", callback_data=f"toggle_assign_{rtype}_{ch_id}_{item_id}"))
        rows = grid_buttons(btns, 2) if btns else []
        rows.append(nav_row(f"genset_{ch_id}"))
        await safe_edit(callback, "\n".join(lines), InlineKeyboardMarkup(rows))
        return

    lines = [f"{info['label']} — {ch_name}\n", "✅ معيّن / 🔲 غير معيّن: اضغط المورد لتعيينه لهذه القناة أو إلغاء تعيينه.\n"]
    if not items:
        lines.append("لا توجد عناصر متاحة.")
    btns = []
    for item in items:
        item_id = str(item.get("id", ""))
        name = item.get("name", item_id)
        on = "✅" if item_id in assigned else "🔲"
        lines.append(f"{on} {name}")
        btns.append(InlineKeyboardButton(f"{on} {name}", callback_data=f"toggle_assign_{rtype}_{ch_id}_{item_id}"))
    rows = grid_buttons(btns, 2) if btns else []
    rows.append(nav_row(f"genset_{ch_id}"))
    await safe_edit(callback, "\n".join(lines), InlineKeyboardMarkup(rows))


async def toggle_assign_resource(client, callback):
    """تبديل تعيين مورد لقناة."""
    # callback.data = "toggle_assign_bots_ch_id_bot_id"
    parts = callback.data.split("_", 4)
    # ['toggle', 'assign', 'bots', 'ch_id', 'bot_id']
    if len(parts) < 5:
        await callback.answer("خطأ في البيانات.")
        return
    rtype = parts[2]
    ch_id = parts[3]
    item_id = parts[4]
    info = _RESOURCE_MAP.get(rtype)
    if not info:
        await callback.answer("غير معروف.")
        return
    if rtype == "bots" and hasattr(db, "mapper"):
        # استخدام BotChannelMapper للربط
        was_assigned = db.mapper.is_assigned(item_id, ch_id)
        if was_assigned:
            db.mapper.unassign(item_id, ch_id)
        else:
            db.mapper.assign(item_id, ch_id)
            # التحقق الفوري عند التعيين
            token = db.bot_manager.get_token(item_id) if hasattr(db, "bot_manager") else ""
            if token:
                try:
                    ver = await verifier.check_bot_in_channel(item_id, ch_id, force=True)
                except Exception:
                    pass
    else:
        # للأنواع الأخرى (sessions, ai, websites) - الطريقة القديمة
        cfg = db.get_channel_config(ch_id)
        key = info["cfg_key"]
        current = list(cfg.get(key, []))
        str_current = [str(x) for x in current]
        if str(item_id) in str_current:
            current = [x for x in current if str(x) != str(item_id)]
        else:
            current.append(item_id)
        db.update_channel_config(ch_id, **{key: current})
    await callback.answer("تم التحديث.")
    callback.data = f"assign_{rtype}_{ch_id}"
    await assign_resource_menu(client, callback)


# ============================================================
# UI: قائمة التنبيهات
# ============================================================

async def notifications_menu(client, callback):
    """عرض قائمة التنبيهات مع إمكانية تشغيل/إيقاف كل فحص."""
    ch_id = None
    if "|" in callback.data:
        ch_id = callback.data.split("|", 1)[1]
    settings = db.get_notification_settings()
    lines = ["🔔 **إعدادات التنبيهات**\n", "اضغط نوع التنبيه لتشغيله أو إيقافه. التنبيهات تصل للمشرفين عند حدوث أحداث:\n"]
    buttons = []
    for key, label in db.NOTIFICATION_TYPES.items():
        on = settings.get(key, True)
        lines.append(f"{'✅' if on else '❌'} {label}")
        buttons.append([InlineKeyboardButton(
            f"{'✅' if on else '❌'} {label}",
            callback_data=f"toggle_notif_{key}|{ch_id}" if ch_id else f"toggle_notif_{key}"
        )])
    buttons.append(nav_row(f"sysset_{ch_id}" if ch_id else "system_menu"))
    await safe_edit(callback, "\n".join(lines), InlineKeyboardMarkup(buttons))


async def _cache_cleanup_loop():
    """تنظيف دوري للكاش منتهي الصلاحية."""
    while True:
        await asyncio.sleep(600)  # كل 10 دقائق
        try:
            if hasattr(db, "cache_clear_expired"):
                db.cache_clear_expired()
        except Exception:
            pass


async def run_clients():
    global bot_client, user_client

    os.makedirs("/data/sessions", exist_ok=True)

    bot_client = Client(
        "/data/sessions/bot_session",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.BOT_TOKEN
    )

    user_client = Client(
        "/data/sessions/user_session",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        session_string=config.SESSION_STRING
    )

    register_bot_handlers(bot_client)
    register_user_handlers(user_client)
    register_middle_handlers(bot_client)

    await bot_client.start()
    await user_client.start()

    try:
        if hasattr(db, "cleanup_old_runtime_data"):
            db.cleanup_old_runtime_data(days=3)
    except Exception as e:
        logger.warning(f"تعذر تنظيف بيانات التشغيل القديمة: {e}")

    await warm_middle_peer()
    try:
        await warm_all_peers_after_import()
    except Exception as e:
        logger.warning(f"فشل تهيئة القنوات/المصادر عند التشغيل: {e}")

    logger.info("✅ البوتان شغّالان")
    asyncio.create_task(poll_public_sources_loop())
    asyncio.create_task(heartbeat_watchdog_loop())
    asyncio.create_task(notification_checks_loop())
    asyncio.create_task(bot_channel_verify_loop())
    asyncio.create_task(_cache_cleanup_loop())
    try:
        blogger_pub = BloggerPublisher()
        asyncio.create_task(blogger_pub.start())
        logger.info("✅ تم تشغيل Blogger Publisher")
    except Exception as e:
        logger.warning(f"⚠️ فشل تشغيل Blogger Publisher: {e}")
    logger.info("✅ تم تشغيل نظام Polling للمصادر العامة")
    logger.info("✅ تم تشغيل Heartbeat/Watchdog")
    logger.info("✅ تم تشغيل نظام التنبيهات")
    logger.info("✅ تم تشغيل فحص البوتات الدوري")
    logger.info("✅ تم تشغيل تنظيف الكاش الدوري")
    await asyncio.Event().wait()

def run_bot():
    lock_file = "/tmp/telegram_bot_core_running.lock"

    if os.path.exists(lock_file):
        # نتحقق إن البوت القديم فعلاً شغّال وليس ملف قفل متروك من crash سابق
        stale = True
        try:
            with open(lock_file, "r") as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)  # لا يرسل إشارة، فقط يتحقق من وجود العملية
            stale = False
        except (ValueError, FileNotFoundError):
            stale = True
        except ProcessLookupError:
            stale = True
        except PermissionError:
            stale = False  # العملية موجودة لكن لا صلاحية للفحص

        if not stale:
            logger.warning("⚠️ البوت يعمل مسبقاً، تم منع تشغيل نسخة ثانية.")
            return

        # ملف قفل متروك — نمسحه ونكمل
        try:
            os.remove(lock_file)
            logger.info("🧹 تم مسح ملف قفل متروك من تشغيل سابق.")
        except Exception:
            pass

    with open(lock_file, "w") as f:
        f.write(str(os.getpid()))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(run_clients())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.exception(f"توقف البوت بسبب خطأ: {e}")
    finally:
        try:
            if bot_client:
                loop.run_until_complete(bot_client.stop())
        except Exception:
            pass

        try:
            if user_client:
                loop.run_until_complete(user_client.stop())
        except Exception:
            pass

        try:
            if os.path.exists(lock_file):
                os.remove(lock_file)
        except Exception:
            pass

        loop.close()