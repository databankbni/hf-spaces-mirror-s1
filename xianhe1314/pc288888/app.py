#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import asyncio
import logging
import threading
import random
import time
import re
from enum import Enum
from collections import Counter, defaultdict
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from pathlib import Path

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from telegram.error import BadRequest

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

# ==================== 配置 ====================
class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    API_ID = int(os.getenv("API_ID", "0"))
    API_HASH = os.getenv("API_HASH", "")
    DATA_API_URL = "https://pc28.help/api/kj.json?nbr=100"
    DATA_DIR = Path("data")
    SESSIONS_DIR = DATA_DIR / "sessions"
    USER_DATA_DIR = DATA_DIR / "users"
    LOGS_DIR = DATA_DIR / "logs"
    POLL_INTERVAL = 3

    @classmethod
    def init_dirs(cls):
        for d in [cls.DATA_DIR, cls.SESSIONS_DIR, cls.USER_DATA_DIR, cls.LOGS_DIR]:
            d.mkdir(parents=True, exist_ok=True)

Config.init_dirs()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger(__name__)

ALL_GROUPS = ['小单', '小双', '大单', '大双']

def get_type(s: int) -> str:
    return ('大' if s >= 14 else '小') + ('单' if s % 2 else '双')

# ==================== 全局引擎 ====================
class GlobalQuantEngine:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.initialized = False
            return cls._instance

    def __init__(self):
        if self.initialized:
            return
        self.initialized = True
        self.weights = {"freq": 0.3, "omission": 0.4, "markov": 0.3}
        self.trained_model_state = {}
        self.last_trained_issue = None

    def train_or_update(self, history: list):
        if not history:
            return
        latest_issue = history[0].get("issue")
        if latest_issue == self.last_trained_issue:
            return
        freq_counter = Counter(d['type'] for d in history)
        total = sum(freq_counter.values())
        omissions = {g: 0 for g in ALL_GROUPS}
        for idx, d in enumerate(history):
            t = d['type']
            if omissions[t] == 0:
                omissions[t] = idx
        markov_matrix = defaultdict(lambda: Counter())
        for i in range(len(history) - 1):
            curr = history[i+1]['type']
            nxt = history[i]['type']
            markov_matrix[curr][nxt] += 1
        self.trained_model_state = {
            "freq": freq_counter,
            "omissions": omissions,
            "markov": dict(markov_matrix),
            "total": total
        }
        self.last_trained_issue = latest_issue

    def predict(self, history: list) -> tuple:
        if not history:
            return "小单", {"kill": "小单"}
        self.train_or_update(history)
        scores = defaultdict(float)
        latest_type = history[0]['type']
        for g in ALL_GROUPS:
            f_count = self.trained_model_state.get("freq", {}).get(g, 0)
            tot = self.trained_model_state.get("total", 1)
            p_freq = f_count / tot if tot > 0 else 0.25
            omission_val = self.trained_model_state.get("omissions", {}).get(g, 0)
            m_score = self.trained_model_state.get("markov", {}).get(latest_type, {}).get(g, 0)
            score = (p_freq * self.weights["freq"] * 10) + (omission_val * self.weights["omission"]) + (m_score * self.weights["markov"])
            scores[g] = score
        sorted_scores = sorted(scores.items(), key=lambda x: x[1])
        return sorted_scores[0][0] if sorted_scores else "小单", {"kill": sorted_scores[0][0] if sorted_scores else "小单"}

global_engine = GlobalQuantEngine()

# ==================== 风控 ====================
class BetMethod(Enum):
    FLAT = "flat"
    MARTINGALE = "martingale"
    FIBONACCI = "fibonacci"

