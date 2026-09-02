from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta
from app.config.settings import settings
from app.config.security import create_access_token, get_password_hash, verify_password

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register")
async def register(form_data: OAuth2PasswordRequestForm):
    """নতুন ইউজার রেজিস্ট্রেশন করার এন্ডপয়েন্ট"""
    # প্রোডাকশনে এখানে ডাটাবেজে ইউজার সেভ করার লজিক থাকবে
    hashed_password = get_password_hash(form_data.password)
    
    # টেস্টিং বা ডেমো রেসপন্স
    return {
        "message": "User registered successfully",
        "username": form_data.username,
        "hashed_password_sample": hashed_password[:15] + "..."
    }

@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm):
    """ইউজার লগইন এবং টোকেন জেনারেট করার এন্ডপয়েন্ট"""
    # ডেমো চেকিং (ডাটাবেজ কানেকশনের পর এটি ডায়নামিক হবে)
    # এখানে ইউজার ভ্যালিডেশন চেক করা হয়
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": form_data.username}, expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer"
    }
