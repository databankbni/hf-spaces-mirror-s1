import os
from core.secrets.compat import env_or_secret

API_ID = int(env_or_secret("API_ID", default="0") or "0")
API_HASH = env_or_secret("API_HASH", default="") or ""
BOT_TOKEN = env_or_secret("BOT_TOKEN", default="") or ""
SESSION_STRING = env_or_secret("SESSION_STRING", default="") or ""

# قراءة قائمة الأدمن من متغير ADMINS (أرقام مفصولة بفواصل)
admins_str = env_or_secret("ADMINS", default="") or ""
ADMINS = [int(x.strip()) for x in admins_str.split(",") if x.strip()]

# إذا لم يُضبط ADMINS نحاول استخدام ADMIN_ID القديم (للتوافق)
if not ADMINS:
    old_admin = env_or_secret("ADMIN_ID", default="") or ""
    if old_admin:
        ADMINS = [int(old_admin)]

MIDDLE_CHANNEL = int(env_or_secret("MIDDLE_CHANNEL", default="0") or "0")

if not all([API_ID, API_HASH, BOT_TOKEN, SESSION_STRING, MIDDLE_CHANNEL]):
    raise ValueError("جميع المتغيرات الأساسية مطلوبة")
if not ADMINS:
    raise ValueError("يجب تعيين ADMINS على الأقل معرف أدمن واحد")