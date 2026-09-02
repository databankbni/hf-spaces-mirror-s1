from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config.settings import settings

# ডাটাবেজ ইঞ্জিন তৈরি করা (SQLite বা PostgreSQL এর জন্য)
connect_args = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}

engine = create_engine(
    settings.DATABASE_URL, connect_args=connect_args
)

# সেশন লোকাল তৈরি করা
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """ফাস্টএপিআই (FastAPI) ডিপেন্ডেন্সির জন্য ডাটাবেজ সেশন গেটার"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
