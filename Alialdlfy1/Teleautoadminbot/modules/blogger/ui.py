import time
import logging

from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from modules.blogger.publisher import BloggerPublisher
from modules.blogger.scheduler import SLOTS_PER_DAY

logger = logging.getLogger(__name__)

_publisher = None

# Navigation stack per user
def get_publisher():
    global _publisher
    if _publisher is None:
        _publisher = BloggerPublisher()
    return _publisher


def _grid_buttons(buttons, max_cols=2):
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
            if len(pending) >= max_cols:
                rows.append(pending)
                pending = []
    if pending:
        rows.append(pending)
    return rows


async def safe_edit(callback, text, reply_markup=None):
    try:
        await callback.edit_message_text(text, reply_markup=reply_markup)
    except Exception:
        try:
            await callback.answer()
        except Exception:
            pass


def _nav_row(uid: int, back_callback: str = None):
    """صف أزرار قياسي: القائمة الرئيسية (للمينيو العام) + رجوع."""
    back_target = back_callback or _get_back_target(uid, "blogger_menu")
    return [
        InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu"),
        InlineKeyboardButton("🔙 رجوع", callback_data=back_target),
    ]


# Navigation stack for proper back-button behavior
_nav_stack: dict[int, list[str]] = {}


def _push_nav(uid: int, callback_data: str):
    stack = _nav_stack.get(uid, [])
    # Back navigation: pop current page, don't push target back
    if len(stack) >= 2 and callback_data == stack[-2]:
        stack.pop()
        _nav_stack[uid] = stack
        return
    # Avoid duplicate consecutive entries
    if stack and stack[-1] == callback_data:
        return
    stack.append(callback_data)
    _nav_stack[uid] = stack


def _get_back_target(uid: int, default: str = "blogger_menu") -> str:
    stack = _nav_stack.get(uid, [])
    if len(stack) >= 2:
        return stack[-2]
    if len(stack) == 1:
        return "main_menu"
    return default


def _clear_nav(uid: int):
    _nav_stack.pop(uid, None)


