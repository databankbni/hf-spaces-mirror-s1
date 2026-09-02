from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.core.ai_gateway import ai_gateway
from app.core.moderation import content_moderator

router = APIRouter(prefix="/chat", tags=["AI Chat"])

class ChatMessage(BaseModel):
    role: str  # যেমন: user বা assistant
    content: str

class ChatRequest(BaseModel):
    prompt: str
    conversation_id: Optional[str] = None
    history: Optional[List[ChatMessage]] = []

@router.post("/send")
async def send_chat_message(request: ChatRequest):
    """ইউজারের চ্যাট প্রম্পট গ্রহণ করে মডারেশন চেক ও এআই-এর কাছে পাঠানোর এন্ডপয়েন্ট"""
    
    # ১. কন্টেন্ট মডারেশন বা সেফটি চেক
    moderation_result = content_moderator.check_content(request.prompt)
    if not moderation_result["is_safe"]:
        raise HTTPException(
            status_code=400,
            detail=moderation_result["reason"]
        )

    # ২. এআই গেটওয়ের মাধ্যমে প্রসেসিং (এখানে ডেমো বা এক্সটার্নাল এআই এন্ডপয়েন্ট কল করা যাবে)
    payload = {
        "prompt": request.prompt,
        "history": [msg.dict() for msg in request.history]
    }
    
    # প্রোডাকশনে এখানে নির্দিষ্ট এআই মডেলের এন্ডপয়েন্ট বসবে
    # ai_response = await ai_gateway.forward_request("https://api.openai.com/v1/chat/completions", payload)

    # আপাতত একটি সাকসেসফুল রেসপন্স রিটার্ন করা হচ্ছে
    return {
        "success": True,
        "conversation_id": request.conversation_id or "default-conv-id",
        "response": f"ZentraX AI processed your prompt securely: {request.prompt}"
    }