class RiskManager:
    FIB_SEQUENCE = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89]
    
    def __init__(self, base_amount: float = 100.0, daily_stop_loss: float = 3000.0,
                 daily_stop_profit: float = 5000.0, max_consecutive_losses: int = 6):
        self.base_amount = base_amount
        self.daily_stop_loss = daily_stop_loss
        self.daily_stop_profit = daily_stop_profit
        self.max_consecutive_losses = max_consecutive_losses
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.fib_index = 0
        self.is_fused = False
        self.total_bets = 0
        self.wins = 0
        self.losses = 0

    def get_amount(self) -> float:
        mult = min(2.0 ** self.consecutive_losses, 16.0)
        return self.base_amount * mult

    def can_bet(self) -> tuple:
        if self.is_fused:
            return False, "已触发熔断"
        if self.daily_pnl <= -self.daily_stop_loss:
            return False, "触及止损"
        if self.daily_pnl >= self.daily_stop_profit:
            return False, "触及止盈"
        return True, "正常"

    def on_settlement(self, is_win: bool, total_lines: int = 3):
        single_bet = self.get_amount()
        total_cost = single_bet * total_lines
        self.total_bets += 1
        if is_win:
            self.daily_pnl += (single_bet * 4.2) - total_cost
            self.consecutive_losses = 0
            self.wins += 1
            self.fib_index = max(0, self.fib_index - 2)
        else:
            self.daily_pnl -= total_cost
            self.consecutive_losses += 1
            self.losses += 1
            self.fib_index += 1
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.is_fused = True

    def get_win_rate(self) -> float:
        total = self.wins + self.losses
        return (self.wins / total * 100) if total > 0 else 0.0

    def to_dict(self):
        return {
            "base_amount": self.base_amount,
            "daily_stop_loss": self.daily_stop_loss,
            "daily_stop_profit": self.daily_stop_profit,
            "max_consecutive_losses": self.max_consecutive_losses,
            "daily_pnl": self.daily_pnl,
            "consecutive_losses": self.consecutive_losses,
            "fib_index": self.fib_index,
            "is_fused": self.is_fused,
            "total_bets": self.total_bets,
            "wins": self.wins,
            "losses": self.losses
        }

    @classmethod
    def from_dict(cls, data):
        rm = cls(
            base_amount=data.get("base_amount", 100.0),
            daily_stop_loss=data.get("daily_stop_loss", 3000.0),
            daily_stop_profit=data.get("daily_stop_profit", 5000.0),
            max_consecutive_losses=data.get("max_consecutive_losses", 6),
        )
        rm.daily_pnl = data.get("daily_pnl", 0.0)
        rm.consecutive_losses = data.get("consecutive_losses", 0)
        rm.fib_index = data.get("fib_index", 0)
        rm.is_fused = data.get("is_fused", False)
        rm.total_bets = data.get("total_bets", 0)
        rm.wins = data.get("wins", 0)
        rm.losses = data.get("losses", 0)
        return rm