async def blogger_main_menu(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_menu")
    pub = get_publisher()
    cfg = pub.config.get_all()
    enabled = "✅ مفعل" if pub.config.is_enabled() else "❌ متوقف"
    configured = "✅ تم" if pub.client.is_configured() else "❌ غير مكتمل"
    blog_id = cfg.get("blog_id", "") or "غير محدد"
    queue_count = len([a for a in pub.db.get_articles_by_status("queued")])
    text = (
        f"🌐 **Blogger Publisher**\n\n"
        f"الحالة: {enabled}\n"
        f"الإعدادات: {configured}\n"
        f"Blog ID: `{blog_id}`\n"
        f"📥 المقالات في Queue: {queue_count}\n\n"
        f"اختر من القائمة:"
    )
    buttons = [
        InlineKeyboardButton("📚 المقالات", callback_data="blogger_articles"),
        InlineKeyboardButton("📝 إعدادات النشر", callback_data="blogger_settings"),
        InlineKeyboardButton("📂 إدارة الأقسام", callback_data="blogger_sections_main"),
        InlineKeyboardButton("📺 إدارة القنوات", callback_data="blogger_channels"),
        InlineKeyboardButton("🕒 جدولة النشر", callback_data="blogger_schedule_info"),
        InlineKeyboardButton("👁 معاينة آخر مقال", callback_data="blogger_preview_last"),
        InlineKeyboardButton("🖼 إعدادات الصورة", callback_data="blogger_set_default_image"),
        InlineKeyboardButton("📊 الإحصائيات", callback_data="blogger_stats"),
        InlineKeyboardButton("⚙️ الإعدادات المتقدمة", callback_data="blogger_advanced"),
    ]
    rows = _grid_buttons(buttons, 2)
    rows.append(_nav_row(uid, "main_menu"))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def blogger_settings_menu(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_settings")
    pub = get_publisher()
    cfg = pub.config.get_all()
    env_keys = pub.config.env_keys()
    def val(key, env_label, display=None):
        if key in env_keys:
            return f"🔒 {env_label} (من البيئة)"
        v = cfg.get(key, "")
        if display:
            return display(v)
        return f"`{v}`" if v else "❌ فارغ"
    text = (
        f"⚙️ **إعدادات Blogger**\n\n"
        f"Blog ID: {val('blog_id', 'محفوظ', lambda v: f'`{v}`')}\n"
        f"Client ID: {val('client_id', 'محفوظ', lambda v: f'`{v[:15]}...`') if 'client_id' not in env_keys else '🔒 محفوظ (من البيئة)'}\n"
        f"Client Secret: {val('client_secret', 'محفوظ', lambda v: '✅ محفوظ')}\n"
        f"Refresh Token: {val('refresh_token', 'محفوظ', lambda v: '✅ محفوظ')}\n"
        f"النشر كمسودة: {'✅' if cfg.get('publish_as_draft') else '❌'}\n"
        f"صورة الوظائف الافتراضية: {'✅ محددة' if cfg.get('default_jobs_image') else '❌ غير محددة'}\n\n"
    )
    if env_keys:
        text += "🔒 القيم من البيئة لا يمكن تعديلها من هنا.\n"
    else:
        text += "لتعيين أو تغيير أي قيمة، اضغط على الزر المناسب."
    buttons = []
    if "blog_id" not in env_keys:
        buttons.append(InlineKeyboardButton("📝 Blog ID", callback_data="blogger_set_blog_id"))
    if "client_id" not in env_keys:
        buttons.append(InlineKeyboardButton("🔑 Client ID", callback_data="blogger_set_client_id"))
    if "client_secret" not in env_keys:
        buttons.append(InlineKeyboardButton("🔐 Client Secret", callback_data="blogger_set_client_secret"))
    if "refresh_token" not in env_keys:
        buttons.append(InlineKeyboardButton("🔄 Refresh Token", callback_data="blogger_set_refresh_token"))
    if "publish_as_draft" not in env_keys:
        buttons.append(InlineKeyboardButton(f"{'✅' if cfg.get('publish_as_draft') else '❌'} مسودة", callback_data="blogger_toggle_draft"))
    if "default_jobs_image" not in env_keys:
        buttons.append(InlineKeyboardButton("🖼 صورة افتراضية للوظائف", callback_data="blogger_set_default_image"))
    buttons.append(InlineKeyboardButton("🧪 اختبار", callback_data="blogger_test"))
    if not buttons:
        buttons.append(InlineKeyboardButton("🧪 اختبار", callback_data="blogger_test"))
    rows = _grid_buttons(buttons, 2)
    rows.append(_nav_row(uid))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def blogger_channels_menu(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_channels")
    pub = get_publisher()
    channels = pub.db.get_all_channels()
    text = f"📢 **قنوات Blogger**\n\nعدد القنوات: {len(channels)}\n\n"
    if channels:
        for ch in channels:
            section = ch.get("section", "غير محدد")
            daily = ch.get("daily_limit", 0)
            enabled = "✅" if ch.get("enabled", True) else "❌"
            start_h = ch.get("start_hour", 9)
            end_h = ch.get("end_hour", 23)
            text += f"{enabled} {ch.get('name', ch.get('channel_id', '?'))}\n"
            text += f"   📂 {section} | 📊 {daily}/يوم | 🕐 {start_h}:00-{end_h}:00\n"
    else:
        text += "لا توجد قنوات بعد.\nأضف قناة تيليجرام كمصدر للنشر."
    buttons = [
        InlineKeyboardButton("➕ إضافة قناة", callback_data="blogger_add_channel"),
    ]
    if channels:
        buttons.append(InlineKeyboardButton("🗑 حذف قناة", callback_data="blogger_del_channel"))
        for ch in channels:
            ch_id = ch.get("channel_id", "")
            name = ch.get("name", ch_id)
            buttons.append(InlineKeyboardButton(f"⚙️ {name[:22]}", callback_data=f"blogger_edit_ch_{ch_id}"))
    buttons.append(InlineKeyboardButton("📂 إدارة الأقسام", callback_data="blogger_sections"))
    rows = _grid_buttons(buttons, 2)
    rows.append(_nav_row(uid))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def blogger_add_channel_prompt(client, callback):
    from bot_core import user_states
    uid = callback.from_user.id
    user_states.pop(uid, None)
    user_states[uid] = {"state": "blogger_add_channel_id"}
    await safe_edit(callback, "أرسل معرف القناة (ID) أو اليوزر (@username):\n\nمثال: @my_channel أو -1001234567890", InlineKeyboardMarkup([_nav_row(uid, "blogger_channels")]))


async def blogger_add_channel_section_prompt(client, message, ch_id, ch_name):
    from bot_core import user_states
    uid = message.from_user.id
    user_states.pop(uid, None)
    user_states[uid] = {"state": "blogger_add_ch_section", "ch_id": ch_id, "ch_name": ch_name}
    await message.reply("أرسل اسم القسم في المدونة:\nمثال: وظائف, أخبار, مناقصات")


async def blogger_add_channel_limit_prompt(client, message, ch_id, section):
    from bot_core import user_states
    uid = message.from_user.id
    user_states.pop(uid, None)
    user_states[uid] = {"state": "blogger_add_ch_limit", "ch_id": ch_id, "section": section}
    await message.reply("أرسل الحد اليومي لعدد المنشورات:\nمثال: 30")


async def blogger_del_channel_menu(client, callback):
    pub = get_publisher()
    channels = pub.db.get_all_channels()
    if not channels:
        await callback.answer("لا توجد قنوات.", show_alert=True)
        return
    text = "🗑 **حذف قناة Blogger**\n\nاختر القناة للحذف:"
    buttons = []
    for ch in channels:
        name = ch.get("name", ch.get("channel_id", "?"))
        ch_id = ch.get("channel_id", "")
        buttons.append([InlineKeyboardButton(f"🗑 {name}", callback_data=f"blogger_del_ch_{ch_id}")])
    uid = callback.from_user.id
    buttons.append(_nav_row(uid, "blogger_channels"))
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def blogger_confirm_del_channel(client, callback):
    ch_id = callback.data.split("_")[-1]
    pub = get_publisher()
    pub.db.delete_channel(ch_id)
    await callback.answer("✅ تم حذف القناة.")
    await blogger_channels_menu(client, callback)


async def blogger_edit_channel_menu(client, callback):
    uid = callback.from_user.id
    ch_id = callback.data.split("_")[-1]
    pub = get_publisher()
    ch = pub.db.get_channel(ch_id)
    if not ch:
        await callback.answer("غير موجودة.")
        return
    _push_nav(uid, f"blogger_edit_ch_{ch_id}")
    enabled = "✅" if ch.get("enabled", True) else "❌"
    sections = pub.db.get_all_sections()
    current_section = ch.get("section", "غير محدد")
    text = (
        f"⚙️ **إعدادات قناة Blogger**\n\n"
        f"الاسم: {ch.get('name', ch_id)}\n"
        f"ID: `{ch_id}`\n"
        f"الحالة: {enabled}\n"
        f"القسم الحالي: **{current_section}** 🔄 تغيير القسم\n"
        f"الحد اليومي: {ch.get('daily_limit', 10)}\n"
        f"ساعات النشر: {ch.get('start_hour', 9)}:00 - {ch.get('end_hour', 23)}:00\n"
    )
    buttons = [
        InlineKeyboardButton(f"{'✅' if ch.get('enabled', True) else '❌'} تفعيل/تعطيل", callback_data=f"blogger_toggle_ch_{ch_id}"),
        InlineKeyboardButton(f"🔄 تغيير القسم", callback_data=f"blogger_ch_section_{ch_id}"),
        InlineKeyboardButton(f"📊 تغيير الحد اليومي", callback_data=f"blogger_ch_limit_{ch_id}"),
        InlineKeyboardButton(f"🕐 تغيير ساعات النشر", callback_data=f"blogger_ch_hours_{ch_id}"),
        InlineKeyboardButton(f"📝 معاينة منشور", callback_data=f"blogger_preview_ch_{ch_id}"),
        InlineKeyboardButton(f"🔄 معالجة فورية", callback_data=f"blogger_process_{ch_id}"),
    ]
    rows = _grid_buttons(buttons, 2)
    rows.append(_nav_row(uid, "blogger_channels"))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def blogger_toggle_channel_handler(client, callback):
    uid = callback.from_user.id
    ch_id = callback.data.split("_")[-1]
    pub = get_publisher()
    ch = pub.db.get_channel(ch_id)
    if ch:
        new_state = not ch.get("enabled", True)
        ch["enabled"] = new_state
        pub.db.save_channel(ch_id, ch)
        await callback.answer("✅ تم التبديل.")
    callback.data = f"blogger_edit_ch_{ch_id}"
    await blogger_edit_channel_menu(client, callback)


async def blogger_manual_process(client, callback):
    ch_id = callback.data.split("_")[-1]
    pub = get_publisher()
    ch = pub.db.get_channel(ch_id)
    if not ch:
        await callback.answer("غير موجودة.")
        return
    await callback.answer("جارٍ المعالجة...")
    try:
        before = len(pub.db.get_all_channels())
        await pub.scheduler._fetch_new_posts([ch])
        await callback.answer("✅ تمت معالجة المنشورات وجدولتها.", show_alert=True)
    except Exception as e:
        logger.exception(f"Blogger manual process error: {e}")
        await callback.answer(f"❌ فشل: {str(e)[:50]}", show_alert=True)


async def blogger_preview_channel(client, callback):
    ch_id = callback.data.split("_")[-1]
    pub = get_publisher()
    ch = pub.db.get_channel(ch_id)
    if not ch:
        await callback.answer("غير موجودة.")
        return
    await callback.answer("جارٍ تجهيز المعاينة...")
    from bot_core import user_client
    if not user_client:
        await callback.answer("❌ البوت الشخصي غير متصل.", show_alert=True)
        return
    try:
        chat_identifier = int(ch_id) if str(ch_id).lstrip('-').isdigit() else ch_id
        msg = None
        async for m in user_client.get_chat_history(chat_identifier, limit=1):
            msg = m
            break
        if not msg:
            await callback.answer("لا توجد رسائل في القناة.", show_alert=True)
            return
        try:
            tmp = msg.text or msg.caption or ""
        except UnicodeDecodeError:
            await callback.answer("❌ تعذر قراءة الرسالة (ترميز تالف).", show_alert=True)
            return
        try:
            raw = str(tmp) if tmp else ""
        except (UnicodeDecodeError, UnicodeEncodeError):
            await callback.answer("❌ تعذر قراءة الرسالة (ترميز تالف).", show_alert=True)
            return
        if not raw.strip():
            await callback.answer("الرسالة الأخيرة فارغة.", show_alert=True)
            return
        fingerprint = pub.processor._fingerprint(raw, str(msg.id))
        article = pub.db.get_article(fingerprint)
        if not article:
            article_data = await pub.processor.process_raw_post(raw, f"preview_{ch_id}_{msg.id}", channel_id=ch_id)
            if not article_data:
                await callback.answer("❌ فشلت المعالجة.", show_alert=True)
                return
            article_data["channel_id"] = ch_id
            section_name = ch.get("section", "")
            article_data["section"] = section_name
            article_data["labels"] = list(pub.scheduler._get_section_labels(section_name))
            pub.db.save_article(fingerprint, article_data)
            article = article_data
        image_source, telegram_text = pub.processor.make_preview_data(article)
        if len(telegram_text) > 4096:
            telegram_text = telegram_text[:4093] + "..."
        buttons = [
            InlineKeyboardButton("📤 نشر الآن", callback_data=f"blogger_publish_now_{fingerprint}"),
            InlineKeyboardButton("💾 كمسودة", callback_data=f"blogger_publish_draft_{fingerprint}"),
            InlineKeyboardButton("🗑 حذف", callback_data=f"blogger_discard_{fingerprint}"),
        ]
        rows = _grid_buttons(buttons, 2)
        rows.append(_nav_row(callback.from_user.id, f"blogger_edit_ch_{ch_id}"))
        markup = InlineKeyboardMarkup(rows)
        had_image = bool(image_source)
        if had_image:
            try:
                await client.send_photo(
                    callback.from_user.id,
                    photo=image_source,
                    caption="📝 **معاينة المنشور**",
                )
            except Exception as e:
                logger.warning(f"Failed to send preview photo: {e}")
                telegram_text = f"⚠️ الصورة غير متوفرة\n\n{telegram_text}"
        sent = await client.send_message(
            callback.from_user.id,
            telegram_text,
            reply_markup=markup,
        )
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.answer("✅ تم إرسال المعاينة", show_alert=True)
    except Exception as e:
        logger.exception(f"Blogger preview error: {e}")
        await callback.answer(f"❌ خطأ: {str(e)[:50]}", show_alert=True)


async def blogger_publish_article_now(client, callback):
    import re
    fingerprint = callback.data[len("blogger_publish_now_"):]
    pub = get_publisher()
    article = pub.db.get_article(fingerprint)
    if not article:
        await callback.answer("المنشور غير موجود.", show_alert=True)
        return
    html = pub.processor.make_article_html(article)
    section = article.get("section", "")
    labels = list(pub.scheduler._get_section_labels(section))
    blogger_article = {
        "title": article.get("title", "عنوان المقال"),
        "content": html,
        "labels": labels,
    }
    await callback.answer("جارٍ النشر...")
    post_id = await pub.publish_article(blogger_article, fingerprint)
    if post_id:
        pub.db.update_article_status(fingerprint, "published", {"post_id": post_id, "published_at": int(time.time())})
        await callback.answer("✅ تم النشر بنجاح!", show_alert=True)
    else:
        await callback.answer("❌ فشل النشر.", show_alert=True)


async def blogger_publish_article_draft(client, callback):
    fingerprint = callback.data[len("blogger_publish_draft_"):]
    pub = get_publisher()
    article = pub.db.get_article(fingerprint)
    if not article:
        await callback.answer("المنشور غير موجود.", show_alert=True)
        return
    html = pub.processor.make_article_html(article)
    section = article.get("section", "")
    labels = list(pub.scheduler._get_section_labels(section))
    blogger_article = {
        "title": article.get("title", "عنوان المقال"),
        "content": html,
        "labels": labels,
    }
    await callback.answer("جارٍ النشر كمسودة...")
    post_id = await pub.publish_article(blogger_article, fingerprint, draft=True)
    if post_id:
        pub.db.update_article_status(fingerprint, "draft", {"post_id": post_id, "published_at": int(time.time())})
        await callback.answer("✅ تم النشر كمسودة!", show_alert=True)
    else:
        await callback.answer("❌ فشل النشر.", show_alert=True)


async def blogger_discard_article(client, callback):
    fingerprint = callback.data[len("blogger_discard_"):]
    pub = get_publisher()
    article = pub.db.get_article(fingerprint)
    if article:
        pub.db.update_article_status(fingerprint, "discarded", {"discarded_at": int(time.time())})
    await callback.answer("🗑 تم الحفظ للإلغاء.", show_alert=True)


async def blogger_ch_section_prompt(client, callback):
    from bot_core import user_states
    ch_id = callback.data.split("_")[-1]
    uid = callback.from_user.id
    pub = get_publisher()
    sections = pub.db.get_all_sections()
    buttons = []
    if sections:
        for sid, sdata in sections.items():
            sname = sdata.get("name", sid)
            buttons.append(InlineKeyboardButton(sname, callback_data=f"blogger_ch_sec_set_{ch_id}_{sid}"))
    buttons.append(InlineKeyboardButton("➕ إضافة قسم جديد", callback_data=f"blogger_ch_sec_new_{ch_id}"))
    rows = _grid_buttons(buttons, 2)
    rows.append(_nav_row(uid, f"blogger_edit_ch_{ch_id}"))
    ch = pub.db.get_channel(ch_id)
    current = ch.get("section", "غير محدد") if ch else "غير محدد"
    await safe_edit(callback, f"📂 **اختر القسم**\nالقسم الحالي: {current}\nأو أضف قسماً جديداً:", InlineKeyboardMarkup(rows))


async def blogger_ch_sec_set(client, callback):
    parts = callback.data.split("_")
    ch_id = parts[-2]
    sid = parts[-1]
    pub = get_publisher()
    sections = pub.db.get_all_sections()
    sdata = sections.get(sid)
    if not sdata:
        await callback.answer("القسم غير موجود.", show_alert=True)
        return
    section_name = sdata.get("name", sid)
    ch = pub.db.get_channel(ch_id)
    if ch:
        ch["section"] = section_name
        pub.db.save_channel(ch_id, ch)
        await callback.answer(f"✅ تم تعيين القسم: {section_name}")
    callback.data = f"blogger_edit_ch_{ch_id}"
    await blogger_edit_channel_menu(client, callback)


async def blogger_ch_sec_new(client, callback):
    from bot_core import user_states
    ch_id = callback.data.split("_")[-1]
    uid = callback.from_user.id
    user_states[uid] = {"state": "blogger_ch_sec_new_input", "ch_id": ch_id}
    await safe_edit(callback, "أرسل اسم القسم الجديد:", InlineKeyboardMarkup([_nav_row(uid, f"blogger_ch_section_{ch_id}")]))


async def blogger_ch_limit_prompt(client, callback):
    from bot_core import user_states
    ch_id = callback.data.split("_")[-1]
    uid = callback.from_user.id
    user_states[uid] = {"state": "blogger_ch_limit_input", "ch_id": ch_id}
    await safe_edit(callback, "أرسل الحد اليومي الجديد:\nمثال: 30", InlineKeyboardMarkup([_nav_row(uid, f"blogger_edit_ch_{ch_id}")]))


async def blogger_ch_hours_prompt(client, callback):
    from bot_core import user_states
    ch_id = callback.data.split("_")[-1]
    uid = callback.from_user.id
    user_states[uid] = {"state": "blogger_ch_hours_input", "ch_id": ch_id}
    await safe_edit(callback, "أرسل ساعات النشر بالتنسيق:\n`start_hour-end_hour`\nمثال: 9-23", InlineKeyboardMarkup([_nav_row(uid, f"blogger_edit_ch_{ch_id}")]))


async def blogger_sections_main_menu(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_sections_main")
    pub = get_publisher()
    sections = pub.db.get_all_sections()
    text = f"📂 **إدارة الأقسام**\n\nعدد الأقسام: {len(sections)}"
    buttons = [
        InlineKeyboardButton("➕ إضافة قسم", callback_data="blogger_section_add"),
        InlineKeyboardButton("📋 قائمة الأقسام", callback_data="blogger_sections"),
    ]
    rows = _grid_buttons(buttons, 2)
    rows.append(_nav_row(uid))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def blogger_section_add_prompt(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_section_add_prompt")
    from bot_core import user_states
    user_states.pop(uid, None)
    user_states[uid] = {"state": "blogger_section_add_name"}
    await safe_edit(callback, "أرسل اسم القسم الجديد:", InlineKeyboardMarkup([_nav_row(uid)]))


async def blogger_section_detail_menu(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, f"blogger_section_detail_{callback.data.split('_')[-1]}")
    sid = callback.data.split("_")[-1]
    pub = get_publisher()
    sections = pub.db.get_all_sections()
    sdata = sections.get(sid)
    if not sdata:
        await callback.answer("القسم غير موجود.", show_alert=True)
        return
    name = sdata.get("name", sid)
    labels = sdata.get("labels", [])
    label_text = "، ".join(labels) if labels else "لا توجد تسميات"
    text = (
        f"📂 **{name}**\n\n"
        f"الرقم التعريفي: `{sid}`\n"
        f"🏷️ التسميات: {label_text}\n"
    )
    buttons = [
        InlineKeyboardButton("✅ اختيار القسم", callback_data=f"blogger_sec_pick_{sid}"),
        InlineKeyboardButton("✏️ تعديل الاسم", callback_data=f"blogger_section_edit_{sid}"),
        InlineKeyboardButton("🏷️ إدارة التسميات", callback_data=f"blogger_sec_labels_{sid}"),
        InlineKeyboardButton("🗑 حذف القسم", callback_data=f"blogger_section_del_{sid}"),
    ]
    rows = _grid_buttons(buttons, 2)
    rows.append(_nav_row(uid))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def blogger_sec_pick(client, callback):
    sid = callback.data.split("_")[-1]
    pub = get_publisher()
    sections = pub.db.get_all_sections()
    sdata = sections.get(sid)
    if not sdata:
        await callback.answer("القسم غير موجود.", show_alert=True)
        return
    section_name = sdata.get("name", sid)
    channels = pub.db.get_all_channels()
    text = f"✅ اختر القناة لتعيين القسم **{section_name}**:"
    buttons = []
    for ch in channels:
        ch_id = ch.get("channel_id", "")
        ch_name = ch.get("name", ch_id)
        buttons.append([InlineKeyboardButton(f"📢 {ch_name}", callback_data=f"blogger_sec_set_ch_{sid}_{ch_id}")])
    uid = callback.from_user.id
    buttons.append(_nav_row(uid))
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def blogger_sec_set_ch(client, callback):
    parts = callback.data.split("_")
    sid = parts[-2]
    ch_id = parts[-1]
    pub = get_publisher()
    sections = pub.db.get_all_sections()
    sdata = sections.get(sid)
    if not sdata:
        await callback.answer("القسم غير موجود.", show_alert=True)
        return
    section_name = sdata.get("name", sid)
    ch = pub.db.get_channel(ch_id)
    if ch:
        ch["section"] = section_name
        pub.db.save_channel(ch_id, ch)
        await callback.answer(f"✅ تم تعيين القسم {section_name} للقناة")
    await blogger_section_detail_menu(client, callback)


async def blogger_sec_labels_menu(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, f"blogger_sec_labels_{callback.data.split('_')[-1]}")
    sid = callback.data.split("_")[-1]
    pub = get_publisher()
    sections = pub.db.get_all_sections()
    sdata = sections.get(sid)
    if not sdata:
        await callback.answer("القسم غير موجود.", show_alert=True)
        return
    name = sdata.get("name", sid)
    labels = sdata.get("labels", [])
    text = f"🏷️ **تسميات {name}**\n\n"
    if labels:
        text += "التسميات الحالية:\n"
        for i, label in enumerate(labels, 1):
            text += f"{i}. {label}\n"
    else:
        text += "لا توجد تسميات.\n"
    text += "\nاختر تسمية لحذفها أو أضف تسمية جديدة:"
    buttons = [
        InlineKeyboardButton("➕ إضافة تسمية", callback_data=f"blogger_sec_add_label_{sid}"),
    ]
    for label in labels:
        short = label[:20]
        buttons.append(InlineKeyboardButton(f"🗑 {short}", callback_data=f"blogger_sec_del_label_{sid}_{label}"))
    rows = _grid_buttons(buttons, 2)
    rows.append(_nav_row(uid))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def blogger_sec_add_label_prompt(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, f"blogger_sec_add_label_{callback.data.split('_')[-1]}")
    sid = callback.data.split("_")[-1]
    from bot_core import user_states
    user_states[uid] = {"state": "blogger_sec_add_label_input", "sid": sid}
    await safe_edit(callback, "أرسل التسمية الجديدة:", InlineKeyboardMarkup([_nav_row(uid)]))


async def blogger_sec_del_label(client, callback):
    parts = callback.data.split("_")
    sid = parts[-2]
    label = parts[-1]
    pub = get_publisher()
    sections = pub.db.get_all_sections()
    sdata = sections.get(sid)
    if sdata:
        labels = sdata.get("labels", [])
        if label in labels:
            labels.remove(label)
            sdata["labels"] = labels
            pub.db.add_section(sid, sdata)
            await callback.answer(f"✅ تم حذف التسمية: {label}")
    await blogger_sec_labels_menu(client, callback)


async def blogger_advanced_menu(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_advanced")
    pub = get_publisher()
    cfg = pub.config.get_all()
    text = (
        f"⚙️ **الإعدادات المتقدمة**\n\n"
        f"🔑 مفاتيح Gemini: {len(pub.db.get_all_ai_keys())}\n"
        f"📋 سجل العمليات: متاح\n"
        f"🧪 اختبار الاتصال: متاح\n"
    )
    buttons = [
        InlineKeyboardButton("🔑 مفاتيح Gemini", callback_data="blogger_ai_keys"),
        InlineKeyboardButton("📋 سجل العمليات", callback_data="blogger_logs"),
        InlineKeyboardButton("🧪 اختبار الاتصال", callback_data="blogger_test"),
        InlineKeyboardButton(f"{'✅' if pub.config.is_enabled() else '❌'} تشغيل/إيقاف", callback_data="blogger_toggle"),
    ]
    rows = _grid_buttons(buttons, 2)
    rows.append(_nav_row(uid))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def blogger_schedule_info(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_schedule_info")
    pub = get_publisher()
    state = pub.db.get_schedule_state()
    today = time.strftime("%Y-%m-%d")
    last_slot = state.get("last_slot", -1) if state.get("day") == today else -1
    slots_total = SLOTS_PER_DAY
    used = last_slot + 1
    remaining = max(0, slots_total - used)
    queue = len([a for a in pub.db.get_articles_by_status("queued")])
    text = (
        f"🕒 **جدولة النشر**\n\n"
        f"⏰ وقت البدء: 09:00 صباحاً\n"
        f"⏰ وقت الانتهاء: 23:00 مساءً\n"
        f"⏱️ الفاصل بين المقالات: 30 دقيقة\n"
        f"📊 الفترات المتاحة اليوم: {slots_total}\n"
        f"✅ الفترات المستخدمة: {used}\n"
        f"📅 الفترات المتبقية: {remaining}\n"
        f"📥 المقالات في Queue: {queue}\n"
    )
    await safe_edit(callback, text, InlineKeyboardMarkup([_nav_row(uid)]))


async def blogger_preview_last(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_preview_last")
    pub = get_publisher()
    articles = pub.db.get_articles_by_status("queued")
    if not articles:
        await safe_edit(callback, "📭 **معاينة آخر منشور**\n\nلا توجد منشورات بانتظار النشر.", InlineKeyboardMarkup([_nav_row(uid)]))
        return
    article = articles[-1]
    fingerprint = article.get("fingerprint", "")
    if not fingerprint:
        await safe_edit(callback, "❌ لا يمكن عرض المعاينة.", InlineKeyboardMarkup([_nav_row(uid)]))
        return
    title = article.get("title", "بدون عنوان")
    section = article.get("section", "عام")
    labels = article.get("labels", [])
    status = article.get("status", "غير معروف")
    key_used = article.get("gemini_key", article.get("_session_kid", "غير محدد"))
    publish_time = article.get("scheduled_time", "حسب الجدولة")
    created_at = article.get("created_at", 0)
    if created_at:
        created_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(created_at))
    else:
        created_str = "غير معروف"
    label_text = "، ".join(labels) if labels else "لا توجد"
    info = (
        f"👁 **معاينة آخر منشور في Queue**\n\n"
        f"📌 **العنوان:** {title}\n"
        f"📂 **القسم:** {section}\n"
        f"🏷️ **التسميات:** {label_text}\n"
        f"🕐 **تاريخ الإضافة:** {created_str}\n"
        f"⏰ **وقت النشر:** {publish_time}\n"
        f"🔑 **المفتاح:** {key_used}\n"
        f"📊 **الحالة:** {status}\n\n"
        f"---\n"
    )
    html = pub.processor.make_article_html(article)
    preview_text = pub.processor.html_to_telegram(html)
    full_text = info + preview_text
    if len(full_text) > 4096:
        full_text = full_text[:4093] + "..."
    image_source = None
    media = article.get("media", [])
    for m in media:
        if m.get("type") == "photo":
            image_source = m.get("file_id")
            break
    if not image_source:
        image_source = pub.config.get("default_jobs_image", "")
    buttons = [
        InlineKeyboardButton("📤 نشر الآن", callback_data=f"blogger_publish_now_{fingerprint}"),
        InlineKeyboardButton("💾 كمسودة", callback_data=f"blogger_publish_draft_{fingerprint}"),
        InlineKeyboardButton("🗑 حذف", callback_data=f"blogger_discard_{fingerprint}"),
    ]
    rows = _grid_buttons(buttons, 2)
    rows.append(_nav_row(uid))
    markup = InlineKeyboardMarkup(rows)
    if image_source:
        try:
            await client.send_photo(callback.from_user.id, photo=image_source, caption=f"📝 **{title[:30]}**")
        except Exception as e:
            logger.warning(f"Failed to send preview photo: {e}")
    await client.send_message(callback.from_user.id, full_text, reply_markup=markup)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("✅ تم إرسال المعاينة", show_alert=True)


async def blogger_sections_menu(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_sections")
    pub = get_publisher()
    sections = pub.db.get_all_sections()
    text = f"📋 **قائمة الأقسام**\n\nعدد الأقسام: {len(sections)}"
    if sections:
        text += "\n\nاختر قسماً لعرض التفاصيل:"
    else:
        text += "\n\nلا توجد أقسام بعد.\nيمكنك إضافة قسم جديد."
    buttons = []
    for sid, sdata in sections.items():
        name = sdata.get("name", sid)
        buttons.append([InlineKeyboardButton(f"📂 {name}", callback_data=f"blogger_section_detail_{sid}")])
    buttons.append(_nav_row(uid))
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def blogger_section_edit(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, f"blogger_section_edit_{callback.data.split('_')[-1]}")
    sid = callback.data.split("_")[-1]
    from bot_core import user_states
    user_states[uid] = {"state": "blogger_section_rename", "sid": sid}
    await safe_edit(callback, "أرسل الاسم الجديد للقسم:", InlineKeyboardMarkup([_nav_row(uid)]))


async def blogger_section_del(client, callback):
    sid = callback.data.split("_")[-1]
    pub = get_publisher()
    pub.db.delete_section(sid)
    await callback.answer("✅ تم حذف القسم.")
    await blogger_sections_main_menu(client, callback)


async def blogger_stats_menu(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_stats")
    pub = get_publisher()
    stats = pub.db.get_stats()
    text = (
        f"📊 **إحصائيات Blogger**\n\n"
        f"✅ المنشورات: {stats.get('total_published', 0)}\n"
        f"❌ الفاشلة: {stats.get('total_failed', 0)}"
    )
    try:
        perf = pub.ai.key_manager.get_perf_stats()
        total = perf.get("requests", 0)
        if total:
            rate = perf.get("success_rate", 0.0)
            text += (
                f"\n\n⚡ **أداء الذكاء الاصطناعي**\n"
                f"🔢 الطلبات: {total}\n"
                f"✅ ناجحة: {perf.get('success', 0)}\n"
                f"❌ أخطاء: {perf.get('errors', 0)}\n"
                f"⏱ مهلة: {perf.get('timeouts', 0)} | 🚫 حظر: {perf.get('rate_limited', 0)}\n"
                f"🎯 نسبة النجاح: {rate}%\n"
                f"⚡ متوسط الاستجابة: {perf.get('avg_latency_ms', 0)}ms"
            )
    except Exception as e:
        logger.warning(f"Failed to load AI perf stats: {e}")
    buttons = [
        InlineKeyboardButton("🔑 إحصائيات المفاتيح", callback_data="blogger_stats_keys"),
    ]
    rows = _grid_buttons(buttons, 2)
    rows.append(_nav_row(uid, "blogger_menu"))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def blogger_stats_keys_menu(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_stats_keys")
    pub = get_publisher()
    keys = pub.db.get_all_ai_keys()
    env_keys = {k: v for k, v in pub.ai.key_manager.get_all_keys_summary().items() if v.get("_source") == "env"}
    all_keys = dict(env_keys)
    all_keys.update(keys)
    text = "🔑 **إحصائيات مفاتيح الذكاء الاصطناعي**\n\n"
    if not all_keys:
        text += "لا توجد مفاتيح بعد."
    else:
        for kid, kdata in all_keys.items():
            name = kdata.get("name", kid)
            if kdata.get("_source") == "env":
                status = "🔒"
            else:
                status = "✅" if kdata.get("enabled", True) else "❌"
            text += f"{status} **{name}**\n"
            cd = pub.ai.key_manager.cooldown_remaining(kid) if kdata.get("_source") != "env" else 0
            suffix = _ai_key_stats_line(kdata)
            if cd:
                suffix += f" | ⏳ {cd}s"
            text += f"   {suffix}\n"
    await safe_edit(callback, text, InlineKeyboardMarkup([_nav_row(uid, "blogger_stats")]))


def _ai_key_stats_line(kdata: dict) -> str:
    usage = kdata.get("usage_count", 0)
    errors = kdata.get("error_count", 0)
    avg = kdata.get("avg_latency_ms", 0)
    last_reason = kdata.get("last_error_reason", "")
    parts = [f"📊 {usage} طلب", f"❌ {errors} خطأ"]
    if avg:
        parts.append(f"⚡ {avg}ms")
    if last_reason:
        parts.append(f"آخر خطأ: {last_reason}")
    return " | ".join(parts)


async def blogger_logs_menu(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_logs")
    pub = get_publisher()
    logs = pub.db.get_logs(20)
    text = "📋 **آخر العمليات**\n\n"
    if not logs:
        text += "لا توجد عمليات."
    else:
        for entry in logs:
            ts = entry.get("time", 0)
            tstr = time.strftime("%H:%M", time.localtime(ts)) if ts else "?"
            st = "✅" if entry.get("status") == "success" else "❌"
            title = entry.get("title", "")[:30]
            text += f"{st} [{tstr}] {title}\n"
    await safe_edit(callback, text, InlineKeyboardMarkup([_nav_row(uid)]))


async def blogger_test_handler(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_test")
    pub = get_publisher()
    if not pub.client.is_configured():
        await safe_edit(
            callback,
            "❌ الإعدادات غير مكتملة. أضف Blog ID و Client ID و Secret و Refresh Token أولاً.",
            InlineKeyboardMarkup([_nav_row(uid)])
        )
        return
    await callback.answer("جاري اختبار الاتصال...")
    ok = await pub.test_connection()
    if ok:
        await safe_edit(
            callback,
            "✅ **تم الاتصال بنجاح**\n\nBlogger يعمل بشكل صحيح.",
            InlineKeyboardMarkup([_nav_row(uid)])
        )
    else:
        await safe_edit(
            callback,
            "❌ **فشل الاتصال**\n\nتحقق من الإعدادات وراجع السجل.",
            InlineKeyboardMarkup([_nav_row(uid)])
        )


async def blogger_toggle_handler(client, callback):
    uid = callback.from_user.id
    pub = get_publisher()
    new_state = not pub.config.is_enabled()
    pub.config.set("enabled", new_state)
    status = "✅ تم التفعيل" if new_state else "❌ تم الإيقاف"
    await callback.answer(status, show_alert=True)
    await blogger_main_menu(client, callback)


async def blogger_toggle_draft_handler(client, callback):
    uid = callback.from_user.id
    pub = get_publisher()
    current = pub.config.get("publish_as_draft", False)
    pub.config.set("publish_as_draft", not current)
    await callback.answer("تم التحديث.")
    await blogger_settings_menu(client, callback)


async def set_blog_id_prompt(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_set_blog_id")
    from bot_core import user_states
    user_states.pop(uid, None)
    user_states[uid] = {"state": "blogger_set_blog_id"}
    await safe_edit(callback, "أرسل Blog ID الخاص بمدونتك:", InlineKeyboardMarkup([_nav_row(uid)]))


async def set_client_id_prompt(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_set_client_id")
    from bot_core import user_states
    user_states.pop(uid, None)
    user_states[uid] = {"state": "blogger_set_client_id"}
    await safe_edit(callback, "أرسل Client ID من Google Cloud Console:", InlineKeyboardMarkup([_nav_row(uid)]))


async def set_client_secret_prompt(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_set_client_secret")
    from bot_core import user_states
    user_states.pop(uid, None)
    user_states[uid] = {"state": "blogger_set_client_secret"}
    await safe_edit(callback, "أرسل Client Secret:", InlineKeyboardMarkup([_nav_row(uid)]))


async def set_refresh_token_prompt(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_set_refresh_token")
    from bot_core import user_states
    user_states.pop(uid, None)
    user_states[uid] = {"state": "blogger_set_refresh_token"}
    await safe_edit(callback, "أرسل Refresh Token:", InlineKeyboardMarkup([_nav_row(uid)]))


async def set_default_image_prompt(client, callback):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_set_default_image")
    pub = get_publisher()
    current = pub.config.get("default_jobs_image", "")
    if current:
        text = (
            f"🖼 **إعدادات الصورة الافتراضية**\n\n"
            f"✅ يوجد رابط صورة محفوظ:\n"
            f"`{current[:80]}{'...' if len(current) > 80 else ''}`\n\n"
            f"اختر من الخيارات أدناه:"
        )
        buttons = [
            InlineKeyboardButton("👁 معاينة الصورة", callback_data="blogger_preview_image"),
            InlineKeyboardButton("✏️ تعديل الرابط", callback_data="blogger_edit_image"),
            InlineKeyboardButton("🗑 حذف الصورة", callback_data="blogger_delete_image"),
            InlineKeyboardButton("➕ إضافة صورة جديدة", callback_data="blogger_add_image"),
        ]
    else:
        text = "🖼 **إعدادات الصورة الافتراضية**\n\n❌ لا توجد صورة.\n\nيمكنك إضافة صورة افتراضية للمقالات:"
        buttons = [
            InlineKeyboardButton("➕ إضافة صورة", callback_data="blogger_add_image"),
        ]
    rows = _grid_buttons(buttons, 2)
    rows.append(_nav_row(uid))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def blogger_preview_image_handler(client, callback):
    pub = get_publisher()
    current = pub.config.get("default_jobs_image", "")
    if not current:
        await callback.answer("❌ لا توجد صورة.", show_alert=True)
        return
    if not current.startswith(("http://", "https://")):
        await callback.answer("❌ الرابط المخزن غير صالح. يجب أن يبدأ بـ http:// أو https://", show_alert=True)
        return
    try:
        await client.send_photo(callback.from_user.id, photo=current, caption="🖼 **الصورة الافتراضية الحالية**")
        await callback.answer("✅ تم إرسال الصورة")
    except Exception as e:
        logger.warning(f"Failed to send image: {e}")
        await callback.answer(f"❌ فشل إرسال الصورة: {str(e)[:30]}", show_alert=True)


async def blogger_edit_image_prompt(client, callback):
    from bot_core import user_states
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {"state": "blogger_set_default_image"}
    await safe_edit(callback, "أرسل الرابط الجديد للصورة الافتراضية:", InlineKeyboardMarkup([_nav_row(callback.from_user.id, "blogger_set_default_image")]))


async def blogger_add_image_prompt(client, callback):
    from bot_core import user_states
    user_states.pop(callback.from_user.id, None)
    user_states[callback.from_user.id] = {"state": "blogger_set_default_image"}
    await safe_edit(callback, "أرسل رابط الصورة الجديدة:", InlineKeyboardMarkup([_nav_row(callback.from_user.id, "blogger_set_default_image")]))


async def blogger_delete_image_handler(client, callback):
    pub = get_publisher()
    pub.config.set("default_jobs_image", "")
    await callback.answer("✅ تم حذف الصورة.", show_alert=True)
    await set_default_image_prompt(client, callback)


async def blogger_test_ai_key_handler(client, callback):
    pub = get_publisher()
    prefix = "blogger_test_ai_key_"
    kid = callback.data[len(prefix):]
    keys = dict(pub.db.get_all_ai_keys())
    for ekid, ekdata in pub.ai.key_manager.get_all_keys_summary().items():
        if ekdata.get("_source") == "env":
            keys[ekid] = ekdata
    kdata = keys.get(kid)
    if not kdata:
        await callback.answer("المفتاح غير موجود.", show_alert=True)
        return
    api_key = kdata.get("key", "")
    if not api_key:
        await callback.answer("المفتاح فارغ.", show_alert=True)
        return
    await callback.answer("جارٍ اختبار المفتاح...")
    import httpx
    from modules.blogger.ai_manager import (
        PROVIDER_CONFIGS, get_models, invalidate_model_cache,
        _gemini_chat, _openai_chat, _discover_gemini_models,
    )
    provider = kdata.get("_provider", "gemini")
    key_preview = api_key[:8] + "..."
    last_err = ""
    async with httpx.AsyncClient(timeout=30) as hc:
        try:
            if provider == "gemini":
                models = await _discover_gemini_models(hc, api_key)
                if not models:
                    models = ["gemini-2.0-flash"]
                for model in models:
                    code, data = await _gemini_chat(hc, api_key, model, "قل مرحبا بالعربية")
                    if code == 200:
                        txt = data if isinstance(data, str) else ""
                        await callback.answer(f"✅ {model}: {txt[:80]}" if txt else f"✅ {model}: رد فارغ", show_alert=True)
                        await blogger_ai_keys_menu(client, callback)
                        return
                    err_msg = data.get("message", str(data)) if isinstance(data, dict) else str(data)
                    last_err = f"{code}: {err_msg[:60]}"
            else:
                base_url = PROVIDER_CONFIGS[provider]["api_base"]
                models = await get_models(provider, hc, api_key, force=True) if provider != "gemini" else []
                if not models:
                    models = ["llama-3.1-8b-instant"]
                for model in models:
                    code, data = await _openai_chat(hc, base_url, api_key, model, "قل مرحبا بالعربية")
                    if code == 200:
                        txt = data if isinstance(data, str) else ""
                        await callback.answer(f"✅ {model}: {txt[:80]}" if txt else f"✅ {model}: رد فارغ", show_alert=True)
                        await blogger_ai_keys_menu(client, callback)
                        return
                    err_msg = data.get("message", str(data)) if isinstance(data, dict) else str(data)
                    last_err = f"{code}: {err_msg[:60]}"
        except Exception as e:
            last_err = str(e)[:60]
    await callback.answer(f"❌ {provider}: جميع الموديلات فشلت: {last_err}", show_alert=True)
    await blogger_ai_keys_menu(client, callback)


async def blogger_ai_keys_menu(client, callback):
    uid = callback.from_user.id
    pub = get_publisher()
    db_keys = pub.db.get_all_ai_keys()
    env_keys = {k: v for k, v in pub.ai.key_manager.get_all_keys_summary().items() if v.get("_source") == "env"}
    text = "🔑 **مفاتيح Gemini**\n\n"
    if not db_keys and not env_keys:
        text += "لا توجد مفاتيح بعد.\nأضف مفتاحاً جديداً."
    else:
        if env_keys:
            text += "🔒 **مفاتيح البيئة (محمية)**\n"
            for kid, kdata in env_keys.items():
                name = kdata.get("name", kid)
                usage = kdata.get("usage_count", 0)
                errors = kdata.get("error_count", 0)
                text += f"🔒 `{name}`\n"
                text += f"   📊 {usage} طلب | ❌ {errors} خطأ\n"
            text += "\n"
        if db_keys:
            text += f"📝 **مفاتيح التطبيق**\n"
            for kid, kdata in db_keys.items():
                name = kdata.get("name", kid)
                status = "✅" if kdata.get("enabled", True) else "❌"
                usage = kdata.get("usage_count", 0)
                errors = kdata.get("error_count", 0)
                last = kdata.get("last_used", 0)
                last_str = time.strftime("%H:%M", time.localtime(last)) if last else "لم يستخدم"
                text += f"{status} **{name}**\n"
                text += f"   📊 {usage} طلب | ❌ {errors} خطأ | 🕐 {last_str}\n"
    buttons = [
        InlineKeyboardButton("➕ إضافة مفتاح", callback_data="blogger_add_ai_key"),
    ]
    all_keys = dict(db_keys)
    for kid, kdata in env_keys.items():
        all_keys[kid] = kdata
    if all_keys:
        if db_keys:
            buttons.append(InlineKeyboardButton("🗑 حذف مفتاح", callback_data="blogger_del_ai_key"))
            buttons.append(InlineKeyboardButton("🔁 تبديل حالة", callback_data="blogger_toggle_ai_key"))
        for kid, kdata in all_keys.items():
            name = kdata.get("name", kid)[:12]
            buttons.append(InlineKeyboardButton(f"🧪 اختبار {name}", callback_data=f"blogger_test_ai_key_{kid}"))
    rows = _grid_buttons(buttons, 2)
    rows.append(_nav_row(uid, "blogger_menu"))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def blogger_add_ai_key_prompt(client, callback):
    from bot_core import user_states
    uid = callback.from_user.id
    user_states.pop(uid, None)
    user_states[uid] = {"state": "blogger_add_ai_key"}
    await safe_edit(callback, "أرسل مفتاح Gemini API:\n\nمثال: AIzaSy...", InlineKeyboardMarkup([_nav_row(uid, "blogger_ai_keys")]))


async def blogger_del_ai_key_menu(client, callback):
    uid = callback.from_user.id
    pub = get_publisher()
    keys = pub.db.get_all_ai_keys()
    if not keys:
        await callback.answer("لا توجد مفاتيح.", show_alert=True)
        return
    text = "🗑 **حذف مفتاح Gemini**\n\nاختر المفتاح للحذف:"
    buttons = []
    for kid, kdata in keys.items():
        name = kdata.get("name", kid)
        buttons.append([InlineKeyboardButton(f"🗑 {name}", callback_data=f"blogger_del_ai_key_{kid}")])
    buttons.append(_nav_row(uid, "blogger_ai_keys"))
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def blogger_confirm_del_ai_key(client, callback):
    key_id = callback.data.split("_")[-1]
    pub = get_publisher()
    pub.db.delete_ai_key(key_id)
    await callback.answer("✅ تم الحذف.")
    await blogger_ai_keys_menu(client, callback)


async def blogger_toggle_ai_key_menu(client, callback):
    uid = callback.from_user.id
    pub = get_publisher()
    keys = pub.db.get_all_ai_keys()
    if not keys:
        await callback.answer("لا توجد مفاتيح.", show_alert=True)
        return
    text = "🔁 **تبديل حالة مفتاح Gemini**\n\nاختر المفتاح لتفعيل/تعطيل:"
    buttons = []
    for kid, kdata in keys.items():
        name = kdata.get("name", kid)
        st = "✅" if kdata.get("enabled", True) else "❌"
        buttons.append([InlineKeyboardButton(f"{st} {name}", callback_data=f"blogger_toggle_ai_key_{kid}")])
    buttons.append(_nav_row(uid, "blogger_ai_keys"))
    await safe_edit(callback, text, InlineKeyboardMarkup(buttons))


async def blogger_confirm_toggle_ai_key(client, callback):
    key_id = callback.data.split("_")[-1]
    pub = get_publisher()
    keys = pub.db.get_all_ai_keys()
    current = keys.get(key_id, {}).get("enabled", True) if key_id in keys else True
    pub.db.set_ai_key_enabled(key_id, not current)
    await callback.answer("✅ تم التبديل.")
    await blogger_toggle_ai_key_menu(client, callback)


async def handle_blogger_text_input(client, message):
    from bot_core import is_admin, user_states
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    if uid not in user_states:
        return
    state = user_states[uid].get("state", "")
    if not state.startswith("blogger_"):
        return
    text = message.text.strip()
    pub = get_publisher()
    try:
        if state == "blogger_set_blog_id":
            pub.config.set("blog_id", text)
            await message.reply("✅ تم حفظ Blog ID.", reply_markup=InlineKeyboardMarkup([_nav_row(uid, "blogger_settings")]))
            user_states.pop(uid, None)
        elif state == "blogger_set_client_id":
            pub.config.set("client_id", text)
            await message.reply("✅ تم حفظ Client ID.", reply_markup=InlineKeyboardMarkup([_nav_row(uid, "blogger_settings")]))
            user_states.pop(uid, None)
        elif state == "blogger_set_client_secret":
            pub.config.set("client_secret", text)
            await message.reply("✅ تم حفظ Client Secret.", reply_markup=InlineKeyboardMarkup([_nav_row(uid, "blogger_settings")]))
            user_states.pop(uid, None)
        elif state == "blogger_set_refresh_token":
            pub.config.set("refresh_token", text)
            await message.reply("✅ تم حفظ Refresh Token.", reply_markup=InlineKeyboardMarkup([_nav_row(uid, "blogger_settings")]))
            user_states.pop(uid, None)
        elif state == "blogger_set_default_image":
            url = text.strip()
            pub.config.set("default_jobs_image", url)
            await message.reply("✅ تم حفظ صورة الوظائف الافتراضية." if url else "✅ تم إلغاء الصورة الافتراضية.", reply_markup=InlineKeyboardMarkup([_nav_row(uid, "blogger_set_default_image")]))
            user_states.pop(uid, None)
        elif state == "blogger_add_ai_key":
            name = text[:30]
            kid = str(int(time.time()))
            pub.db.add_ai_key(kid, {"name": name, "key": text})
            await message.reply(f"✅ تم إضافة المفتاح '{name}'.", reply_markup=InlineKeyboardMarkup([_nav_row(uid, "blogger_ai_keys")]))
            user_states.pop(uid, None)
        elif state == "blogger_add_channel_id":
            raw = text.strip()
            ch_id = raw
            ch_name = raw
            import re
            m = re.search(r'(?:https?://)?(?:t\.me/|telegram\.me/)(\w+)', raw)
            if m:
                ch_id = "@" + m.group(1)
                ch_name = ch_id
            elif raw.startswith("@"):
                ch_id = raw
                ch_name = raw
            try:
                from bot_core import user_client
                if user_client:
                    chat = await user_client.get_chat(ch_id)
                    ch_name = chat.title or chat.username or ch_id
                    ch_id = str(chat.id)
            except Exception as e:
                logger.warning(f"Blogger: could not resolve channel name for {ch_id}: {e}")
            user_states[uid] = {"state": "blogger_add_ch_section", "ch_id": ch_id, "ch_name": ch_name}
            bk = InlineKeyboardMarkup([_nav_row(uid, "blogger_channels")])
            await message.reply(f"✅ تم التعرف على القناة: {ch_name}\nأرسل اسم القسم في المدونة:\nمثال: وظائف, أخبار, مناقصات", reply_markup=bk)
        elif state == "blogger_add_ch_section":
            ch_id = user_states[uid].get("ch_id", "")
            ch_name = user_states[uid].get("ch_name", ch_id)
            section = text.strip()
            if not section:
                await message.reply("❌ اسم القسم لا يمكن أن يكون فارغاً.")
                return
            existing = pub.db.get_all_sections()
            found = any(sdata.get("name") == section for sdata in existing.values())
            if not found:
                sid = str(int(time.time()))
                pub.db.add_section(sid, {"name": section, "created_at": int(time.time())})
                logger.info(f"Blogger: auto-created section '{section}' (id={sid})")
            user_states[uid] = {"state": "blogger_add_ch_limit", "ch_id": ch_id, "ch_name": ch_name, "section": section}
            bk = InlineKeyboardMarkup([_nav_row(uid, "blogger_channels")])
            await message.reply(f"✅ القسم: {section}\nأرسل الحد اليومي لعدد المنشورات:\nمثال: 30", reply_markup=bk)
        elif state == "blogger_section_rename":
            sid = user_states[uid].get("sid", "")
            name = text.strip()
            if not name:
                await message.reply("❌ الاسم لا يمكن أن يكون فارغاً.")
                return
            pub.db.add_section(sid, {"name": name, "updated_at": int(time.time())})
            await message.reply(f"✅ تم تحديث اسم القسم إلى '{name}'.", reply_markup=InlineKeyboardMarkup([_nav_row(uid, f"blogger_section_detail_{sid}")]))
            user_states.pop(uid, None)
        elif state == "blogger_ch_sec_new_input":
            ch_id = user_states[uid].get("ch_id", "")
            name = text.strip()
            if not name:
                await message.reply("❌ اسم القسم لا يمكن أن يكون فارغاً.")
                return
            sid = str(int(time.time()))
            pub.db.add_section(sid, {"name": name, "created_at": int(time.time())})
            ch = pub.db.get_channel(ch_id)
            if ch:
                ch["section"] = name
                pub.db.save_channel(ch_id, ch)
            await message.reply(f"✅ تم إضافة القسم '{name}' وتعيينه للقناة.", reply_markup=InlineKeyboardMarkup([_nav_row(uid, f"blogger_edit_ch_{ch_id}")]))
            user_states.pop(uid, None)
        elif state == "blogger_ch_section_input":
            ch_id = user_states[uid].get("ch_id", "")
            section = text.strip()
            if not section:
                await message.reply("❌ اسم القسم لا يمكن أن يكون فارغاً.")
                return
            ch = pub.db.get_channel(ch_id)
            if ch:
                ch["section"] = section
                pub.db.save_channel(ch_id, ch)
            await message.reply("✅ تم تحديث القسم.", reply_markup=InlineKeyboardMarkup([_nav_row(uid, f"blogger_edit_ch_{ch_id}")]))
            user_states.pop(uid, None)
        elif state == "blogger_section_add_name":
            name = text.strip()
            if not name:
                await message.reply("❌ اسم القسم لا يمكن أن يكون فارغاً.")
                return
            sid = str(int(time.time()))
            pub.db.add_section(sid, {"name": name, "created_at": int(time.time())})
            await message.reply(f"✅ تم إنشاء القسم '{name}'.", reply_markup=InlineKeyboardMarkup([_nav_row(uid, "blogger_sections_main")]))
            user_states.pop(uid, None)
        elif state == "blogger_ch_limit_input":
            ch_id = user_states[uid].get("ch_id", "")
            try:
                limit = int(text.strip())
            except ValueError:
                await message.reply("❌ الرجاء إرسال رقم صحيح.\nمثال: 30")
                return
            ch = pub.db.get_channel(ch_id)
            if ch:
                ch["daily_limit"] = limit
                pub.db.save_channel(ch_id, ch)
            await message.reply(f"✅ تم تحديث الحد اليومي إلى {limit}.", reply_markup=InlineKeyboardMarkup([_nav_row(uid, f"blogger_edit_ch_{ch_id}")]))
            user_states.pop(uid, None)
        elif state == "blogger_ch_hours_input":
            ch_id = user_states[uid].get("ch_id", "")
            import re
            m = re.match(r'(\d+)\s*[-\s]\s*(\d+)', text.strip())
            if not m:
                await message.reply("❌ التنسيق خطأ. أرسل مثل: `9-23`")
                return
            start_h, end_h = int(m.group(1)), int(m.group(2))
            if not (0 <= start_h < 24 and 0 <= end_h < 24):
                await message.reply("❌ الساعات يجب أن تكون بين 0 و 23.")
                return
            ch = pub.db.get_channel(ch_id)
            if ch:
                ch["start_hour"] = start_h
                ch["end_hour"] = end_h
                pub.db.save_channel(ch_id, ch)
            await message.reply(f"✅ تم تحديث ساعات النشر: {start_h}:00 - {end_h}:00.", reply_markup=InlineKeyboardMarkup([_nav_row(uid, f"blogger_edit_ch_{ch_id}")]))
            user_states.pop(uid, None)
        elif state == "blogger_add_ch_limit":
            ch_id = user_states[uid].get("ch_id", "")
            ch_name = user_states[uid].get("ch_name", ch_id)
            section = user_states[uid].get("section", "عام")
            try:
                daily_limit = int(text.strip())
            except ValueError:
                await message.reply("❌ الرجاء إرسال رقم صحيح.\nمثال: 30")
                return
            channel_data = {
                "channel_id": ch_id,
                "name": ch_name,
                "section": section,
                "daily_limit": daily_limit,
                "enabled": True,
                "start_hour": 9,
                "end_hour": 23,
                "last_message_id": 0,
                "added_at": int(time.time()),
            }
            pub.db.save_channel(ch_id, channel_data)
            bk = InlineKeyboardMarkup([_nav_row(uid, "blogger_channels")])
            await message.reply(f"✅ تم إضافة القناة بنجاح:\n{ch_name} → {section} ({daily_limit}/يوم)", reply_markup=bk)
            user_states.pop(uid, None)
        elif state == "blogger_sec_add_label_input":
            sid = user_states[uid].get("sid", "")
            label = text.strip()
            if not label:
                await message.reply("❌ التسمية لا يمكن أن تكون فارغة.")
                return
            sections = pub.db.get_all_sections()
            sdata = sections.get(sid)
            if sdata:
                labels = sdata.get("labels", [])
                if label not in labels:
                    labels.append(label)
                sdata["labels"] = labels
                pub.db.add_section(sid, sdata)
            await message.reply(f"✅ تم إضافة التسمية '{label}'.", reply_markup=InlineKeyboardMarkup([_nav_row(uid, f"blogger_sec_labels_{sid}")]))
            user_states.pop(uid, None)
        elif state.startswith("blogger_article_edit_val_"):
            import re
            parts = state.split("_", 5)
            fingerprint = parts[-2]
            field = parts[-1]
            article = pub.db.get_article(fingerprint)
            if not article:
                await message.reply("❌ المقال غير موجود.")
                user_states.pop(uid, None)
                return
            article[field] = text.strip()
            pub.db.save_article(fingerprint, article)
            field_names = {
                "title": "العنوان", "body": "المحتوى", "introduction": "المقدمة",
                "conclusion": "الخاتمة", "summary": "الملخص", "section": "القسم",
            }
            far = field_names.get(field, field)
            await message.reply(f"✅ تم تحديث {far}.", reply_markup=InlineKeyboardMarkup([_nav_row(uid, f"blogger_article_detail_{fingerprint}")]))
            user_states.pop(uid, None)
        elif state == "blogger_article_add_title":
            title = text.strip()
            if not title:
                await message.reply("❌ العنوان لا يمكن أن يكون فارغاً.")
                return
            user_states[uid] = {"state": "blogger_article_add_body", "article_data": {"title": title}}
            await message.reply("✅ تم حفظ العنوان.\nأرسل محتوى المقال (النص الأساسي):", reply_markup=InlineKeyboardMarkup([_nav_row(uid, "blogger_articles")]))
        elif state == "blogger_article_add_body":
            body = text.strip()
            state_data = user_states.get(uid, {})
            article_data = state_data.get("article_data", {})
            article_data["body"] = body
            if not body:
                await message.reply("❌ المحتوى لا يمكن أن يكون فارغاً.")
                return
            pub2 = get_publisher()
            sections = pub2.db.get_all_sections()
            user_states[uid] = {"state": "blogger_article_add_section_pick", "article_data": article_data}
            if sections:
                buttons = []
                for sid, sdata in sections.items():
                    sname = sdata.get("name", sid)
                    buttons.append(InlineKeyboardButton(sname, callback_data=f"blogger_article_add_section_{sname}"))
                rows = _grid_buttons(buttons, 2)
                rows.append(_nav_row(uid, "blogger_articles"))
                await message.reply("اختر القسم:", reply_markup=InlineKeyboardMarkup(rows))
            else:
                article_data["section"] = "عام"
                user_states[uid] = {"state": "blogger_article_add_confirm", "article_data": article_data}
                text = (
                    "➕ **تأكيد المقال الجديد**\n\n"
                    f"العنوان: {article_data.get('title', '—')}\n"
                    f"القسم: عام\n"
                    f"طول المحتوى: {len(body)} حرف\n\n"
                    "هل تريد إضافة هذا المقال إلى Queue؟"
                )
                btns = [
                    InlineKeyboardButton("✅ إضافة إلى Queue", callback_data="blogger_article_add_finish"),
                    InlineKeyboardButton("❌ إلغاء", callback_data="blogger_articles"),
                ]
                await message.reply(text, reply_markup=InlineKeyboardMarkup([btns]))
        else:
            return
    except Exception as e:
        logger.exception(f"Blogger input error: {e}")
        await message.reply(f"❌ فشل: {e}", reply_markup=InlineKeyboardMarkup([_nav_row(uid, "blogger_menu")]))
        user_states.pop(uid, None)


# ──────────────────────────────────────────
# Article Management UI
# ──────────────────────────────────────────

STATUS_EMOJI = {
    "queued": "⏳", "published": "✅", "draft": "📄",
    "failed_permanent": "❌", "gemini_pending": "🤖",
    "processing": "⚙️", "discarded": "🗑", "processed": "📝",
}
STATUS_AR = {
    "all": "الكل", "queued": "في Queue", "published": "منشور",
    "draft": "مسودة", "processed": "معالج", "failed_permanent": "فاشل",
    "gemini_pending": "بإنتظار AI", "discarded": "مهمل",
}


def _article_summary(a: dict) -> str:
    title = (a.get("title") or "(بدون عنوان)")[:45]
    status = a.get("status", "unknown")
    emoji = STATUS_EMOJI.get(status, "❓")
    sec = a.get("section", "")
    sec_tag = f" [{sec}]" if sec else ""
    return f"{emoji} {title}{sec_tag}"


async def blogger_articles_menu(client, callback, page: int = 0):
    uid = callback.from_user.id
    _push_nav(uid, "blogger_articles")
    pub = get_publisher()
    filter_status = callback.data.split("_")[-1] if callback.data.startswith("blogger_articles_filter_") else "all"
    all_articles = pub.db.get_all_articles()
    if filter_status != "all":
        all_articles = [a for a in all_articles if a.get("status") == filter_status]
    all_articles.sort(key=lambda a: a.get("created_at", 0), reverse=True)
    per_page = 8
    total = len(all_articles)
    max_page = max(0, (total - 1) // per_page) if total else 0
    page = max(0, min(page, max_page))
    start, end = page * per_page, (page + 1) * per_page
    page_articles = all_articles[start:end]

    counts = {}
    for a in pub.db.get_all_articles():
        s = a.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1
    counts["all"] = sum(counts.values())

    text_parts = [f"📚 **إدارة المقالات**\n"]
    filter_labels = []
    for key in ("all", "processed", "queued", "published", "draft", "gemini_pending", "failed_permanent", "discarded"):
        c = counts.get(key, 0)
        if c or key == "all":
            ar = STATUS_AR.get(key, key)
            marker = "▫️" if key != filter_status else "🔹"
            filter_labels.append(f"{marker} {ar} ({c})")

    text_parts.append(" | ".join(filter_labels))
    text_parts.append(f"\n📄 الصفحة {page + 1}/{max_page + 1} — {total} مقال")

    if not page_articles:
        text_parts.append("\nلا توجد مقالات.")
    else:
        for i, a in enumerate(page_articles, 1):
            fp = a.get("fingerprint", "")
            summary = _article_summary(a)
            text_parts.append(f"\n{i}. {summary}")

    filter_row = []
    for key in ("all", "processed", "queued", "published"):
        ar = STATUS_AR.get(key, key)
        selected = "🔹" if key == filter_status else "▫️"
        filter_row.append(InlineKeyboardButton(f"{selected}{ar}", callback_data=f"blogger_articles_filter_{key}"))

    nav_row_btns = []
    if page > 0:
        nav_row_btns.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"blogger_articles_page_{page - 1}_{filter_status}"))
    if page < max_page:
        nav_row_btns.append(InlineKeyboardButton("التالي ➡️", callback_data=f"blogger_articles_page_{page + 1}_{filter_status}"))

    article_buttons = []
    for a in page_articles:
        fp = a.get("fingerprint", "")
        title = (a.get("title") or "(بدون عنوان)")[:35]
        article_buttons.append(InlineKeyboardButton(title, callback_data=f"blogger_article_detail_{fp}"))

    rows = _grid_buttons(filter_row, 4)
    if article_buttons:
        rows.extend([[b] for b in article_buttons])
    if nav_row_btns:
        rows.append(nav_row_btns)
    rows.append([
        InlineKeyboardButton("➕ إضافة مقال", callback_data="blogger_article_add"),
        InlineKeyboardButton("🔄 تحديث", callback_data=f"blogger_articles_refresh_{filter_status}"),
    ])
    if total > 0:
        sec_ar = STATUS_AR.get(filter_status, filter_status)
        rows.append([InlineKeyboardButton(f"🗑 حذف الكل ({sec_ar})", callback_data=f"blogger_articles_delete_all_{filter_status}")])
    rows.append(_nav_row(uid, "blogger_menu"))
    await safe_edit(callback, "\n".join(text_parts), InlineKeyboardMarkup(rows))


async def blogger_articles_refresh(client, callback):
    await blogger_articles_menu(client, callback)


async def blogger_articles_page(client, callback):
    import re
    parts = callback.data.split("_")
    page = int(parts[-2])
    filter_status = parts[-1] if len(parts) > 3 else "all"
    uid = callback.from_user.id
    _push_nav(uid, "blogger_articles")
    pub = get_publisher()
    all_articles = pub.db.get_all_articles()
    if filter_status != "all":
        all_articles = [a for a in all_articles if a.get("status") == filter_status]
    all_articles.sort(key=lambda a: a.get("created_at", 0), reverse=True)
    per_page = 8
    total = len(all_articles)
    max_page = max(0, (total - 1) // per_page) if total else 0
    page = max(0, min(page, max_page))
    start, end = page * per_page, (page + 1) * per_page
    page_articles = all_articles[start:end]

    counts = {}
    for a in pub.db.get_all_articles():
        s = a.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1
    counts["all"] = sum(counts.values())

    text_parts = [f"📚 **إدارة المقالات**\n"]
    filter_labels = []
    for key in ("all", "processed", "queued", "published", "draft", "gemini_pending", "failed_permanent", "discarded"):
        c = counts.get(key, 0)
        if c or key == "all":
            ar = STATUS_AR.get(key, key)
            marker = "▫️" if key != filter_status else "🔹"
            filter_labels.append(f"{marker} {ar} ({c})")
    text_parts.append(" | ".join(filter_labels))
    text_parts.append(f"\n📄 الصفحة {page + 1}/{max_page + 1} — {total} مقال")
    if not page_articles:
        text_parts.append("\nلا توجد مقالات.")
    else:
        for i, a in enumerate(page_articles, 1):
            summary = _article_summary(a)
            text_parts.append(f"\n{i}. {summary}")

    filter_row = []
    for key in ("all", "processed", "queued", "published"):
        ar = STATUS_AR.get(key, key)
        selected = "🔹" if key == filter_status else "▫️"
        filter_row.append(InlineKeyboardButton(f"{selected}{ar}", callback_data=f"blogger_articles_filter_{key}"))

    nav_row_btns = []
    if page > 0:
        nav_row_btns.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"blogger_articles_page_{page - 1}_{filter_status}"))
    if page < max_page:
        nav_row_btns.append(InlineKeyboardButton("التالي ➡️", callback_data=f"blogger_articles_page_{page + 1}_{filter_status}"))

    article_buttons = []
    for a in page_articles:
        fp = a.get("fingerprint", "")
        title = (a.get("title") or "(بدون عنوان)")[:35]
        article_buttons.append(InlineKeyboardButton(title, callback_data=f"blogger_article_detail_{fp}"))

    rows = _grid_buttons(filter_row, 4)
    if article_buttons:
        rows.extend([[b] for b in article_buttons])
    if nav_row_btns:
        rows.append(nav_row_btns)
    rows.append([
        InlineKeyboardButton("➕ إضافة مقال", callback_data="blogger_article_add"),
        InlineKeyboardButton("🔄 تحديث", callback_data=f"blogger_articles_refresh_{filter_status}"),
    ])
    if total > 0:
        sec_ar = STATUS_AR.get(filter_status, filter_status)
        rows.append([InlineKeyboardButton(f"🗑 حذف الكل ({sec_ar})", callback_data=f"blogger_articles_delete_all_{filter_status}")])
    rows.append(_nav_row(uid, "blogger_menu"))
    await safe_edit(callback, "\n".join(text_parts), InlineKeyboardMarkup(rows))


async def blogger_article_detail(client, callback):
    fingerprint = callback.data[len("blogger_article_detail_"):]
    uid = callback.from_user.id
    pub = get_publisher()
    article = pub.db.get_article(fingerprint)
    if not article:
        await callback.answer("المقال غير موجود.", show_alert=True)
        return
    title = article.get("title", "(بدون عنوان)")
    status = article.get("status", "unknown")
    emoji = STATUS_EMOJI.get(status, "❓")
    status_ar = STATUS_AR.get(status, status)
    section = article.get("section", "—")
    created = article.get("created_at", 0)
    if created:
        created_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(created))
    else:
        created_str = "—"
    processed_at = article.get("processed_at", 0)
    processed_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(processed_at)) if processed_at else "—"
    published_at = article.get("published_at", 0)
    published_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(published_at)) if published_at else "—"
    error = article.get("error", "")
    body_len = len(article.get("body", "") or "")

    text = (
        f"📄 **{title}**\n\n"
        f"الحالة: {emoji} {status_ar}\n"
        f"القسم: {section}\n"
        f"تاريخ الإنشاء: {created_str}\n"
    )
    if status in ("processed", "queued", "published", "draft"):
        text += f"تاريخ المعالجة: {processed_str}\n"
    if status in ("published", "draft"):
        text += f"تاريخ النشر: {published_str}\n"
    text += f"طول المحتوى: {body_len} حرف\n"
    if error:
        text += f"\n⚠️ خطأ: {error[:200]}"

    buttons = []
    if status in ("processed", "queued"):
        buttons.append(InlineKeyboardButton("📤 نشر الآن", callback_data=f"blogger_publish_now_{fingerprint}"))
        buttons.append(InlineKeyboardButton("📄 مسودة", callback_data=f"blogger_publish_draft_{fingerprint}"))
    if status == "queued":
        buttons.append(InlineKeyboardButton("⬆️ رفع", callback_data=f"blogger_article_move_up_{fingerprint}"))
        buttons.append(InlineKeyboardButton("⬇️ خفض", callback_data=f"blogger_article_move_down_{fingerprint}"))
    buttons.append(InlineKeyboardButton("👁 معاينة", callback_data=f"blogger_article_preview_{fingerprint}"))
    buttons.append(InlineKeyboardButton("✏️ تعديل", callback_data=f"blogger_article_edit_{fingerprint}"))
    buttons.append(InlineKeyboardButton("🗑 حذف", callback_data=f"blogger_article_delete_{fingerprint}"))
    buttons.append(InlineKeyboardButton("🔙 رجوع", callback_data="blogger_articles"))

    rows = _grid_buttons(buttons, 2)
    rows.append(_nav_row(uid, "blogger_articles"))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def blogger_article_preview(client, callback):
    fingerprint = callback.data[len("blogger_article_preview_"):]
    uid = callback.from_user.id
    pub = get_publisher()
    article = pub.db.get_article(fingerprint)
    if not article:
        await callback.answer("المقال غير موجود.", show_alert=True)
        return
    html = pub.processor.make_article_html(article)
    telegram_text = pub.processor.html_to_telegram(html)
    max_len = 4000
    if len(telegram_text) > max_len:
        telegram_text = telegram_text[:max_len] + "\n\n...(مختصر)"
    await safe_edit(callback, f"👁 **معاينة المقال**\n\n{telegram_text}", InlineKeyboardMarkup([_nav_row(uid, f"blogger_article_detail_{fingerprint}")]))


async def blogger_article_delete(client, callback):
    fingerprint = callback.data[len("blogger_article_delete_"):]
    uid = callback.from_user.id
    pub = get_publisher()
    article = pub.db.get_article(fingerprint)
    if not article:
        await callback.answer("المقال غير موجود.", show_alert=True)
        return
    title = article.get("title", "(بدون عنوان)")[:40]
    text = f"🗑 **تأكيد حذف المقال**\n\nهل أنت متأكد من حذف:\n「{title}」\n\nسيتم حذف المقال بشكل دائم."
    buttons = [
        InlineKeyboardButton("✅ نعم، احذف", callback_data=f"blogger_article_delete_confirm_{fingerprint}"),
        InlineKeyboardButton("❌ إلغاء", callback_data=f"blogger_article_detail_{fingerprint}"),
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup([buttons]))


async def blogger_article_delete_confirm(client, callback):
    fingerprint = callback.data[len("blogger_article_delete_confirm_"):]
    uid = callback.from_user.id
    pub = get_publisher()
    article = pub.db.get_article(fingerprint)
    if not article:
        await callback.answer("المقال غير موجود.", show_alert=True)
        return
    pub.db.delete_article(fingerprint)
    pub.db.remove_pending_by_fingerprint(fingerprint)
    pub.db.mark_published(fingerprint)
    await callback.answer("✅ تم حذف المقال.", show_alert=True)
    await blogger_articles_menu(client, callback)


async def blogger_articles_delete_all(client, callback):
    filter_status = callback.data[len("blogger_articles_delete_all_"):]
    uid = callback.from_user.id
    pub = get_publisher()
    logger.info(f"[1] Callback received: {callback.data}")
    logger.info(f"[2] Section extracted: {filter_status}")
    all_articles = pub.db.get_all_articles()
    if filter_status == "all":
        target = all_articles
    else:
        target = [a for a in all_articles if a.get("status") == filter_status]
    count = len(target)
    logger.info(f"[3] Articles found before confirm: {count}")
    if count > 0:
        first_5 = [a.get("fingerprint", "?")[:12] for a in target[:5]]
        logger.info(f"[6] First 5 IDs: {first_5}")
    if count == 0:
        await callback.answer("لا توجد مقالات للحذف.", show_alert=True)
        return
    sec_ar = STATUS_AR.get(filter_status, filter_status)
    text = (
        f"⚠️ **تأكيد حذف الكل**\n\n"
        f"هل أنت متأكد من حذف جميع المقالات الموجودة في:\n"
        f"**{sec_ar}** ؟\n\n"
        f"عدد المقالات: {count}\n\n"
        f"لن يمكن التراجع عن هذه العملية."
    )
    buttons = [
        InlineKeyboardButton("✅ نعم احذف", callback_data=f"blogger_articles_delete_all_confirm_{filter_status}"),
        InlineKeyboardButton("❌ إلغاء", callback_data="blogger_articles"),
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup([buttons]))


async def blogger_articles_delete_all_confirm(client, callback):
    filter_status = callback.data[len("blogger_articles_delete_all_confirm_"):]
    uid = callback.from_user.id
    logger.info(f"[1] Confirm Callback received: {callback.data}")
    logger.info(f"[4] Section after confirm: {filter_status}")
    pub = get_publisher()
    all_articles = pub.db.get_all_articles()
    logger.info(f"[5] Total articles in DB after reload: {len(all_articles)}")
    if filter_status == "all":
        target = all_articles
    else:
        target = [a for a in all_articles if a.get("status") == filter_status]
    count = len(target)
    logger.info(f"[7] Articles to delete: {count}")
    if count > 0:
        first_5 = [a.get("fingerprint", "?")[:12] for a in target[:5]]
        logger.info(f"[6] First 5 IDs: {first_5}")
    if count == 0:
        await callback.answer("لا توجد مقالات للحذف.", show_alert=True)
        return
    fingerprints = [a.get("fingerprint") for a in target if a.get("fingerprint")]
    logger.info(f"[8] Deleting {len(fingerprints)} articles...")
    for fp in fingerprints:
        pub.db.delete_article(fp)
        pub.db.remove_pending_by_fingerprint(fp)
    logger.info(f"[9] Database saved. Deleted: {len(fingerprints)}")
    queue_fps = set(a.get("fingerprint") for a in target if a.get("status") == "queued")
    if queue_fps:
        pub.scheduler._queue = [a for a in pub.scheduler._queue if a.get("fingerprint") not in queue_fps]
        logger.info(f"[10] Queue Reloaded: removed {len(queue_fps)} articles")
    else:
        logger.info(f"[10] No queued articles in target, Queue unchanged")
    logger.info(f"[11] UI Refreshed. section={filter_status} Deleted: {count}")
    sec_ar = STATUS_AR.get(filter_status, filter_status)
    await callback.answer(f"✅ تم حذف جميع المقالات.\nالقسم: {sec_ar}\nالعدد: {count}", show_alert=True)
    await blogger_articles_menu(client, callback)


async def blogger_article_edit(client, callback):
    fingerprint = callback.data[len("blogger_article_edit_"):]
    uid = callback.from_user.id
    pub = get_publisher()
    article = pub.db.get_article(fingerprint)
    if not article:
        await callback.answer("المقال غير موجود.", show_alert=True)
        return
    fields = {
        "title": "العنوان",
        "body": "المحتوى",
        "introduction": "المقدمة",
        "conclusion": "الخاتمة",
        "summary": "الملخص",
        "section": "القسم",
    }
    title = article.get("title", "(بدون عنوان)")[:30]
    text = f"✏️ **تعديل المقال**\n「{title}」\n\nاختر الحقل الذي تريد تعديله:"
    buttons = []
    for fkey, far in fields.items():
        current = article.get(fkey, "")
        preview = str(current)[:25] if current else "فارغ"
        buttons.append(InlineKeyboardButton(f"{far}: {preview}", callback_data=f"blogger_article_edit_field_{fingerprint}_{fkey}"))
    rows = _grid_buttons(buttons, 1)
    rows.append(_nav_row(uid, f"blogger_article_detail_{fingerprint}"))
    await safe_edit(callback, text, InlineKeyboardMarkup(rows))


async def blogger_article_edit_field(client, callback):
    import re
    parts = callback.data.split("_", 5)
    fingerprint = parts[-2]
    field = parts[-1]
    uid = callback.from_user.id
    pub = get_publisher()
    article = pub.db.get_article(fingerprint)
    if not article:
        await callback.answer("المقال غير موجود.", show_alert=True)
        return

    field_names = {
        "title": "العنوان", "body": "المحتوى", "introduction": "المقدمة",
        "conclusion": "الخاتمة", "summary": "الملخص", "section": "القسم",
    }
    far = field_names.get(field, field)
    current = article.get(field, "")
    current_preview = str(current)[:100] if current else "(فارغ)"

    from bot_core import user_states
    user_states[uid] = {"state": f"blogger_article_edit_val_{fingerprint}_{field}"}

    text = f"✏️ **تعديل {far}**\n\nالقيمة الحالية:\n`{current_preview}`\n\nأرسل القيمة الجديدة:"
    await safe_edit(callback, text, InlineKeyboardMarkup([_nav_row(uid, f"blogger_article_edit_{fingerprint}")]))


async def blogger_article_move_up(client, callback):
    fingerprint = callback.data[len("blogger_article_move_up_"):]
    uid = callback.from_user.id
    pub = get_publisher()
    await _reorder_article(pub, fingerprint, -1)
    await callback.answer("✅ تم رفع المقال.", show_alert=True)
    await blogger_article_detail(client, callback)


async def blogger_article_move_down(client, callback):
    fingerprint = callback.data[len("blogger_article_move_down_"):]
    uid = callback.from_user.id
    pub = get_publisher()
    await _reorder_article(pub, fingerprint, 1)
    await callback.answer("✅ تم خفض المقال.", show_alert=True)
    await blogger_article_detail(client, callback)


async def _reorder_article(pub, fingerprint: str, direction: int):
    queue = [a for a in pub.db.get_articles_by_status("queued")
             if a.get("fingerprint") and a.get("fingerprint") != fingerprint]
    article = pub.db.get_article(fingerprint)
    if not article:
        return
    idx = next((i for i, a in enumerate(queue) if a.get("fingerprint") == fingerprint), -1)
    if idx == -1:
        if direction == -1:
            queue.insert(0, article)
        else:
            queue.append(article)
    else:
        target = idx + direction
        if 0 <= target < len(queue):
            queue.pop(idx)
            queue.insert(target, article)
        elif target < 0:
            queue.insert(0, queue.pop(idx))
        else:
            queue.append(queue.pop(idx))
    for a in queue:
        a["status"] = "queued"
        pub.db.save_article(a.get("fingerprint", ""), a)
    pub.scheduler._queue = queue


async def blogger_article_add(client, callback):
    uid = callback.from_user.id
    from bot_core import user_states
    user_states[uid] = {"state": "blogger_article_add_title", "article_data": {}}
    text = "➕ **إضافة مقال جديد**\n\nأرسل عنوان المقال:"
    await safe_edit(callback, text, InlineKeyboardMarkup([_nav_row(uid, "blogger_articles")]))


async def blogger_article_add_section(client, callback):
    parts = callback.data.split("_", 1)
    section = parts[-1]
    uid = callback.from_user.id
    from bot_core import user_states
    state_data = user_states.get(uid, {})
    state_data["article_data"] = state_data.get("article_data", {})
    state_data["article_data"]["section"] = section
    state_data["state"] = "blogger_article_add_confirm"
    user_states[uid] = state_data
    pub = get_publisher()
    ad = state_data["article_data"]
    text = (
        "➕ **تأكيد المقال الجديد**\n\n"
        f"العنوان: {ad.get('title', '—')}\n"
        f"القسم: {ad.get('section', '—')}\n"
        f"طول المحتوى: {len(ad.get('body', ''))} حرف\n\n"
        "هل تريد إضافة هذا المقال إلى Queue؟"
    )
    buttons = [
        InlineKeyboardButton("✅ إضافة إلى Queue", callback_data="blogger_article_add_finish"),
        InlineKeyboardButton("❌ إلغاء", callback_data="blogger_articles"),
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup([buttons]))


async def blogger_article_add_finish(client, callback):
    uid = callback.from_user.id
    from bot_core import user_states
    state_data = user_states.get(uid, {})
    article_data = state_data.get("article_data", {})
    if not article_data.get("title"):
        await callback.answer("❌ العنوان مطلوب.", show_alert=True)
        return
    pub = get_publisher()
    import hashlib, time
    raw = article_data.get("title", "") + article_data.get("body", "")
    fingerprint = hashlib.md5(raw.encode("utf-8")).hexdigest()
    existing = pub.db.get_article(fingerprint)
    if existing:
        await callback.answer("❌ المقال موجود مسبقاً.", show_alert=True)
        return
    article = {
        "fingerprint": fingerprint,
        "title": article_data.get("title", ""),
        "body": article_data.get("body", ""),
        "section": article_data.get("section", "عام"),
        "status": "queued",
        "created_at": int(time.time()),
        "source_url": "",
        "media": [],
    }
    pub.db.save_article(fingerprint, article)
    pub.scheduler.add_to_queue(article)
    user_states.pop(uid, None)
    await callback.answer("✅ تم إضافة المقال إلى Queue!", show_alert=True)
    await blogger_articles_menu(client, callback)
    user_states.pop(uid, None)


BLOGGER_CALLBACKS = {
    "blogger_menu": blogger_main_menu,
    "blogger_settings": blogger_settings_menu,
    "blogger_channels": blogger_channels_menu,
    "blogger_ai_keys": blogger_ai_keys_menu,
    "blogger_stats": blogger_stats_menu,
    "blogger_stats_keys": blogger_stats_keys_menu,
    "blogger_logs": blogger_logs_menu,
    "blogger_test": blogger_test_handler,
    "blogger_toggle": blogger_toggle_handler,
    "blogger_toggle_draft": blogger_toggle_draft_handler,
    "blogger_set_blog_id": set_blog_id_prompt,
    "blogger_set_client_id": set_client_id_prompt,
    "blogger_set_client_secret": set_client_secret_prompt,
    "blogger_set_refresh_token": set_refresh_token_prompt,
    "blogger_set_default_image": set_default_image_prompt,
    "blogger_preview_image": blogger_preview_image_handler,
    "blogger_edit_image": blogger_edit_image_prompt,
    "blogger_add_image": blogger_add_image_prompt,
    "blogger_delete_image": blogger_delete_image_handler,
    "blogger_add_ai_key": blogger_add_ai_key_prompt,
    "blogger_toggle_ai_key": blogger_toggle_ai_key_menu,
    "blogger_del_ai_key": blogger_del_ai_key_menu,
    "blogger_add_channel": blogger_add_channel_prompt,
    "blogger_del_channel": blogger_del_channel_menu,
    "blogger_sections": blogger_sections_menu,
    "blogger_sections_main": blogger_sections_main_menu,
    "blogger_section_add": blogger_section_add_prompt,
    "blogger_advanced": blogger_advanced_menu,
    "blogger_schedule_info": blogger_schedule_info,
    "blogger_preview_last": blogger_preview_last,
    "blogger_articles": blogger_articles_menu,
    "blogger_article_add": blogger_article_add,
    "blogger_article_add_finish": blogger_article_add_finish,
}

DYNAMIC_PREFIXES = {
    "blogger_del_ai_key_": "blogger_confirm_del_ai_key",
    "blogger_toggle_ai_key_": "blogger_confirm_toggle_ai_key",
    "blogger_test_ai_key_": "blogger_test_ai_key_handler",
    "blogger_del_ch_": "blogger_confirm_del_channel",
    "blogger_edit_ch_": "blogger_edit_channel_menu",
    "blogger_toggle_ch_": "blogger_toggle_channel_handler",
    "blogger_process_": "blogger_manual_process",
    "blogger_preview_ch_": "blogger_preview_channel",
    "blogger_publish_now_": "blogger_publish_article_now",
    "blogger_publish_draft_": "blogger_publish_article_draft",
    "blogger_discard_": "blogger_discard_article",
    "blogger_ch_section_": "blogger_ch_section_prompt",
    "blogger_ch_sec_set_": "blogger_ch_sec_set",
    "blogger_ch_sec_new_": "blogger_ch_sec_new",
    "blogger_ch_limit_": "blogger_ch_limit_prompt",
    "blogger_ch_hours_": "blogger_ch_hours_prompt",
    "blogger_section_edit_": "blogger_section_edit",
    "blogger_section_del_": "blogger_section_del",
    "blogger_section_detail_": "blogger_section_detail_menu",
    "blogger_sec_pick_": "blogger_sec_pick",
    "blogger_sec_set_ch_": "blogger_sec_set_ch",
    "blogger_sec_labels_": "blogger_sec_labels_menu",
    "blogger_sec_add_label_": "blogger_sec_add_label_prompt",
    "blogger_sec_del_label_": "blogger_sec_del_label",
    "blogger_articles_filter_": "blogger_articles_menu",
    "blogger_articles_refresh_": "blogger_articles_refresh",
    "blogger_articles_page_": "blogger_articles_page",
    "blogger_article_detail_": "blogger_article_detail",
    "blogger_article_preview_": "blogger_article_preview",
    "blogger_article_delete_": "blogger_article_delete",
    "blogger_article_delete_confirm_": "blogger_article_delete_confirm",
    "blogger_article_edit_": "blogger_article_edit",
    "blogger_article_edit_field_": "blogger_article_edit_field",
    "blogger_article_move_up_": "blogger_article_move_up",
    "blogger_article_move_down_": "blogger_article_move_down",
    "blogger_article_add_section_": "blogger_article_add_section",
    "blogger_articles_delete_all_confirm_": "blogger_articles_delete_all_confirm",
    "blogger_articles_delete_all_": "blogger_articles_delete_all",
}


def register_blogger_handlers(app):
    # No separate MessageHandler needed: handle_text_input in bot_core.py
    # already delegates to handle_blogger_text_input for blogger_* states.
    # Registering a separate MessageHandler with the same filter would
    # BLOCK handle_text_input from receiving non-blogger states due to
    # Pyrogram's dispatch (break on first handler match within a group).
    logger.info("Blogger UI handlers registered")
