"""
Subscription API Routes
Handles newsletter subscriptions and unsubscribe functionality
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, EmailStr, field_validator
from typing import List, Optional
from datetime import datetime

from app.services.brevo_email_service import get_brevo_service
from app.services.appwrite_db import get_appwrite_db, _safe_get

router = APIRouter(prefix="/api/subscription", tags=["subscription"])


# Pydantic models
class SubscribeRequest(BaseModel):
    email: EmailStr
    name: str
    topics: Optional[List[str]] = ["news", "security", "cloud", "ai"]
    preference: str = "Weekly"  # Default to Weekly for backward compatibility
    
    @field_validator('preference')
    @classmethod
    def validate_preference(cls, v):
        allowed = ["Morning", "Afternoon", "Evening", "Weekly", "Monthly"]
        if v not in allowed:
            raise ValueError(f"Preference must be one of: {allowed}")
        return v


class SubscribeResponse(BaseModel):
    success: bool
    message: str
    token: Optional[str] = None


class UnsubscribeResponse(BaseModel):
    success: bool
    message: str
    email: Optional[str] = None


@router.post("/subscribe", response_model=SubscribeResponse)
async def subscribe(request: SubscribeRequest):
    """
    Subscribe a user to the newsletter
    
    - Adds subscriber to Appwrite (Sole Source of Truth)
    - Sends welcome email via Brevo
    - Returns subscription token
    """
    try:
        brevo = get_brevo_service()
        appwrite_db = get_appwrite_db()
        
        # Generate unique token
        token = brevo.generate_unsubscribe_token(request.email)
        
        # Convert preference to boolean flags
        prefs = {request.preference: True}
        
        # Create Subscriber in Appwrite
        success = await appwrite_db.create_subscriber(
            email=request.email,
            name=request.name,
            preferences=prefs,
            token=token
        )
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to save subscriber to Appwrite"
            )
        
        # Send welcome email
        email_sent = brevo.send_welcome_email(
            email=request.email,
            name=request.name,
            token=token
        )
        
        if not email_sent:
            return SubscribeResponse(
                success=True,
                message=f"Subscribed to {request.preference} newsletter! (Email not sent)",
                token=token
            )
        
        return SubscribeResponse(
            success=True,
            message=f"Successfully subscribed to {request.preference} newsletter!",
            token=token
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in subscribe endpoint: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Subscription failed: {str(e)}"
        )


@router.get("/unsubscribe", response_model=UnsubscribeResponse)
async def unsubscribe(
    token: str = Query(..., description="Unsubscribe token from email"),
    preference: Optional[str] = Query(None, description="Specific newsletter to unsubscribe from")
):
    """
    Unsubscribe user via email link
    Supports Granular Unsubscribe (e.g., 'Morning' only)
    """
    try:
        appwrite_db = get_appwrite_db()
        brevo = get_brevo_service()
        
        # Find subscriber by token
        subscriber = await appwrite_db.get_subscriber_by_token(token)
        
        if not subscriber:
            raise HTTPException(
                status_code=404,
                detail="Invalid or expired unsubscribe link"
            )
        
        email = subscriber.get('email')
        name = subscriber.get('name', 'Subscriber')
        
        success = False
        message = ""
        
        if preference:
            # GRANULAR UNSUBSCRIBE
            success = await appwrite_db.update_subscription_status(email, preference, False)
            message = f"You have been unsubscribed from the {preference} newsletter."
        else:
            # GLOBAL UNSUBSCRIBE
            success = await appwrite_db.update_subscriber_status(email, subscribed=False)
            message = "You have been globally unsubscribed from all SegmentoPulse newsletters."
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to update subscription preference"
            )
        
        # Send confirmation email (Global or Specific)
        # Note: We might want slightly different emails for specific vs global, 
        # but for now reusing the standard one is fine or we can customize.
        if not preference:
             brevo.send_unsubscribe_confirmation(email, name)
        
        return UnsubscribeResponse(
            success=True,
            message=message,
            email=email
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in unsubscribe endpoint: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Unsubscribe failed: {str(e)}"
        )


class UnsubscribeRequest(BaseModel):
    email: EmailStr
    preference: Optional[str] = None

@router.post("/unsubscribe", response_model=UnsubscribeResponse)
async def unsubscribe_post(request: UnsubscribeRequest):
    """
    Unsubscribe via email address (for forms/dashboard)
    Supports Granular Unsubscribe
    """
    try:
        appwrite_db = get_appwrite_db()
        brevo = get_brevo_service()
        
        # Get subscriber
        subscriber = await appwrite_db.get_subscriber(request.email)
        
        if not subscriber:
            raise HTTPException(
                status_code=404,
                detail="Email not found in subscriber list"
            )
        
        name = subscriber.get('name', 'Subscriber')
        email = request.email
        
        success = False
        message = ""
        
        if request.preference:
            # GRANULAR UNSUBSCRIBE
            success = await appwrite_db.update_subscription_status(email, request.preference, False)
            message = f"Successfully unsubscribed from {request.preference}"
        else:
             # GLOBAL UNSUBSCRIBE
            success = await appwrite_db.update_subscriber_status(email, subscribed=False)
            message = "Successfully unsubscribed from all newsletters"
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to unsubscribe"
            )
        
        # Send confirmation
        # Only send email if global unsubscribe (to avoid spamming on toggle off)
        # OR we could send a specific one. For dashboard usage, maybe silent is better?
        # Let's keep it consistent: send confirmation.
        if not request.preference:
            brevo.send_unsubscribe_confirmation(email, name)
        
        return UnsubscribeResponse(
            success=True,
            message=message,
            email=email
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in unsubscribe_post endpoint: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Unsubscribe failed: {str(e)}"
        )


@router.get("/subscribers/count")
async def get_subscriber_count():
    """Get total number of active subscribers from Appwrite"""
    try:
        appwrite_db = get_appwrite_db()
        subscribers = await appwrite_db.get_all_subscribers()
        
        active_count = sum(1 for s in subscribers if s.get('isActive', True))
        
        return {
            "total": len(subscribers),
            "active": active_count,
            "inactive": len(subscribers) - active_count
        }
        
    except Exception as e:
        print(f"Error getting subscriber count: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get subscriber count"
        )


@router.post("/newsletter/send")
async def send_newsletter(
    subject: str,
    category: str = "ai"
):
    """
    Send newsletter to all subscribers (LEGACY ENDPOINT - Use scheduled newsletters instead)
    
    - Fetches latest news from specified category
    - Sends to all active subscribers
    - Returns send statistics
    """
    try:
        appwrite_db = get_appwrite_db()
        brevo = get_brevo_service()
        
        # Get all active subscribers from Appwrite
        subscribers = await appwrite_db.get_all_subscribers()
        active_subscribers = [s for s in subscribers if s.get('isActive', True)]
        
        if not active_subscribers:
            return {
                "success": False,
                "message": "No active subscribers found",
                "sent": 0,
                "failed": 0
            }
        
        # Fetch latest news articles (you can customize this)
        from app.services.news_aggregator import news_aggregator
        articles = await news_aggregator.fetch_by_category(category)
        
        # Send newsletter
        result = brevo.send_newsletter(
            subject=subject,
            articles=articles,
            subscribers=active_subscribers
        )
        
        return {
            "success": True,
            "message": f"Newsletter sent to {result['sent']} subscribers",
            **result
        }
        
    except Exception as e:
        print(f"Error sending newsletter: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send newsletter: {str(e)}"
        )

@router.get("/status")
async def get_subscription_status(email: str = Query(..., description="User email")):
    """
    Get subscription status by email
    Required for Dashboard to sync with Appwrite (Single Source of Truth)
    """
    print(f"DEBUG: Status endpoint hit for {email}") # Debug print
    try:
        appwrite_db = get_appwrite_db()
        subscriber = await appwrite_db.get_subscriber(email)
        
        if not subscriber:
            return {
                "email": email,
                "subscribed": False,
                "preference": "Weekly",
                "subscriptions": {}
            }
            
        # Transform Appwrite flat columns to Frontend nested object
        subscriptions = {
            "Morning": _safe_get(subscriber, "sub_morning", False),
            "Afternoon": _safe_get(subscriber, "sub_afternoon", False),
            "Evening": _safe_get(subscriber, "sub_evening", False),
            "Weekly": _safe_get(subscriber, "sub_weekly", False),
            "Monthly": _safe_get(subscriber, "sub_monthly", False)
        }
        
        # Determine "primary" preference for backward compatibility
        # (Just pick the first active one, or default to Weekly)
        primary_pref = "Weekly"
        for key, val in subscriptions.items():
            if val:
                primary_pref = key
                break
        
        return {
            "email": _safe_get(subscriber, "email"),
            "name": _safe_get(subscriber, "name"),
            "subscribed": _safe_get(subscriber, "isActive", True),
            "token": _safe_get(subscriber, "token"),
            "subscribedAt": _safe_get(subscriber, "$createdAt"),
            "topics": ["news"], # Default
            "preference": primary_pref,
            "subscriptions": subscriptions
        }
        
    except Exception as e:
        print(f"Error getting subscription status: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get status: {str(e)}"
        )
