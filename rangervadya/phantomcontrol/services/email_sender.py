import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class EmailSender:
    def __init__(self):
        self.host = os.getenv('EMAIL_HOST')
        self.port = int(os.getenv('EMAIL_PORT', 465))
        self.user = os.getenv('EMAIL_USER')
        self.password = os.getenv('EMAIL_PASSWORD')
        self.recipient = os.getenv('EMAIL_RECIPIENT')
        self.use_ssl = os.getenv('EMAIL_USE_SSL', 'True').lower() == 'true'
        self.enabled = all([self.host, self.user, self.password, self.recipient])
        if not self.enabled:
            logger.warning("Email не настроен (проверьте переменные в .env)")

    def send_email(self, subject, body, html=False, attachments=None):
        if not self.enabled:
            return False
        msg = MIMEMultipart()
        msg['From'] = self.user
        msg['To'] = self.recipient
        msg['Subject'] = subject

        if html:
            msg.attach(MIMEText(body, 'html'))
        else:
            msg.attach(MIMEText(body, 'plain'))

        if attachments:
            for file_path in attachments:
                if os.path.exists(file_path):
                    with open(file_path, 'rb') as f:
                        part = MIMEBase('application', 'octet-stream')
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        part.add_header('Content-Disposition', f'attachment; filename={os.path.basename(file_path)}')
                        msg.attach(part)

        try:
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.host, self.port)
            else:
                server = smtplib.SMTP(self.host, self.port)
            server.login(self.user, self.password)
            server.sendmail(self.user, self.recipient, msg.as_string())
            server.quit()
            logger.info(f"Email отправлен: {subject}")
            return True
        except Exception as e:
            logger.error(f"Ошибка отправки email: {e}")
            return False

    def send_product_added(self, name, sku, price):
        subject = f"🟢 Новый товар добавлен: {name}"
        body = f"<b>{name}</b><br>SKU: {sku}<br>Цена: {price} ₽"
        self.send_email(subject, body, html=True)

    def send_product_sold(self, name, quantity, price):
        subject = f"🛒 Продажа: {name}"
        body = f"<b>{name}</b><br>Осталось: {quantity} шт.<br>Цена: {price} ₽"
        self.send_email(subject, body, html=True)

    def send_low_stock(self, name, quantity):
        subject = f"⚠️ Заканчивается: {name}"
        body = f"<b>{name}</b><br>Осталось: {quantity} шт."
        self.send_email(subject, body, html=True)

    def send_product_deleted(self, name, sku):
        subject = f"❌ Товар удалён: {name}"
        body = f"<b>{name}</b><br>SKU: {sku}"
        self.send_email(subject, body, html=True)