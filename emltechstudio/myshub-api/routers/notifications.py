from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import os
import json

from utils.db import (
    get_user_by_email,
    get_notifications, create_notification, mark_notification_read,
    _ensure_private_loaded, _notifications, _schedule_private_flush, FLUSH_DELAY_NOTIFICATIONS
)
from utils.security import verify_password

router = APIRouter()

# VAPID keys from env (user will configure)
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_CLAIMS = {"sub": os.getenv("VAPID_SUBJECT", "mailto:admin@myshub.site")}

# ── Pydantic Models ─────────────────────────────────────────────────
class PushSubscription(BaseModel):
    endpoint: str
    keys: dict  # {p256dh: str, auth: str}

class NotificationCreate(BaseModel):
    email: str  # target user email or "ALL" for broadcast
    type: str  # milestone, expiry, broadcast, system
    title: str
    message: str
    data: dict = {}

# ── Auth Helper ─────────────────────────────────────────────────────
def _verify_user(email: str, password: str):
    user = get_user_by_email(email.lower().strip())
    if not user:
        raise HTTPException(status_code=404, detail="No account found.")
    if not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect password.")
    return user

# ── Web Push Endpoints ──────────────────────────────────────────────
@router.get("/vapid-public-key")
def get_vapid_public_key():
    """Get VAPID public key for frontend subscription."""
    if not VAPID_PUBLIC_KEY:
        return {"key": ""}
    return {"key": VAPID_PUBLIC_KEY}

@router.post("/subscribe")
def subscribe_push(
    subscription: PushSubscription,
    email: str = Header(...),
    password: str = Header(...)
):
    """Save user's push subscription."""
    user = _verify_user(email, password)

    # Update user with push subscription
    from utils.db import update_user
    update_user(email, {"push_subscription": subscription.dict()})

    return {"success": True, "message": "Push subscription saved."}

@router.post("/unsubscribe")
def unsubscribe_push(
    email: str = Header(...),
    password: str = Header(...)
):
    """Remove user's push subscription."""
    user = _verify_user(email, password)
    from utils.db import update_user
    update_user(email, {"push_subscription": None})
    return {"success": True, "message": "Push subscription removed."}

# ── In-App Notifications ────────────────────────────────────────────
@router.get("/")
def list_notifications(
    email: str = Header(...),
    password: str = Header(...),
    unread_only: bool = False
):
    """Get all notifications for the user."""
    user = _verify_user(email, password)
    notifs = get_notifications(email)

    if unread_only:
        notifs = [n for n in notifs if not n.get("read", False)]

    # Sort by created_at desc
    notifs.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return {
        "total": len(notifs),
        "unread": len([n for n in notifs if not n.get("read", False)]),
        "notifications": notifs
    }

@router.post("/{notification_id}/read")
def mark_as_read(
    notification_id: str,
    email: str = Header(...),
    password: str = Header(...)
):
    """Mark a notification as read."""
    _verify_user(email, password)
    success = mark_notification_read(notification_id, email)
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"success": True}

@router.post("/read-all")
def mark_all_read(
    email: str = Header(...),
    password: str = Header(...)
):
    """Mark all notifications as read."""
    _verify_user(email, password)
    notifs = get_notifications(email)

    for n in notifs:
        if not n.get("read", False):
            mark_notification_read(n["id"], email)

    return {"success": True, "message": "All notifications marked as read."}


@router.delete("/{notification_id}")
def delete_user_notification(
    notification_id: str,
    email: str = Header(...),
    password: str = Header(...)
):
    """Delete one notification visible to the authenticated user."""
    _verify_user(email, password)
    _ensure_private_loaded()
    normalized_email = email.lower().strip()
    for index, notification in enumerate(list(_notifications or [])):
        owner = str(notification.get("email", "")).lower().strip()
        if notification.get("id") == notification_id and owner in {normalized_email, "all"}:
            del _notifications[index]
            _schedule_private_flush(
                "notifications",
                "notifications.parquet",
                _notifications,
                FLUSH_DELAY_NOTIFICATIONS,
            )
            return {"success": True, "notification_id": notification_id}
    raise HTTPException(status_code=404, detail="Notification not found")

