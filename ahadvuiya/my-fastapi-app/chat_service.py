from sqlalchemy.orm import Session
from app.models.message import Message
from app.models.conversation import Conversation

class ChatService:
    @staticmethod
    def save_message(db: Session, conversation_id: int, sender: str, content: str):
        """মেসেজ ডাটাবেজে সংরক্ষণ করার সার্ভিস"""
        db_message = Message(conversation_id=conversation_id, sender=sender, content=content)
        db.add(db_message)
        db.commit()
        db.refresh(db_message)
        return db_message

    @staticmethod
    def get_conversation_history(db: Session, conversation_id: int):
        """নির্দিষ্ট কনভারসেশনের হিস্ট্রি ফেচ করার সার্ভিস"""
        return db.query(Message).filter(Message.conversation_id == conversation_id).all()
