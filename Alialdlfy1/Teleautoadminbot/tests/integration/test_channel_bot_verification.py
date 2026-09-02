import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "testhash")
os.environ.setdefault("BOT_TOKEN", "123:testtoken")
os.environ.setdefault("SESSION_STRING", "testsession")
os.environ.setdefault("MIDDLE_CHANNEL", "1000")
os.environ.setdefault("ADMINS", "111")

_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from pyrogram.enums import ChatMemberStatus

import bot_core


class InMemoryDb:

    def __init__(self):
        self.channels = {
            "111": {"id": "111", "name": "قناة أ"},
        }

    def get_channel(self, ch_id):
        return self.channels.get(str(ch_id))

    def get_all_channels(self):
        return list(self.channels.values())

    def update_channel(self, ch_id, key, value):
        ch = self.channels.get(str(ch_id))
        if ch:
            ch[key] = value
            return True
        return False

    def add_channel(self, channel_id, **meta):
        cid = str(channel_id)
        if cid not in self.channels:
            self.channels[cid] = {"id": cid, **meta}
            return True
        return False

    def get_channel_blocked_words(self, ch_id):
        return []

    def get_channel_remove_terms(self, ch_id):
        return []

    def get_source_remove_terms(self, source_id):
        return []

    def get_source_remove_emoji(self, source_id):
        return False

    def get_channel_hashtags(self, ch_id):
        return self.channels.get(str(ch_id), {}).get("hashtags", [])

    def add_channel_hashtags(self, ch_id, terms):
        return {"added": 0, "exists": 0}

    def remove_channel_hashtags(self, ch_id, terms):
        return {"removed": 0, "missing": 0}

    def get_channel_quote_types(self, ch_id):
        return {
            "text": bool(self.channels.get(str(ch_id), {}).get("quote_text", True)),
            "photo": bool(self.channels.get(str(ch_id), {}).get("quote_photo", False)),
            "video": bool(self.channels.get(str(ch_id), {}).get("quote_video", False)),
            "album": bool(self.channels.get(str(ch_id), {}).get("quote_album", False)),
        }

    def set_channel_quote_type(self, ch_id, qtype, value):
        key = {"text": "quote_text", "photo": "quote_photo", "video": "quote_video", "album": "quote_album"}.get(qtype)
        if key:
            self.update_channel(ch_id, key, value)

    def get_channel_quote_publish(self, ch_id, default=False):
        return self.channels.get(str(ch_id), {}).get("quote_publish", default)

    def get_channel_quote_type(self, ch_id, qtype, default=False):
        return self.get_channel_quote_types(ch_id).get(qtype, default)

    def set_channel_bold_publish(self, ch_id, value):
        self.update_channel(ch_id, "bold_publish", value)

    def get_channel_bold_publish(self, ch_id):
        return self.channels.get(str(ch_id), {}).get("bold_publish", True)

    def set_channel_publish_delay(self, ch_id, value):
        self.update_channel(ch_id, "publish_delay", value)

    def get_channel_publish_delay(self, ch_id):
        return self.channels.get(str(ch_id), {}).get("publish_delay")

    def get_published_message_ids(self, ch_id, kind):
        return []

    def clear_published_message_ids(self, ch_id, kind, ids=None):
        return True

    def get_channel_config(self, ch_id):
        return {}

    def set_channel_title_quote(self, ch_id, enabled):
        return True

    def set_channel_signature_quote(self, ch_id, enabled):
        return True

    def get_channel_disable_preview(self, ch_id):
        return self.channels.get(str(ch_id), {}).get("disable_web_page_preview", False)

    def set_channel_disable_preview(self, ch_id, enabled):
        self.update_channel(ch_id, "disable_web_page_preview", enabled)

    def get_settings_clipboard(self):
        return getattr(self, "_clipboard", None)

    def set_settings_clipboard(self, clip):
        self._clipboard = clip

    NOTIFICATION_TYPES = {"errors": "الأخطاء"}

    def get_notification_settings(self):
        return {}

    def is_maintenance_mode(self):
        return False

    def set_maintenance_mode(self, enabled):
        return True

    def get_last_errors(self, limit=20):
        return []

    def clear_last_errors(self):
        return True

    def get_public_sources(self):
        return []

    def get_channel_delete_terms(self, ch_id):
        return []


class FakeMember:

    def __init__(self, status, can_post_messages=None, privileges=None):
        self.status = status
        self.can_post_messages = can_post_messages
        self.privileges = privileges


