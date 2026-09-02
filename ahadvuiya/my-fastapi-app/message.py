from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.user import Base

class Message(Base):
    """চ্যাটের মেসেজ বা প্রম্পট ও রেসপন্স সংরক্ষণের মডেল"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    sender = Column(String, nullable=False)  # যেমন: "user" বা "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # কনভারসেশন টেবিলের সাথে সম্পর্ক
    conversation = relationship("Conversation", backref="messages")
