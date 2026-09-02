from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.user import Base

class Embedding(Base):
    """ভেক্টর এমবেডিং এবং সিমিলারিটি সার্চের ডাটা মডেল"""
    __tablename__ = "embeddings"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    chunk_text = Column(Text, nullable=False)
    vector_data = Column(Text, nullable=False)  # এমবেডিং ভেক্টর স্ট্রিং বা বাইনারি ফরম্যাটে
    created_at = Column(DateTime, default=datetime.utcnow)

    # ডকুমেন্ট টেবিলের সাথে সম্পর্ক
    document = relationship("Document", backref="embeddings")
