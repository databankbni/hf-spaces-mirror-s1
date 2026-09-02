from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.user import Base

class Document(Base):
    """ডকুমেন্ট বা ফাইল সংরক্ষণের মডেল (RAG বা নলেজ বেজের জন্য)"""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_type = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # ইউজার টেবিলের সাথে সম্পর্ক
    owner = relationship("User", backref="documents")
