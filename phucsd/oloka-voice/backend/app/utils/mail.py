import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.config import settings

def send_verification_email(email: str, username: str, code: str):
    """
    Sends a verification email with the 6-digit OTP code to the user.
    If SMTP credentials are not configured, prints the code to stdout/console.
    """
    subject = "Xác thực tài khoản OmniVoice"
    body = f"""
    Chào {username},
    
    Cảm ơn bạn đã đăng ký tài khoản tại OmniVoice Gateway.
    Mã xác thực đăng ký tài khoản của bạn là:
    
    ============================
             {code}
    ============================
    
    Mã xác thực này sẽ hết hạn sau 10 phút.
    Nếu bạn không yêu cầu đăng ký này, vui lòng bỏ qua email.
    
    Trân trọng,
    Đội ngũ OmniVoice.
    """
    
    # Load dynamic SMTP settings from database
    from app.database import SessionLocal
    from app.models import SystemSetting
    
    smtp_host = settings.SMTP_HOST
    smtp_port = settings.SMTP_PORT
    smtp_username = settings.SMTP_USERNAME
    smtp_password = settings.SMTP_PASSWORD
    smtp_from = settings.SMTP_FROM
    
    db = SessionLocal()
    try:
        def get_setting(key: str, default_val):
            entry = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            if entry and entry.value.strip():
                return entry.value.strip()
            return default_val
            
        smtp_host = get_setting("smtp_host", smtp_host)
        
        smtp_port_str = get_setting("smtp_port", str(smtp_port))
        try:
            smtp_port = int(smtp_port_str)
        except ValueError:
            pass
            
        smtp_username = get_setting("smtp_username", smtp_username)
        smtp_password = get_setting("smtp_password", smtp_password)
        smtp_from = get_setting("smtp_from", smtp_from)
    except Exception as e:
        print(f"[SMTP config check] Error loading from DB: {e}")
    finally:
        db.close()
    
    # Check if credentials exist
    if not smtp_username or not smtp_password:
        print(f"\n=======================================================")
        print(f"[MAIL MOCK] Gửi mail xác thực tới: {email}")
        print(f"[MAIL MOCK] Tên tài khoản: {username}")
        print(f"[MAIL MOCK] Mã OTP đăng ký: {code}")
        print(f"=======================================================\n")
        return True

    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = smtp_from
        msg['To'] = email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # Connect to SMTP server
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()  # Upgrade connection to secure encrypted SSL/TLS
        server.login(smtp_username, smtp_password)
        server.sendmail(smtp_from, email, msg.as_string())
        server.quit()
        
        print(f"[SMTP] Đã gửi mail xác thực tới {email} thành công.")
        return True
    except Exception as e:
        print(f"[SMTP ERROR] Không thể gửi mail tới {email}: {e}")
        # Log mock fallback anyway so developer/tester doesn't get blocked
        print(f"\n=======================================================")
        print(f"[FALLBACK LOG] Gửi mail xác thực tới: {email}")
        print(f"[FALLBACK LOG] Tên tài khoản: {username}")
        print(f"[FALLBACK LOG] Mã OTP đăng ký: {code}")
        print(f"=======================================================\n")
        return False
