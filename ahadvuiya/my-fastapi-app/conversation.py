from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.user import Base # User মডেলের Base ব্যবহার করা হচ্ছে

class Conversation(Base):
    """কনভারসেশন বা চ্যাট হিস্ট্রি মডেল"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, default="New Conversation")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ইউজার টেবিলের সাথে সম্পর্ক (Relationship)
    owner = relationship("User", backref="conversations")