# ==================== 用户状态 ====================
class UserState:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.file_path = Config.USER_DATA_DIR / f"{user_id}.json"
        self.lock = threading.Lock()
        self.is_logged_in = False
        self.is_active = False
        self.phone = ""
        self.groups = []
        self.client = None
        self.session_string = ""
        self.temp_phone_code_hash = None
        self.custom_delay = 12.0
        self.selected_modes = ["group"]
        self.selected_balls = ["a"]
        self.ball_bet_amount = 100.0
        self.extra_special_numbers = []
        self.extra_bauzi = False
        self.last_kill_target = ""
        self.last_betted_issue = ""
        self.last_settled_issue = ""
        self.last_bet_lines_count = 3
        self.history = []
        self.risk_mgr = RiskManager()
        self.load()

    def load(self):
        with self.lock:
            if self.file_path.exists():
                try:
                    with open(self.file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        self.is_logged_in = data.get("is_logged_in", False)
                        self.is_active = data.get("is_active", False)
                        self.phone = data.get("phone", "")
                        self.groups = data.get("groups", [])
                        self.custom_delay = data.get("custom_delay", 12.0)
                        self.selected_modes = data.get("selected_modes", ["group"])
                        self.selected_balls = data.get("selected_balls", ["a"])
                        self.ball_bet_amount = data.get("ball_bet_amount", 100.0)
                        self.extra_special_numbers = data.get("extra_special_numbers", [])
                        self.extra_bauzi = data.get("extra_bauzi", False)
                        self.last_betted_issue = data.get("last_betted_issue", "")
                        self.last_settled_issue = data.get("last_settled_issue", "")
                        self.session_string = data.get("session_string", "")
                        if "risk_mgr" in data:
                            self.risk_mgr = RiskManager.from_dict(data["risk_mgr"])
                except Exception as e:
                    logger.error(f"加载用户 {self.user_id} 失败: {e}")

    def save(self):
        with self.lock:
            try:
                Config.USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
                with open(self.file_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        "user_id": self.user_id,
                        "is_logged_in": self.is_logged_in,
                        "is_active": self.is_active,
                        "phone": self.phone,
                        "groups": self.groups,
                        "custom_delay": self.custom_delay,
                        "selected_modes": self.selected_modes,
                        "selected_balls": self.selected_balls,
                        "ball_bet_amount": self.ball_bet_amount,
                        "extra_special_numbers": self.extra_special_numbers,
                        "extra_bauzi": self.extra_bauzi,
                        "last_betted_issue": self.last_betted_issue,
                        "last_settled_issue": self.last_settled_issue,
                        "session_string": self.session_string,
                        "risk_mgr": self.risk_mgr.to_dict()
                    }, f, ensure_ascii=False)
            except Exception as e:
                logger.error(f"保存用户 {self.user_id} 失败: {e}")

    async def ensure_client_connected(self):
        if self.client is not None and self.client.is_connected():
            return True
        if not self.is_logged_in:
            return False
        try:
            if self.session_string:
                self.client = TelegramClient(StringSession(self.session_string), Config.API_ID, Config.API_HASH)
            else:
                session_path = Config.SESSIONS_DIR / f"user_{self.user_id}"
                self.client = TelegramClient(str(session_path), Config.API_ID, Config.API_HASH)
            await self.client.connect()
            if await self.client.is_user_authorized():
                self.session_string = self.client.session.save()
                self.save()
                return True
            self.is_logged_in = False
            self.save()
            return False
        except Exception as e:
            logger.error(f"连接失败: {e}")
            return False

    def get_modes_display(self) -> str:
        names = []
        if "group" in self.selected_modes:
            names.append("杀组")
        if "ball" in self.selected_modes:
            names.append("ABC球")
        return "+".join(names) if names else "未选择"

# ==================== 数据抓取 ====================
class DataFetcher:
    @staticmethod
    async def fetch_history_list():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(Config.DATA_API_URL, timeout=15) as resp:
                    if resp.status == 200:
                        return (await resp.json()).get("data", [])
        except Exception as e:
            logger.error(f"抓取异常: {e}")
            return []

    @staticmethod
    def parse_history(raw_data: list) -> list:
        parsed = []
        for item in raw_data:
            try:
                num_str = str(item.get("number", ""))
                nums = [int(d) for d in num_str if d.isdigit()]
                if len(nums) >= 3:
                    total = int(item.get("num", sum(nums[:3])))
                    combo = item.get("combination") or get_type(total)
                    parsed.append({"nums": nums[:3], "sum": total, "type": combo, "combination": combo, "issue": str(item.get("nbr", ""))})
            except:
                continue
        return parsed

    @staticmethod
    async def fetch_latest():
        raw = await DataFetcher.fetch_history_list()
        if raw:
            item = raw[0]
            num_str = str(item.get("number", ""))
            nums = [int(d) for d in num_str if d.isdigit()]
            total = int(item.get("num", sum(nums[:3]) if nums else 0))
            return {"issue_id": str(item.get("nbr")), "number_str": num_str, "num_value": total, "combination": str(item.get("combination", ""))}
        return None

