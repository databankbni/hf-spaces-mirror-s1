from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/users", tags=["Users"])

class UserProfileResponse(BaseModel):
    username: str
    email: Optional[str] = "user@zentrax.ai"
    is_active: bool = True

@router.get("/me", response_model=UserProfileResponse)
async def get_current_user_profile():
    """বর্তমান লগইন করা ইউজারের প্রফাইল তথ্য পাওয়ার এন্ডপয়েন্ট"""
    # প্রোডাকশনে এখানে ডাটাবেজ থেকে ইউজারের আসল ডাটা ফেচ করা হবে
    return {
        "username": "admin_user",
        "email": "admin@zentrax.ai",
        "is_active": True
    }

@router.put("/me")
async def update_user_profile(email: Optional[str] = None):
    """ইউজারের প্রফাইল আপডেট করার এন্ডপয়েন্ট"""
    return {
        "success": True,
        "message": "Profile updated successfully",
        "updated_email": email
    }