class FakePrivileges:

    def __init__(self, can_post_messages=True, can_edit_messages=True, can_delete_messages=True):
        self.can_post_messages = can_post_messages
        self.can_edit_messages = can_edit_messages
        self.can_delete_messages = can_delete_messages


class TestStatusHelpers(unittest.TestCase):

    def test_member_status_value_from_enum(self):
        self.assertEqual(bot_core.member_status_value(ChatMemberStatus.ADMINISTRATOR), "administrator")
        self.assertEqual(bot_core.member_status_value(ChatMemberStatus.OWNER), "owner")
        self.assertEqual(bot_core.member_status_value(ChatMemberStatus.MEMBER), "member")
        self.assertEqual(bot_core.member_status_value(ChatMemberStatus.LEFT), "left")
        self.assertEqual(bot_core.member_status_value(ChatMemberStatus.BANNED), "banned")
        self.assertEqual(bot_core.member_status_value(ChatMemberStatus.RESTRICTED), "restricted")

    def test_member_status_value_from_string_and_none(self):
        self.assertEqual(bot_core.member_status_value("administrator"), "administrator")
        self.assertEqual(bot_core.member_status_value(None), "")

    def test_is_bot_admin_status_valid(self):
        for s in ("administrator", "owner", "creator"):
            self.assertTrue(bot_core.is_bot_admin_status(s), s)

    def test_is_bot_admin_status_invalid(self):
        for s in ("member", "left", "banned", "restricted", "", "ChatMemberStatus.ADMINISTRATOR"):
            self.assertFalse(bot_core.is_bot_admin_status(s), s)


class TestBotCheckResultFormat(unittest.TestCase):

    def test_administrator_message(self):
        text = bot_core.format_bot_check_result("administrator", FakePrivileges())
        self.assertIn("✅ البوت مشرف في القناة", text)
        self.assertIn("administrator", text)
        self.assertIn("نشر الرسائل", text)

    def test_owner_message(self):
        text = bot_core.format_bot_check_result("owner")
        self.assertIn("✅ البوت مشرف في القناة", text)

    def test_member_message(self):
        text = bot_core.format_bot_check_result("member")
        self.assertIn("❌ البوت ليس مشرفاً في القناة", text)

    def test_restricted_message(self):
        text = bot_core.format_bot_check_result("restricted")
        self.assertIn("❌ البوت ليس مشرفاً في القناة", text)

    def test_left_message(self):
        text = bot_core.format_bot_check_result("left")
        self.assertIn("❌ البوت غير موجود داخل القناة.", text)

    def test_banned_message(self):
        text = bot_core.format_bot_check_result("banned")
        self.assertIn("❌ البوت محظور داخل القناة.", text)

    def test_error_message(self):
        text = bot_core.format_bot_check_result("", error="USER_NOT_PARTICIPANT")
        self.assertIn("❌ تعذر الوصول إلى القناة.", text)
        self.assertIn("USER_NOT_PARTICIPANT", text)