# ==================== Bot ====================
class PC28Bot:
    def __init__(self):
        self.application = Application.builder().token(Config.BOT_TOKEN).build()
        self.users = {}
        self.user_login_states = {}
        self.last_issue_id = None
        self.is_running = True
        self._register_handlers()

    def get_user_state(self, uid: int) -> UserState:
        if uid not in self.users:
            self.users[uid] = UserState(uid)
        return self.users[uid]

    def _register_handlers(self):
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("cancel", self.cmd_cancel))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))

    def main_keyboard(self, u: UserState):
        status = "🟢 运行中" if u.is_active else "🔴 已停止"
        login = "🚪 登出" if u.is_logged_in else "🔑 登录"
        modes = u.get_modes_display()
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(f"状态: {status}", callback_data="noop"), InlineKeyboardButton(login, callback_data="login")],
            [InlineKeyboardButton("▶️ 启动", callback_data="start"), InlineKeyboardButton("⏹️ 停止", callback_data="stop")],
            [InlineKeyboardButton(f"⚙️ 模式: [{modes}]", callback_data="select_mode")],
            [InlineKeyboardButton("➕ 加群", callback_data="add_g"), InlineKeyboardButton("➖ 删群", callback_data="del_g")],
            [InlineKeyboardButton(f"⏱️ 延迟: {u.custom_delay}s", callback_data="set_delay"), InlineKeyboardButton("📊 战报", callback_data="stats")],
        ])

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        u = self.get_user_state(uid)
        await update.message.reply_text(
            f"🎰 PC28 全局量化挂机系统\n--------------------\n"
            f"状态: {'🟢 运行中' if u.is_active else '🔴 已停止'}\n"
            f"模式: {u.get_modes_display()}\n"
            f"群组: {len(u.groups)} 个\n"
            f"盈亏: {u.risk_mgr.daily_pnl:+.2f}",
            reply_markup=self.main_keyboard(u)
        )

    async def cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.user_login_states.pop(update.effective_user.id, None)
        await update.message.reply_text("✅ 已取消")

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        uid = query.from_user.id
        u = self.get_user_state(uid)
        data = query.data

        if data == "noop":
            return

        if data == "select_mode":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ 杀组模式" if "group" in u.selected_modes else "⬜ 杀组模式", callback_data="toggle_group")],
                [InlineKeyboardButton("✅ ABC杀球" if "ball" in u.selected_modes else "⬜ ABC杀球", callback_data="toggle_ball")],
                [InlineKeyboardButton("🔙 返回", callback_data="back_main")]
            ])
            await query.edit_message_text("选择模式(多选):", reply_markup=keyboard)
            return

        if data == "toggle_group":
            if "group" in u.selected_modes:
                if len(u.selected_modes) > 1:
                    u.selected_modes.remove("group")
            else:
                u.selected_modes.append("group")
            u.save()
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ 杀组模式" if "group" in u.selected_modes else "⬜ 杀组模式", callback_data="toggle_group")],
                [InlineKeyboardButton("✅ ABC杀球" if "ball" in u.selected_modes else "⬜ ABC杀球", callback_data="toggle_ball")],
                [InlineKeyboardButton("🔙 返回", callback_data="back_main")]
            ])
            await query.edit_message_text("选择模式(多选):", reply_markup=keyboard)
            return

        if data == "toggle_ball":
            if "ball" in u.selected_modes:
                if len(u.selected_modes) > 1:
                    u.selected_modes.remove("ball")
            else:
                u.selected_modes.append("ball")
            u.save()
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ 杀组模式" if "group" in u.selected_modes else "⬜ 杀组模式", callback_data="toggle_group")],
                [InlineKeyboardButton("✅ ABC杀球" if "ball" in u.selected_modes else "⬜ ABC杀球", callback_data="toggle_ball")],
                [InlineKeyboardButton("🔙 返回", callback_data="back_main")]
            ])
            await query.edit_message_text("选择模式(多选):", reply_markup=keyboard)
            return

        if data == "start":
            if not u.is_logged_in:
                await query.answer("请先登录!", alert=True)
                return
            if not u.groups:
                await query.answer("请绑定群组!", alert=True)
                return
            u.is_active = True
            u.save()
            await query.edit_message_text("✅ 已启动", reply_markup=self.main_keyboard(u))
            return

        if data == "stop":
            u.is_active = False
            u.save()
            await query.edit_message_text("⏹ 已停止", reply_markup=self.main_keyboard(u))
            return

        if data == "set_delay":
            self.user_login_states[uid] = "WAIT_DELAY"
            await query.message.reply_text(f"当前延迟: {u.custom_delay}s\n输入新延迟:")
            return

        if data == "add_g":
            self.user_login_states[uid] = "WAIT_GROUP"
            await query.message.reply_text("发送群组Username或ID:")
            return

        if data == "del_g":
            if not u.groups:
                await query.message.reply_text("无群组")
                return
            self.user_login_states[uid] = "WAIT_DEL_GROUP"
            await query.message.reply_text("发送序号删除:\n" + "\n".join([f"{i+1}. {g}" for i, g in enumerate(u.groups)]))
            return

        if data == "stats":
            rm = u.risk_mgr
            await query.message.reply_text(
                f"📊 战报\n"
                f"盈亏: {rm.daily_pnl:+.2f}\n"
                f"连败: {rm.consecutive_losses}\n"
                f"单注: {rm.get_amount():.2f}\n"
                f"胜率: {rm.get_win_rate():.1f}%"
            )
            return

        if data == "login":
            if u.is_logged_in:
                u.is_logged_in = False
                u.is_active = False
                if u.client:
                    try:
                        await u.client.disconnect()
                    except:
                        pass
                    u.client = None
                u.session_string = ""
                u.save()
                await query.edit_message_text("已登出", reply_markup=self.main_keyboard(u))
            else:
                self.user_login_states[uid] = "WAIT_PHONE"
                await query.message.reply_text("发送手机号(格式: +8613800000000):")
            return

        if data == "back_main":
            await query.edit_message_text(
                f"🏠 主菜单\n状态: {'🟢 运行中' if u.is_active else '🔴 已停止'}\n"
                f"模式: {u.get_modes_display()}\n"
                f"盈亏: {u.risk_mgr.daily_pnl:+.2f}",
                reply_markup=self.main_keyboard(u)
            )
            return

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        state = self.user_login_states.get(uid)
        u = self.get_user_state(uid)
        text = update.message.text.strip()

        if state == "WAIT_PHONE":
            u.phone = text
            try:
                client = TelegramClient(str(Config.SESSIONS_DIR / f"user_{uid}"), Config.API_ID, Config.API_HASH)
                await client.connect()
                req = await client.send_code_request(u.phone)
                u.client = client
                u.temp_phone_code_hash = req.phone_code_hash
                self.user_login_states[uid] = "WAIT_CODE"
                await update.message.reply_text("验证码已发送，请输入:")
            except Exception as e:
                await update.message.reply_text(f"发送失败: {e}")
                self.user_login_states.pop(uid, None)
            return

        if state == "WAIT_CODE":
            try:
                await u.client.sign_in(u.phone, text, phone_code_hash=u.temp_phone_code_hash)
                u.is_logged_in = True
                u.session_string = u.client.session.save()
                u.save()
                self.user_login_states.pop(uid, None)
                await update.message.reply_text("✅ 登录成功!", reply_markup=self.main_keyboard(u))
            except SessionPasswordNeededError:
                self.user_login_states[uid] = "WAIT_PASSWORD"
                await update.message.reply_text("请输入2FA密码:")
            except Exception as e:
                await update.message.reply_text(f"登录失败: {e}")
                self.user_login_states.pop(uid, None)
            return

        if state == "WAIT_PASSWORD":
            try:
                await u.client.sign_in(password=text)
                u.is_logged_in = True
                u.session_string = u.client.session.save()
                u.save()
                self.user_login_states.pop(uid, None)
                await update.message.reply_text("✅ 2FA通过!", reply_markup=self.main_keyboard(u))
            except Exception as e:
                await update.message.reply_text(f"密码错误: {e}")
            return

        if state == "WAIT_GROUP":
            if text not in u.groups:
                u.groups.append(text)
                u.save()
            await update.message.reply_text(f"✅ 已绑定: {text}", reply_markup=self.main_keyboard(u))
            self.user_login_states.pop(uid, None)
            return

        if state == "WAIT_DEL_GROUP":
            try:
                idx = int(text) - 1
                if 0 <= idx < len(u.groups):
                    removed = u.groups.pop(idx)
                    u.save()
                    await update.message.reply_text(f"✅ 已移除: {removed}", reply_markup=self.main_keyboard(u))
            except:
                pass
            self.user_login_states.pop(uid, None)
            return

        if state == "WAIT_DELAY":
            try:
                u.custom_delay = max(0, float(text))
                u.save()
                await update.message.reply_text(f"✅ 延迟: {u.custom_delay}s", reply_markup=self.main_keyboard(u))
            except:
                await update.message.reply_text("❌ 无效数字")
            self.user_login_states.pop(uid, None)
            return

    async def poll_api(self):
        logger.info("🔄 API轮询启动")
        while self.is_running:
            try:
                data = await DataFetcher.fetch_latest()
                if data and data['issue_id'] != self.last_issue_id:
                    self.last_issue_id = data['issue_id']
                    raw = await DataFetcher.fetch_history_list()
                    hist = DataFetcher.parse_history(raw)
                    if hist:
                        global_engine.train_or_update(hist)
                    for uid, u in self.users.items():
                        if hist:
                            u.history = hist
                        if u.is_logged_in:
                            if u.last_kill_target:
                                is_win = data['combination'] != u.last_kill_target
                                u.risk_mgr.on_settlement(is_win, u.last_bet_lines_count)
                                u.last_settled_issue = data['issue_id']
                                try:
                                    await self.application.bot.send_message(uid, f"{'🎉中奖' if is_win else '❌未中'} {data['issue_id']}\n开奖: {data['number_str']} -> {data['combination']}\n盈亏: {u.risk_mgr.daily_pnl:+.2f}")
                                except:
                                    pass
                            u.save()
                            if u.is_active:
                                await self.handle_bet(u, data['issue_id'])
            except Exception as e:
                logger.error(f"轮询异常: {e}")
            await asyncio.sleep(Config.POLL_INTERVAL)

    async def handle_bet(self, u: UserState, issue_id: str):
        if u.last_betted_issue == issue_id:
            return
        u.last_betted_issue = issue_id
        can_bet, reason = u.risk_mgr.can_bet()
        if not can_bet or not u.groups:
            return
        if not await u.ensure_client_connected():
            return
        lines = []
        if "group" in u.selected_modes:
            kill, _ = global_engine.predict(u.history)
            u.last_kill_target = kill
            amt = int(u.risk_mgr.get_amount())
            lines.extend([f"{g}{amt}" for g in ALL_GROUPS if g != kill])
        if not lines:
            return
        u.last_bet_lines_count = len(lines)
        bet_msg = "\n".join(lines)
        u.save()
        if u.custom_delay > 0:
            await asyncio.sleep(u.custom_delay)
        for g in u.groups:
            try:
                await u.client.send_message(g, bet_msg)
                logger.info(f"[用户 {u.user_id}] 向 {g} 下注 {issue_id}")
            except Exception as e:
                logger.error(f"发送失败: {e}")

    async def start(self):
        await self.application.initialize()
        await self.application.start()
        await self.application.bot.set_my_commands([("start", "启动主菜单"), ("cancel", "取消")])
        logger.info("✅ Bot 启动成功!")
        asyncio.create_task(self.poll_api())
        await self.application.updater.start_polling()
        await self.application.idle()

if __name__ == "__main__":
    bot = PC28Bot()
    asyncio.run(bot.start())