from sqlalchemy.orm import Session
from app.models.user import User
from app.config.security import get_password_hash

class UserService:
    @staticmethod
    def get_user_by_username(db: Session, username: str):
        """ইউজারনেম দিয়ে ইউজার খোঁজার সার্ভিস"""
        return db.query(User).filter(User.username == username).first()

    @staticmethod
    def create_user(db: Session, username: str, email: str, password: str):
        """নতুন ইউজার তৈরি করার সার্ভিস"""
        hashed_password = get_password_hash(password)
        db_user = User(username=username, email=email, hashed_password=hashed_password)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user
