import os

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

BOT_WEBHOOK_URL = os.getenv("BOT_WEBHOOK_URL")

DEPARTMENTS = {
    "ИСТ": "ist-portfolio@urtisi.ru",
    "МЭС": "mec@urtisi.ru",
    "ИТиМС": "itims@urtisi.ru"
}

# ---------- Brevo (transactional email API) ----------
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "")
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "Portfolio Bot")

# Личная почта админа для тестовой отправки самому себе через /zip_build -> "Моя почта (тест)"
MY_EMAIL = os.getenv("MY_EMAIL", "")

# Ваш telegram id — используется как бутстрап для коллекции allowed_email_senders в БД,
# чтобы только вы могли отправлять архив на личную почту (см. db.is_allowed_email_sender)
MY_TG_ID = int(os.getenv("MY_TG_ID", "0")) or None