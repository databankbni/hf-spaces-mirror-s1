"""
Отправка писем с вложением (архивом) через Brevo (бывш. Sendinblue) transactional email API.

Требуемые переменные в config.py:
    BREVO_API_KEY       — API-ключ Brevo (Settings -> SMTP & API -> API Keys)
    BREVO_SENDER_EMAIL   — email отправителя, подтверждённый в Brevo (Senders)
    BREVO_SENDER_NAME    — отображаемое имя отправителя (например, "Portfolio Bot")
    MY_EMAIL             — личная почта админа для тестовой отправки самому себе
    MY_TG_ID             — telegram id админа (используется как бутстрап для коллекции
                            allowed_email_senders в БД — см. db.py)
"""
import base64
import logging

import aiohttp

import config

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


async def send_email_with_attachment(
    to_email: str,
    subject: str,
    body_text: str,
    attachment_path: str,
    attachment_filename: str,
    to_name: str = "",
) -> tuple[bool, str]:
    """
    Отправляет письмо с одним вложением через Brevo API.
    Возвращает (успех: bool, сообщение_об_ошибке_или_пусто: str).
    """
    try:
        with open(attachment_path, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        return False, f"Не удалось прочитать файл вложения: {e}"

    payload = {
        "sender": {
            "name": getattr(config, "BREVO_SENDER_NAME", "Portfolio Bot"),
            "email": config.BREVO_SENDER_EMAIL,
        },
        "to": [{"email": to_email, "name": to_name or to_email}],
        "subject": subject,
        "htmlContent": f"<p>{body_text}</p>",
        "attachment": [
            {"content": content_b64, "name": attachment_filename}
        ],
    }
    headers = {
        "api-key": config.BREVO_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(BREVO_API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                text = await resp.text()
                if resp.status in (200, 201):
                    logging.info(f"📧 Письмо успешно отправлено на {to_email} (тема: {subject})")
                    return True, ""
                logging.error(f"📧 Brevo API ошибка {resp.status}: {text}")
                return False, f"Brevo API вернул {resp.status}: {text}"
    except Exception as e:
        logging.error(f"📧 Ошибка отправки письма через Brevo: {e}")
        return False, str(e)


async def send_multiple_attachments(
    to_email: str,
    to_name: str,
    items: list[tuple[str, str, str]],
) -> list[tuple[str, bool, str]]:
    """
    Отправляет несколько писем (по одному на каждый архив) последовательно.
    items — список кортежей (путь_к_файлу, имя_файла, тема_письма).
    Возвращает список (тема, успех, ошибка) по каждому письму.
    """
    results = []
    for file_path, file_name, subject in items:
        ok, err = await send_email_with_attachment(
            to_email=to_email,
            subject=subject,
            body_text=f"Во вложении архив «{file_name}».",
            attachment_path=file_path,
            attachment_filename=file_name,
            to_name=to_name,
        )
        results.append((subject, ok, err))
    return results