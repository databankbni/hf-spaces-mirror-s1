# -*- coding: utf-8 -*-
"""تحقق من نقل قسم النظام للقائمة الرئيسية فقط وعدم ظهوره في القنوات."""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "testhash")
os.environ.setdefault("BOT_TOKEN", "123:testtoken")
os.environ.setdefault("SESSION_STRING", "testsession")
os.environ.setdefault("MIDDLE_CHANNEL", "1000")
os.environ.setdefault("ADMINS", "111")

import bot_core
from tests.integration.test_channel_bot_verification import InMemoryDb


class FakeCallback:
    def __init__(self, data):
        self.data = data
        self.id = 111
        self.from_user = type("U", (), {"id": 111})()
        self.answer = AsyncMock()
        self.edit_message_text = AsyncMock()
        self.message = type("M", (), {"chat": type("C", (), {"id": 111})(), "text": ""})()


class TestSystemMoveToMainMenu(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fake_db = InMemoryDb()
        patcher = patch.object(bot_core, "db", self.fake_db)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_dispatcher_routes_system_menu(self):
        cb = FakeCallback("system_menu")
        with patch.object(bot_core, "safe_edit", new=AsyncMock()) as se:
            await bot_core.system_menu(None, cb)
        datas = [b.callback_data for row in se.await_args.args[2].inline_keyboard for b in row]
        for expected in ("full_check", "system_status", "ops_menu", "log_menu", "notifications_menu", "main_menu"):
            self.assertIn(expected, datas)

    async def test_dispatcher_routes_channel_to_post_settings(self):
        cb = FakeCallback("postset_111")
        with patch.object(bot_core, "safe_edit", new=AsyncMock()) as se:
            await bot_core.post_settings_menu(None, cb)
        datas = [b.callback_data for row in se.await_args.args[2].inline_keyboard for b in row]
        self.assertIn("testset_111", datas)

    async def test_main_keyboard_has_no_direct_system_tools(self):
        datas = [b.callback_data for row in bot_core.main_keyboard.inline_keyboard for b in row]
        self.assertIn("system_menu", datas)
        for tool in ("system_status", "full_check", "ops_menu", "log_menu", "notifications_menu"):
            self.assertNotIn(tool, datas)

    def test_callback_dispatcher_wires_system_menu(self):
        captured = []
        class FakeApp:
            def add_handler(self, handler):
                captured.append(handler)

        with patch.object(bot_core, "register_blogger_handlers", new=AsyncMock()):
            bot_core.register_bot_handlers(FakeApp())
        # التسجيل يضيف CallbackQueryHandler الذي يلتف حول الكلوزر
        import inspect
        from pyrogram.handlers import CallbackQueryHandler
        cb_handler = next(h for h in captured if isinstance(h, CallbackQueryHandler))
        src = inspect.getsource(cb_handler.callback)
        self.assertIn('data == "system_menu"', src)
        self.assertIn('await system_menu(client, callback)', src)


if __name__ == "__main__":
    unittest.main()