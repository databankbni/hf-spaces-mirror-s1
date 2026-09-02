"""
Admin Alerting Service
Sends real-time alerts via webhooks (Discord/Slack) for critical failures.
Converts passive logs into active notifications.
"""
from typing import Optional, Dict
import httpx
from datetime import datetime
from app.config import settings


async def send_admin_alert(
    title: str,
    message: str,
    severity: str = "warning",
    details: Optional[Dict] = None
) -> bool:
    """
    Send alert to admin via webhook (Discord/Slack)
    
    This converts passive logs into ACTIVE alerts that ping your phone.
    
    Args:
        title: Alert title (e.g., "Critical: No Articles Found")
        message: Detailed description
        severity: "info", "warning", "error", "critical"
        details: Optional dict with extra context
    
    Returns:
        True if alert sent successfully
    """
    if not settings.ADMIN_WEBHOOK_URL:
        # No webhook configured, silent fail (keeps logs only)
        return False
    
    try:
        # Map severity to colors (Discord embed colors)
        color_map = {
            "info": 3447003,      # Blue
            "warning": 16776960,  # Yellow
            "error": 16711680,    # Red
            "critical": 10038562  # Dark Red
        }
        
        # Build timestamp
        timestamp = datetime.now().isoformat()
        
        # Format details if provided
        details_text = ""
        if details:
            details_text = "\n**Details:**\n"
            for key, value in details.items():
                details_text += f"• {key}: `{value}`\n"
        
        # Discord/Slack webhook payload
        # This format works for both services
        payload = {
            "embeds": [{
                "title": f"🚨 {title}",
                "description": f"{message}{details_text}",
                "color": color_map.get(severity, 16776960),
                "footer": {
                    "text": f"SegmentoPulse Newsletter System • {timestamp}"
                },
                "fields": [
                    {
                        "name": "Severity",
                        "value": severity.upper(),
                        "inline": True
                    }
                ]
            }]
        }
        
        # Send webhook request (non-blocking, timeout after 5s)
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                settings.ADMIN_WEBHOOK_URL,
                json=payload
            )
            
            if response.status_code in [200, 204]:
                print(f"✅ Admin alert sent via webhook")
                return True
            else:
                print(f"⚠️  Webhook failed with status {response.status_code}")
                return False
    
    except httpx.TimeoutException:
        print(f"⚠️  Webhook timeout (5s) - alert not sent")
        return False
    except Exception as e:
        print(f"⚠️  Failed to send webhook alert: {e}")
        return False


async def alert_zero_articles(preference: str, timestamp: str) -> None:
    """Alert: Critical - No articles available for newsletter"""
    await send_admin_alert(
        title="Critical: Zero Articles",
        message=f"No articles found for **{preference}** newsletter!",
        severity="critical",
        details={
            "Preference": preference,
            "Time (IST)": timestamp,
            "Action": "Run /api/admin/scheduler/fetch-now",
            "Possible Cause": "News fetcher failed or rate limited"
        }
    )


async def alert_quota_exhausted(
    preference: str,
    sent: int,
    skipped: int,
    remaining: int
) -> None:
    """Alert: Warning - Brevo API quota exhausted"""
    await send_admin_alert(
        title="Quota Exhausted",
        message=f"Brevo API limit reached for **{preference}** newsletter",
        severity="error",
        details={
            "Emails Sent": sent,
            "Subscribers Skipped": skipped,
            "Remaining Credits": remaining,
            "Action": "Upgrade Brevo plan or reduce frequency"
        }
    )


async def alert_high_failure_rate(
    preference: str,
    sent: int,
    failed: int,
    failure_rate: float
) -> None:
    """Alert: Error - High email failure rate"""
    if failure_rate > 0.1:  # Alert if >10% failure
        await send_admin_alert(
            title="High Failure Rate",
            message=f"**{failure_rate*100:.1f}%** of emails failed for **{preference}** newsletter",
            severity="error",
            details={
                "Emails Sent": sent,
                "Failed": failed,
                "Failure Rate": f"{failure_rate*100:.1f}%",
                "Action": "Check Brevo dashboard for bounce reasons"
            }
        )