# ── Admin Broadcast ─────────────────────────────────────────────────
@router.post("/broadcast")
def broadcast_notification(
    data: NotificationCreate,
    admin_email: str = Header(...),
    admin_password: str = Header(...)
):
    """Admin broadcast notification to all users or specific user."""
    # Verify admin
    from utils.db import get_admin
    admin = get_admin(admin_email)
    if not admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    import hashlib
    admin_pwd_hash = hashlib.sha256(admin_password.encode()).hexdigest()
    if admin.get("password") != admin_pwd_hash:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    notification = {
        "email": data.email,  # "ALL" or specific email
        "type": data.type,
        "title": data.title,
        "message": data.message,
        "read": False,
        "data": data.data,
    }

    notif = create_notification(notification)

    # If web push is configured, try to send push
    if VAPID_PRIVATE_KEY and data.email == "ALL":
        # Send to all users with push subscriptions
        _send_push_broadcast(data.title, data.message)
    elif VAPID_PRIVATE_KEY and data.email != "ALL":
        # Send to specific user
        user = get_user_by_email(data.email)
        if user and user.get("push_subscription"):
            _send_push_to_user(user["push_subscription"], data.title, data.message)

    return {"success": True, "notification_id": notif["id"]}

# ── Milestone Check (called from analytics) ──────────────────────
def check_milestones(shop: dict):
    """Check and create milestone notifications."""
    visit_count = shop.get("visit_count", 0)
    email = shop.get("email", "")
    slug = shop.get("slug", "")

    milestones = [100, 500, 1000, 5000, 10000, 50000, 100000]

    for milestone in milestones:
        if visit_count == milestone:
            create_notification({
                "email": email,
                "type": "milestone",
                "title": f"🎉 Congrats on {milestone} views!",
                "message": f"Your shub '{slug}' just hit {milestone} views. Keep growing!",
                "read": False,
                "data": {"milestone": milestone, "slug": slug}
            })
            # Try web push
            user = get_user_by_email(email)
            if user and user.get("push_subscription") and VAPID_PRIVATE_KEY:
                _send_push_to_user(
                    user["push_subscription"],
                    f"🎉 {milestone} Views!",
                    f"Your shub '{slug}' just hit {milestone} views!"
                )
            break

def check_expiry_warning(shop: dict):
    """Check and create expiry warning notifications."""
    from datetime import datetime, timezone
    expires_at = shop.get("expires_at", "")
    plan = shop.get("plan", "free")
    email = shop.get("email", "")

    if not expires_at or plan == "free":
        return

    try:
        expiry = datetime.fromisoformat(expires_at)
        days_left = (expiry - datetime.now(timezone.utc)).days

        if days_left in [5, 3, 1]:
            create_notification({
                "email": email,
                "type": "expiry",
                "title": f"⏰ Plan expires in {days_left} days",
                "message": f"Your {plan} plan expires in {days_left} days. Renew to keep your features.",
                "read": False,
                "data": {"days_left": days_left, "plan": plan}
            })
            # Try web push
            user = get_user_by_email(email)
            if user and user.get("push_subscription") and VAPID_PRIVATE_KEY:
                _send_push_to_user(
                    user["push_subscription"],
                    f"⏰ Plan Expires Soon",
                    f"Your {plan} plan expires in {days_left} days. Renew now!"
                )
    except:
        pass

# ── Web Push Helpers ──────────────────────────────────────────────
def _send_push_to_user(subscription: dict, title: str, body: str):
    """Send web push notification to a single user."""
    try:
        from pywebpush import webpush, WebPushException

        webpush(
            subscription_info=subscription,
            data=json.dumps({"title": title, "body": body, "icon": "https://myshub.site/icon.svg"}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=VAPID_CLAIMS
        )
    except Exception as e:
        print(f"[Push Error] {e}")

def _send_push_broadcast(title: str, body: str):
    """Send web push to all subscribed users."""
    from utils.db import _users
    _ensure_private_loaded()

    for user in _users:
        sub = user.get("push_subscription")
        if sub:
            _send_push_to_user(sub, title, body)