class TestChannelBotCheckHandler(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.fake_db = InMemoryDb()
        patcher_db = patch.object(bot_core, "db", self.fake_db)
        patcher_db.start()
        self.addCleanup(patcher_db.stop)
        self.fake_bot = AsyncMock()
        self.fake_bot.get_me = AsyncMock(return_value=MagicMock(id=12345))
        patcher_bot = patch.object(bot_core, "bot_client", self.fake_bot)
        patcher_bot.start()
        self.addCleanup(patcher_bot.stop)

    def _make_callback(self, data):
        cb = MagicMock()
        cb.data = data
        cb.from_user = MagicMock()
        cb.from_user.id = 111
        cb.answer = AsyncMock()
        return cb

    async def _run_with_status(self, status_enum, privileges=None):
        self.fake_bot.get_chat_member = AsyncMock(return_value=FakeMember(status_enum, privileges=privileges))
        with patch.object(bot_core, "safe_edit", new_callable=AsyncMock) as se:
            cb = self._make_callback("chbotcheck|111")
            await bot_core.channel_bot_check(None, cb)
            return se.await_args.args[1]

    async def test_administrator_shows_verified_with_permissions(self):
        self.fake_bot.get_chat_member = AsyncMock(return_value=FakeMember(ChatMemberStatus.ADMINISTRATOR, privileges=FakePrivileges(can_post_messages=False)))
        with patch.object(bot_core, "safe_edit", new_callable=AsyncMock) as se:
            cb = self._make_callback("chbotcheck|111")
            await bot_core.channel_bot_check(None, cb)
            text = se.await_args.args[1]
            self.assertIn("✅ البوت مشرف في القناة", text)
            self.assertIn("administrator", text)
            self.assertIn("نشر الرسائل: ❌", text)
        self.assertTrue(self.fake_db.channels["111"]["bot_admin"])
        self.assertEqual(self.fake_db.channels["111"]["bot_status"], "administrator")

    async def test_owner_shows_verified(self):
        self.fake_bot.get_chat_member = AsyncMock(return_value=FakeMember(ChatMemberStatus.OWNER))
        with patch.object(bot_core, "safe_edit", new_callable=AsyncMock) as se:
            cb = self._make_callback("chbotcheck|111")
            await bot_core.channel_bot_check(None, cb)
            text = se.await_args.args[1]
            self.assertIn("✅ البوت مشرف في القناة", text)
        self.assertTrue(self.fake_db.channels["111"]["bot_admin"])

    async def test_member_shows_not_admin(self):
        text = await self._run_with_status(ChatMemberStatus.MEMBER)
        self.assertIn("❌ البوت ليس مشرفاً في القناة", text)
        self.assertFalse(self.fake_db.channels["111"]["bot_admin"])

    async def test_left_shows_not_present(self):
        text = await self._run_with_status(ChatMemberStatus.LEFT)
        self.assertIn("❌ البوت غير موجود داخل القناة.", text)
        self.assertFalse(self.fake_db.channels["111"]["bot_admin"])

    async def test_banned_shows_banned(self):
        text = await self._run_with_status(ChatMemberStatus.BANNED)
        self.assertIn("❌ البوت محظور داخل القناة.", text)
        self.assertFalse(self.fake_db.channels["111"]["bot_admin"])

    async def test_restricted_shows_not_admin(self):
        text = await self._run_with_status(ChatMemberStatus.RESTRICTED)
        self.assertIn("❌ البوت ليس مشرفاً في القناة", text)

    async def test_channel_inaccessible_shows_real_reason(self):
        self.fake_bot.get_chat_member = AsyncMock(side_effect=Exception("CHAT_ID_INVALID: bad chat id"))
        with patch.object(bot_core, "safe_edit", new_callable=AsyncMock) as se:
            cb = self._make_callback("chbotcheck|111")
            await bot_core.channel_bot_check(None, cb)
            text = se.await_args.args[1]
            self.assertIn("❌ تعذر الوصول إلى القناة.", text)
            self.assertIn("CHAT_ID_INVALID", text)
        self.assertEqual(self.fake_db.channels["111"]["bot_status"], "unknown")


class TestChannelAdditionFlow(unittest.IsolatedAsyncioTestCase):
    """القناة تُضاف دائماً حتى لو لم يكن البوت مشرفاً أو تعذر الفحص."""

    def setUp(self):
        self.fake_db = InMemoryDb()
        patcher_db = patch.object(bot_core, "db", self.fake_db)
        patcher_db.start()
        self.addCleanup(patcher_db.stop)
        self.fake_bot = AsyncMock()
        self.fake_bot.get_me = AsyncMock(return_value=MagicMock(id=12345))
        patcher_bot = patch.object(bot_core, "bot_client", self.fake_bot)
        patcher_bot.start()
        self.addCleanup(patcher_bot.stop)
        self.user_states = {}
        patcher_states = patch.object(bot_core, "user_states", self.user_states)
        patcher_states.start()
        self.addCleanup(patcher_states.stop)

    def _make_message(self, text):
        msg = MagicMock()
        msg.text = text
        msg.chat = MagicMock()
        msg.chat.id = 1
        msg.from_user = MagicMock()
        msg.from_user.id = 111
        msg.reply = AsyncMock()
        return msg

    def _fake_chat(self, cid):
        chat = MagicMock()
        chat.id = cid
        chat.title = f"قناة {cid}"
        chat.username = ""
        chat.type = "channel"
        return chat

    async def test_channel_added_even_if_bot_not_admin(self):
        self.user_states[111] = {"state": "waiting_channel_id"}
        self.fake_bot.get_chat_member = AsyncMock(return_value=FakeMember(ChatMemberStatus.MEMBER))
        with patch.object(bot_core, "resolve_chat_info_timeout", new=AsyncMock(return_value=self._fake_chat(555))):
            with patch.object(bot_core, "show_channels_menu_from_message", new=AsyncMock()) as show_menu:
                msg = self._make_message("@test_channel")
                await bot_core.handle_text_input(None, msg)
        self.assertIn("555", self.fake_db.channels)
        ch = self.fake_db.channels["555"]
        self.assertFalse(ch["bot_admin"])
        self.assertEqual(ch["bot_status"], "member")
        report = msg.reply.await_args.args[0]
        self.assertIn("❌ البوت ليس مشرفاً", report)
        show_menu.assert_awaited()

    async def test_channel_added_even_if_bot_is_admin(self):
        self.user_states[111] = {"state": "waiting_channel_id"}
        self.fake_bot.get_chat_member = AsyncMock(return_value=FakeMember(ChatMemberStatus.ADMINISTRATOR))
        with patch.object(bot_core, "resolve_chat_info_timeout", new=AsyncMock(return_value=self._fake_chat(666))):
            with patch.object(bot_core, "show_channels_menu_from_message", new=AsyncMock()):
                msg = self._make_message("@admin_channel")
                await bot_core.handle_text_input(None, msg)
        self.assertIn("666", self.fake_db.channels)
        self.assertTrue(self.fake_db.channels["666"]["bot_admin"])
        report = msg.reply.await_args.args[0]
        self.assertIn("✅ البوت مشرف", report)

    async def test_channel_added_even_if_check_fails(self):
        self.user_states[111] = {"state": "waiting_channel_id"}
        self.fake_bot.get_chat_member = AsyncMock(side_effect=Exception("network error"))
        with patch.object(bot_core, "resolve_chat_info_timeout", new=AsyncMock(return_value=self._fake_chat(777))):
            with patch.object(bot_core, "show_channels_menu_from_message", new=AsyncMock()):
                msg = self._make_message("@offline_channel")
                await bot_core.handle_text_input(None, msg)
        self.assertIn("777", self.fake_db.channels)
        ch = self.fake_db.channels["777"]
        self.assertEqual(ch["bot_status"], "unknown")
        report = msg.reply.await_args.args[0]
        self.assertIn("تعذر التحقق من البوت", report)

    async def test_channel_added_even_if_bot_left(self):
        self.user_states[111] = {"state": "waiting_channel_id"}
        self.fake_bot.get_chat_member = AsyncMock(return_value=FakeMember(ChatMemberStatus.LEFT))
        with patch.object(bot_core, "resolve_chat_info_timeout", new=AsyncMock(return_value=self._fake_chat(888))):
            with patch.object(bot_core, "show_channels_menu_from_message", new=AsyncMock()):
                msg = self._make_message("@new_channel")
                await bot_core.handle_text_input(None, msg)
        self.assertIn("888", self.fake_db.channels)
        self.assertFalse(self.fake_db.channels["888"]["bot_admin"])

    async def test_save_tail_updates_channel_ui_without_error(self):
        self.fake_db.update_channel("111", "tail", "")
        self.user_states[111] = {"state": "waiting_tail", "ch_id": "111"}
        msg = self._make_message("توقيع جديد")
        await bot_core.handle_text_input(None, msg)
        self.assertEqual(self.fake_db.channels["111"]["tail"], "توقيع جديد")
        self.assertEqual(len(msg.reply.await_args_list), 2)
        markup = msg.reply.await_args_list[1].kwargs["reply_markup"]
        datas = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn("postset_111", datas)
        self.assertIn("srcset_111", datas)
        self.assertIn("genset_111", datas)
        self.assertNotIn("sysset_111", datas)


class TestChannelDisplayName(unittest.TestCase):

    def setUp(self):
        self.fake_db = InMemoryDb()
        patcher_db = patch.object(bot_core, "db", self.fake_db)
        patcher_db.start()
        self.addCleanup(patcher_db.stop)

    def test_dict_with_id_shows_name_and_id(self):
        text = bot_core.channel_display_name({"id": "111", "name": "قناة أ"})
        self.assertEqual(text, "قناة أ | ID: `111`")

    def test_dict_without_id_shows_name_only_no_dict(self):
        text = bot_core.channel_display_name({"name": "قديمة بدون id"})
        self.assertNotIn("{", text)
        self.assertNotIn("ID", text)
        self.assertIn("قديمة بدون id", text)

    def test_string_id_shows_id_only(self):
        text = bot_core.channel_display_name("555")
        self.assertEqual(text, "ID: `555`")


class TestPostSettingsMenus(unittest.IsolatedAsyncioTestCase):
    """أزرار إعدادات المنشورات تعمل في كل القنوات ولا تسقط على بيانات قديمة/كبيرة."""

    def setUp(self):
        self.fake_db = InMemoryDb()
        self.fake_db.channels["999"] = {"name": "قناة قديمة بدون id"}
        self.fake_db.channels["888"] = {"id": "888", "name": "قناة هاشتاكات", "hashtags": [f"#tag{i}" for i in range(3000)]}
        patcher_db = patch.object(bot_core, "db", self.fake_db)
        patcher_db.start()
        self.addCleanup(patcher_db.stop)
        self.user_states = {}
        patcher_states = patch.object(bot_core, "user_states", self.user_states)
        patcher_states.start()
        self.addCleanup(patcher_states.stop)

    def _make_callback(self, data):
        cb = MagicMock()
        cb.data = data
        cb.from_user = MagicMock()
        cb.from_user.id = 111
        cb.answer = AsyncMock()
        cb.edit_message_text = AsyncMock()
        return cb

    async def _run_edit(self, handler, data):
        cb = self._make_callback(data)
        with patch.object(bot_core, "safe_edit", new=AsyncMock()) as se:
            await handler(None, cb)
        return se, cb

    async def test_old_channel_without_id_key_opens_quote_menu(self):
        se, _ = await self._run_edit(bot_core.channel_quote_menu, "quotemenu_999")
        self.assertEqual(se.call_count, 1)
        text = se.await_args.args[1]
        self.assertIn("إعدادات الاقتباس", text)
        self.assertNotIn("{", text)
        self.assertNotIn("ID: `", text)

    async def test_quote_toggles_never_show_dictionary(self):
        for qtype in ("text", "photo", "video", "album"):
            se, cb = await self._run_edit(bot_core.toggle_channel_quote_type, f"toggleqtype|999|{qtype}")
            text = se.await_args.args[1]
            self.assertIn("إعدادات الاقتباس", text, qtype)
            self.assertNotIn("{", text, qtype)
            self.assertNotIn("ID: `", text, qtype)

    async def test_old_channel_without_id_key_opens_hashtags_menu(self):
        se, _ = await self._run_edit(bot_core.channel_hashtags_menu, "hashtags_999")
        self.assertEqual(se.call_count, 1)
        self.assertIn("لا توجد", se.await_args.args[1])

    async def test_old_channel_without_id_key_opens_purge_menus(self):
        for kind in ("text", "photo", "video"):
            se, _ = await self._run_edit(bot_core.purge_published_prompt, f"purgepub|999|{kind}")
            self.assertEqual(se.call_count, 1, kind)
            self.assertIn("تأكيد", se.await_args.args[1])

    async def test_hashtags_menu_truncates_long_list(self):
        se, _ = await self._run_edit(bot_core.channel_hashtags_menu, "hashtags_888")
        text = se.await_args.args[1]
        self.assertLessEqual(len(text), 4096)
        self.assertIn("هاشتاك إضافي", text)

    async def test_safe_edit_truncates_overlong_text(self):
        cb = self._make_callback("whatever")
        await bot_core.safe_edit(cb, "x" * 5000)
        called_text = cb.edit_message_text.await_args.args[0]
        self.assertLessEqual(len(called_text), 4096)
        cb.answer.assert_not_called()

    async def test_safe_edit_shows_alert_on_other_errors(self):
        cb = self._make_callback("whatever")
        cb.edit_message_text = AsyncMock(side_effect=Exception("MESSAGE_TOO_LONG"))
        await bot_core.safe_edit(cb, "نص")
        cb.answer.assert_awaited()
        self.assertEqual(cb.answer.await_args.kwargs.get("show_alert"), True)

    async def test_toggle_bold_stays_on_post_settings_page(self):
        se, cb = await self._run_edit(bot_core.toggle_channel_bold, "togglebold_111")
        self.assertEqual(self.fake_db.channels["111"]["bold_publish"], False)
        self.assertIn("إعدادات المنشورات", se.await_args.args[1])
        datas = [b.callback_data for row in se.await_args.args[2].inline_keyboard for b in row]
        self.assertIn("togglebold_111", datas)
        self.assertIn("quotemenu_111", datas)

    async def test_toggle_quote_type_stays_on_quote_page(self):
        se, cb = await self._run_edit(bot_core.toggle_channel_quote_type, "toggleqtype|111|text")
        self.assertEqual(self.fake_db.channels["111"]["quote_text"], False)
        self.assertIn("إعدادات الاقتباس", se.await_args.args[1])

    async def test_set_speed_stays_on_speed_page(self):
        se, cb = await self._run_edit(bot_core.set_channel_speed, "setspeed|111|5")
        self.assertEqual(self.fake_db.channels["111"]["publish_delay"], 5.0)
        self.assertIn("سرعة النشر", se.await_args.args[1])


class TestChannelSettingsNavigation(unittest.IsolatedAsyncioTestCase):
    """التحقق العملي من كل أزرار تنظيم إعدادات القناة الجديد."""

    def setUp(self):
        self.fake_db = InMemoryDb()
        patcher_db = patch.object(bot_core, "db", self.fake_db)
        patcher_db.start()
        self.addCleanup(patcher_db.stop)
        self.user_states = {}
        patcher_states = patch.object(bot_core, "user_states", self.user_states)
        patcher_states.start()
        self.addCleanup(patcher_states.stop)
        self.fake_verifier = MagicMock()
        self.fake_verifier.get_cached_verifications_for_channel = MagicMock(return_value={})
        patcher_ver = patch.object(bot_core, "verifier", self.fake_verifier)
        patcher_ver.start()
        self.addCleanup(patcher_ver.stop)
        self.fake_user_client = AsyncMock()
        self.fake_user_client.get_me = AsyncMock(return_value=MagicMock(id=1))
        patcher_user = patch.object(bot_core, "user_client", self.fake_user_client)
        patcher_user.start()
        self.addCleanup(patcher_user.stop)
        self.fake_bot = AsyncMock()
        self.fake_bot.get_me = AsyncMock(return_value=MagicMock(id=2))
        patcher_bot = patch.object(bot_core, "bot_client", self.fake_bot)
        patcher_bot.start()
        self.addCleanup(patcher_bot.stop)

    def _make_callback(self, data):
        cb = MagicMock()
        cb.data = data
        cb.from_user = MagicMock()
        cb.from_user.id = 111
        cb.answer = AsyncMock()
        cb.edit_message_text = AsyncMock()
        return cb

    async def _run(self, handler, data):
        cb = self._make_callback(data)
        with patch.object(bot_core, "safe_edit", new=AsyncMock()) as se:
            await handler(None, cb)
        return se, cb

    def _datas(self, se):
        return [b.callback_data for row in se.await_args.args[2].inline_keyboard for b in row]

    async def test_hub_has_three_categories(self):
        se, _ = await self._run(bot_core.channel_settings, "ch_111")
        datas = self._datas(se)
        self.assertIn("postset_111", datas)
        self.assertIn("srcset_111", datas)
        self.assertIn("genset_111", datas)
        self.assertNotIn("sysset_111", datas)
        self.assertIn("menu_channels", datas)

    async def test_post_settings_has_all_buttons(self):
        se, _ = await self._run(bot_core.post_settings_menu, "postset_111")
        datas = self._datas(se)
        for expected in ("togglebold_111", "tails_111", "quotemenu_111", "hashtags_111", "speedmenu_111", "purgepage_111", "chwords|111", "chdelterms|111", "chlinks|111", "ch_preview_111"):
            self.assertIn(expected, datas)
        self.assertIn("ch_111", datas)

    async def test_post_sub_pages_open_and_back_to_postset(self):
        cases = [
            ("tails_111", bot_core.tail_settings_menu, "إعدادات التوقيع", "postset_111"),
            ("quotemenu_111", bot_core.channel_quote_menu, "إعدادات الاقتباس", "postset_111"),
            ("hashtags_111", bot_core.channel_hashtags_menu, "هاشتاكات", "postset_111"),
            ("speedmenu_111", bot_core.channel_speed_menu, "سرعة النشر", "postset_111"),
            ("purgepage_111", bot_core.purge_published_menu, "حذف المنشورات", "postset_111"),
            ("chwords|111", bot_core.channel_blocked_words_menu, "الكلمات المحظورة", "postset_111"),
            ("chdelterms|111", bot_core.channel_delete_terms_menu, "الكلمات المحذوفة", "postset_111"),
            ("chlinks|111", bot_core.channel_links_menu, "إدارة الروابط", "postset_111"),
        ]
        for data, handler, text_part, back in cases:
            se, _ = await self._run(handler, data)
            self.assertIn(text_part, se.await_args.args[1], data)
            self.assertIn(back, self._datas(se), data)

    async def test_quote_page_has_all_six_toggles(self):
        se, _ = await self._run(bot_core.channel_quote_menu, "quotemenu_111")
        datas = self._datas(se)
        for expected in ("ch_titlequote_111", "toggleqtype|111|text", "toggleqtype|111|photo", "toggleqtype|111|video", "toggleqtype|111|album", "ch_sigquote_111"):
            self.assertIn(expected, datas)

    async def test_quote_title_toggle_stays_on_quote_page(self):
        se, _ = await self._run(bot_core.toggle_channel_title_quote, "ch_titlequote_111")
        self.assertIn("إعدادات الاقتباس", se.await_args.args[1])
        self.assertIn("ch_titlequote_111", self._datas(se))

    async def test_quote_signature_toggle_stays_on_quote_page(self):
        se, _ = await self._run(bot_core.toggle_channel_signature_quote, "ch_sigquote_111")
        self.assertIn("إعدادات الاقتباس", se.await_args.args[1])
        self.assertIn("ch_sigquote_111", self._datas(se))

    async def test_preview_toggle_stays_on_post_settings(self):
        se, _ = await self._run(bot_core.toggle_channel_preview, "ch_preview_111")
        self.assertIn("إعدادات المنشورات", se.await_args.args[1])

    async def test_purge_prompt_back_to_purge_page(self):
        se, _ = await self._run(bot_core.purge_published_prompt, "purgepub|111|text")
        datas = self._datas(se)
        self.assertIn("confirmpurge|111|text", datas)
        self.assertIn("purgepage_111", datas)

    async def test_purge_page_has_all_four_kinds(self):
        se, _ = await self._run(bot_core.purge_published_menu, "purgepage_111")
        datas = self._datas(se)
        for kind in ("text", "photo", "video", "album"):
            self.assertIn(f"purgepub|111|{kind}", datas)

    async def test_genset_page_has_all_buttons(self):
        se, _ = await self._run(bot_core.general_settings_menu, "genset_111")
        datas = self._datas(se)
        for expected in ("genset_summary_111", "genset_copy_111", "genset_paste_111", "genset_reset_111", "chbotcheck|111", "toggle_111", "assign_sessions_111", "assign_bots_111", "assign_ai_111", "assign_websites_111", "delchannel_111"):
            self.assertIn(expected, datas)
        self.assertIn("ch_111", datas)

    async def test_genset_subpages_back_to_genset(self):
        self.fake_db.set_settings_clipboard({"bold_publish": False})
        cases = [
            ("genset_summary_111", bot_core.general_settings_summary),
            ("genset_paste_111", bot_core.general_settings_paste),
            ("genset_reset_111", bot_core.general_settings_reset),
            ("delchannel_111", bot_core.delete_channel_prompt),
        ]
        for data, handler in cases:
            se, _ = await self._run(handler, data)
            self.assertIn("genset_111", self._datas(se), data)

    async def test_genset_confirms_stay_in_genset(self):
        self.fake_db.set_settings_clipboard({"bold_publish": False})
        se, _ = await self._run(bot_core.general_settings_paste_confirm, "genset_paste_confirm_111")
        self.assertIn("الإعدادات العامة", se.await_args.args[1])
        se, _ = await self._run(bot_core.general_settings_reset_confirm, "genset_reset_confirm_111")
        self.assertIn("الإعدادات العامة", se.await_args.args[1])

    async def test_assign_menu_back_to_genset(self):
        se, _ = await self._run(bot_core.assign_resource_menu, "assign_bots_111")
        self.assertIn("genset_111", self._datas(se))

    async def test_system_menu_global_has_all_items(self):
        se, _ = await self._run(bot_core.system_menu, "system_menu")
        datas = self._datas(se)
        for expected in ("full_check", "system_status", "ops_menu", "log_menu", "notifications_menu"):
            self.assertIn(expected, datas)
        self.assertIn("main_menu", datas)

    async def test_testset_is_inside_post_settings(self):
        se, _ = await self._run(bot_core.post_settings_menu, "postset_111")
        self.assertIn("testset_111", self._datas(se))

    async def test_testset_back_to_post_settings(self):
        se, _ = await self._run(bot_core.test_settings_menu, "testset_111")
        self.assertIn("postset_111", self._datas(se))

    async def test_system_pages_global_back_to_system_menu(self):
        se, _ = await self._run(bot_core.system_status_menu, "system_status")
        self.assertIn("system_menu", self._datas(se))
        se, _ = await self._run(bot_core.operations_menu, "ops_menu")
        self.assertIn("system_menu", self._datas(se))
        se, _ = await self._run(bot_core.log_management_menu, "log_menu")
        self.assertIn("system_menu", self._datas(se))
        se, _ = await self._run(bot_core.notifications_menu, "notifications_menu")
        self.assertIn("system_menu", self._datas(se))

    async def test_system_menu_in_main_keyboard(self):
        datas = [b.callback_data for row in bot_core.main_keyboard.inline_keyboard for b in row]
        self.assertIn("system_menu", datas)
        self.assertNotIn("sysset_", "".join(datas))
        for legacy in ("system_status", "full_check", "ops_menu", "log_menu", "notifications_menu"):
            self.assertNotIn(legacy, datas)

    async def test_full_check_global_keeps_context(self):
        with patch.object(bot_core, "warm_middle_peer", new=AsyncMock()), \
             patch.object(bot_core, "hydrate_publish_channel", new=AsyncMock()), \
             patch.object(bot_core, "hydrate_source_channel", new=AsyncMock()):
            se, _ = await self._run(bot_core.full_check_menu, "full_check")
        datas = self._datas(se)
        self.assertIn("system_status", datas)

    async def test_ops_toggle_stays_in_ops_from_channel(self):
        self.fake_db.channels["111"]["ignore_short_posts"] = True
        self.fake_db.get_channel_ignore_short_posts = lambda ch_id: bool(self.fake_db.channels.get(str(ch_id), {}).get("ignore_short_posts", getattr(self.fake_db, "global_short_posts", False)))
        self.fake_db.set_channel_ignore_short_posts = lambda ch_id, enabled: self.fake_db.channels[str(ch_id)].__setitem__("ignore_short_posts", bool(enabled))
        self.fake_db.global_short_posts = False

        se, _ = await self._run(
            bot_core.toggle_short_posts_filter,
            "toggle_short_posts|111",
        )
        self.assertEqual(self.fake_db.channels["111"]["ignore_short_posts"], False)
        self.assertIn("إعدادات المنشورات", se.await_args.args[1])
        buttons = [button for row in se.await_args.args[2].inline_keyboard for button in row]
        short_button = next(
            button for button in buttons
            if button.callback_data == "toggle_short_posts|111"
        )
        self.assertIn("📝 النصوص القصيرة: ❌ إيقاف", short_button.text)
        self.assertEqual(short_button.callback_data, "toggle_short_posts|111")
        self.assertFalse(bot_core.should_ignore_short_post_for_channel("one two", "111"))

        self.fake_db.global_short_posts = True
        self.assertFalse(bot_core.should_ignore_short_post_for_channel("one two", "111"))

        se, _ = await self._run(
            bot_core.toggle_short_posts_filter,
            "toggle_short_posts|111",
        )
        self.assertEqual(self.fake_db.channels["111"]["ignore_short_posts"], True)
        self.assertIn("إعدادات المنشورات", se.await_args.args[1])
        buttons = [button for row in se.await_args.args[2].inline_keyboard for button in row]
        short_button = next(
            button for button in buttons
            if button.callback_data == "toggle_short_posts|111"
        )
        self.assertIn("📝 النصوص القصيرة: ✅ تشغيل", short_button.text)
        self.assertEqual(short_button.callback_data, "toggle_short_posts|111")

    async def test_link_filter_toggle_stays_on_links_page(self):
        se, _ = await self._run(bot_core.toggle_channel_link_filter, "chlinktg|111")
        self.assertIn("إدارة الروابط", se.await_args.args[1])
        self.assertEqual(self.fake_db.channels["111"]["link_remove_tg"], True)

    async def test_bold_toggle_saves_and_stays_on_post_settings(self):
        se, _ = await self._run(bot_core.toggle_channel_bold, "togglebold_111")
        self.assertEqual(self.fake_db.channels["111"]["bold_publish"], False)
        self.assertIn("إعدادات المنشورات", se.await_args.args[1])
        self.assertIn("togglebold_111", self._datas(se))

    async def test_speed_save_stays_on_speed_page(self):
        se, _ = await self._run(bot_core.set_channel_speed, "setspeed|111|5")
        self.assertEqual(self.fake_db.channels["111"]["publish_delay"], 5.0)
        self.assertIn("سرعة النشر", se.await_args.args[1])


if __name__ == "__main__":
    unittest.main()
