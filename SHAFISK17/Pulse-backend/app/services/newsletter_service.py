"""
Newsletter Service
Orchestrates newsletter sending with time-based preferences and smart content selection.
Handles IST-to-UTC timezone conversion and stale data protection.
"""
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import pytz
from app.services.appwrite_db import get_appwrite_db

from app.services.brevo_email_service import get_brevo_service
from app.services.alert_service import alert_zero_articles, alert_quota_exhausted, alert_high_failure_rate
from app.config import settings


# Timezone constants
IST = pytz.timezone('Asia/Kolkata')
UTC = pytz.timezone('UTC')


# Newsletter configuration
PREFERENCE_CONFIG = {
    "Morning": {
        "hours_back": 12,
        "max_articles": 5,
        "subject": "☀️ Your Morning Tech Brief - SegmentoPulse",
        "greeting": "Good morning! Start your day with the latest tech news:"
    },
    "Afternoon": {
        "hours_back": 6,
        "max_articles": 5,
        "subject": "📰 Midday Tech Update - SegmentoPulse",
        "greeting": "Here's your midday tech update to keep you informed:"
    },
    "Evening": {
        "hours_back": 24,
        "max_articles": 7,
        "subject": "🌙 Evening Tech Digest - SegmentoPulse",
        "greeting": "Wrapping up the day? Catch up on today's top stories:"
    },
    "Weekly": {
        "days_back": 7,
        "max_articles": 15,
        "subject": "📅 Your Weekly Tech Roundup - SegmentoPulse",
        "greeting": "Your curated tech highlights from the past week:"
    },
    "Monthly": {
        "days_back": 30,
        "max_articles": 25,
        "subject": "📊 Monthly Tech Intelligence - SegmentoPulse",
        "greeting": "The most impactful tech stories from this month:"
    }
}


async def get_newsletter_content(preference: str) -> List[Dict]:
    """
    Fetch articles from Appwrite using precise time-windowed application logic.
    Ref: https://segmento.in/newsletter-logic
    
    Time Windows (IST):
    - Morning:   23:00 (Prev Day) -> 07:00 (Today)
    - Afternoon: 07:00 (Today)    -> 14:00 (Today)
    - Evening:   14:00 (Today)    -> 19:00 (Today)
    - Weekly:    Top 10 of the week
    - Monthly:   Top 10 of the month
    """
    from appwrite.query import Query
    
    if preference not in PREFERENCE_CONFIG:
        print(f"❌ Invalid preference: {preference}")
        return []
    
    config = PREFERENCE_CONFIG[preference]
    appwrite_db = get_appwrite_db()
    
    if not appwrite_db.initialized:
        print("⚠️ Appwrite database not initialized")
        return []
    
    try:
        # Step 1: Calculate Strict Time Windows in IST
        now_ist = datetime.now(IST)
        
        if preference == "Morning":
            # 11 PM Prev Day -> 7 AM Today
            today_7am = now_ist.replace(hour=7, minute=0, second=0, microsecond=0)
            prev_day_11pm = (now_ist - timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0)
            
            start_time = prev_day_11pm
            end_time = today_7am
            
        elif preference == "Afternoon":
            # 7 AM Today -> 2 PM Today
            today_7am = now_ist.replace(hour=7, minute=0, second=0, microsecond=0)
            today_2pm = now_ist.replace(hour=14, minute=0, second=0, microsecond=0)
            
            start_time = today_7am
            end_time = today_2pm
            
        elif preference == "Evening":
            # 2 PM Today -> 7 PM Today
            today_2pm = now_ist.replace(hour=14, minute=0, second=0, microsecond=0)
            today_7pm = now_ist.replace(hour=19, minute=0, second=0, microsecond=0)
            
            start_time = today_2pm
            end_time = today_7pm
            
        elif preference == "Weekly":
            # Last 7 days
            end_time = now_ist
            start_time = now_ist - timedelta(days=7)
            
        elif preference == "Monthly":
            # Last 30 days
            end_time = now_ist
            start_time = now_ist - timedelta(days=30)
            
        else:
            # Fallback
            end_time = now_ist
            start_time = now_ist - timedelta(hours=24)

        # Step 2: Convert to UTC for Appwrite Queries
        start_utc = start_time.astimezone(UTC)
        end_utc = end_time.astimezone(UTC)
        
        print(f"🔍 Fetching {preference} newsletter articles...")
        print(f"   Window (IST): {start_time.strftime('%Y-%m-%d %H:%M')} to {end_time.strftime('%Y-%M-%d %H:%M')}")
        print(f"   Window (UTC): {start_utc.isoformat()} to {end_utc.isoformat()}")

        # Step 3: Server-Side Filtering Strategy
        # We want "Top 10" for Weekly/Monthly, but Appwrite sorting limitations might require client-side sort if 'quality_score' isn't indexed.
        # However, we MUST filter by date on the server to avoid fetching 10k articles.
        
        limit = 10 if preference in ["Weekly", "Monthly"] else config["max_articles"]
        
        queries = [
            Query.greater_than('published_at', start_utc.isoformat()),
            Query.less_than_equal('published_at', end_utc.isoformat()),
            Query.order_desc('published_at'), # Default sort by recency
            Query.limit(limit)
        ]
        
        # Step 4: Execute Query across Core Categories (AI, Cloud, Data)
        import asyncio
        core_categories = ['ai', 'cloud-aws', 'data-engineering']
        fetch_tasks = []
        for cat in core_categories:
            fetch_tasks.append(appwrite_db.get_articles_with_queries(queries, category=cat))
            
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        
        collections_articles = []
        for i, res in enumerate(results):
            if isinstance(res, list):
                collections_articles.append(res)
            else:
                print(f"❌ Error fetching newsletter articles for {core_categories[i]}: {res}")
                
        # Step 5: Round-Robin Category Selection
        # We pull 1 from AI, 1 from Cloud, 1 from Data, to build exactly `limit` diverse articles
        final_articles = []
        idx = 0
        
        while len(final_articles) < limit and collections_articles:
            current_list_idx = idx % len(collections_articles)
            list_to_pull_from = collections_articles[current_list_idx]
            
            if list_to_pull_from:
                final_articles.append(list_to_pull_from.pop(0))
                idx += 1
            else:
                collections_articles.pop(current_list_idx)
                # Do not increment idx, as the next list shifts into current_list_idx
        
        print(f"✅ Found {len(final_articles)} articles for {preference} newsletter via Round-Robin")
        return final_articles

    except Exception as e:
        print(f"❌ Error fetching newsletter content: {e}")
        import traceback
        traceback.print_exc()
        return []


async def send_scheduled_newsletter(preference: str) -> Dict[str, int]:
    """
    Main newsletter orchestrator.
    
    CRITICAL SAFETY CHECKS:
    1. Validates preference parameter
    2. Fetches content from Appwrite (with timezone conversion)
    3. SKIPS sending if no articles found (stale data protection)
    4. Gets subscribers for this preference
    5. Sends emails via Brevo API
    
    Returns: {"sent": int, "failed": int, "skipped": Optional[str]}
    """
    print(f"\n{'='*80}")
    print(f"📧 NEWSLETTER SEND TRIGGER: {preference}")
    print(f"⏰ Trigger Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"{'='*80}\n")
    
    # Validation
    if preference not in PREFERENCE_CONFIG:
        print(f"❌ Invalid preference: {preference}")
        return {"sent": 0, "failed": 0, "skipped": "invalid_preference"}
    
    # SAFETY CHECK #1: Fetch articles with timezone conversion
    articles = await get_newsletter_content(preference)
    
    if not articles or len(articles) == 0:
        # CRITICAL ALERT: Zero articles found
        error_msg = f"CRITICAL ALERT: No articles for {preference} newsletter!"
        timestamp_ist = datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S %Z')
        
        print(f"")
        print(f"{'!'*80}")
        print(f"⚠️  {error_msg}")
        print(f"   Preference: {preference}")
        print(f"   Time: {timestamp_ist}")
        print(f"   Possible causes:")
        print(f"   1. News fetcher hasn't run yet")
        print(f"   2. All APIs hit rate limits (429 errors)")
        print(f"   3. No articles match the time window")
        print(f"   4. Appwrite database is empty")
        print(f"   ")
        print(f"   ACTION REQUIRED: Check /api/admin/scheduler/fetch-now")
        print(f"{'!'*80}")
        print(f"")
        
        # ACTIVE ALERT: Send webhook to admin (Discord/Slack)
        await alert_zero_articles(preference, timestamp_ist)
        
        return {"sent": 0, "failed": 0, "skipped": "no_articles", "alert": True}
    
    # SAFETY CHECK #2: Get subscribers for this preference
    appwrite_db = get_appwrite_db()
    subscribers = await appwrite_db.get_subscribers_by_preference(preference)
    
    if not subscribers or len(subscribers) == 0:
        print(f"ℹ️ SKIP: No active subscribers for {preference} preference.")
        print(f"\n{'='*80}\n")
        return {"sent": 0, "failed": 0, "skipped": "no_subscribers"}
    
    print(f"👥 Found {len(subscribers)} active subscribers")
    print(f"📰 Sending {len(articles)} curated articles")
    
    # Send newsletter via Brevo
    config = PREFERENCE_CONFIG[preference]
    brevo = get_brevo_service()
    
    result = brevo.send_newsletter(
        preference=preference,
        subject=config["subject"],
        greeting=config["greeting"],
        articles=articles,
        subscribers=subscribers
    )
    
    # Check for quota issues and alert if needed
    if result.get('quota_limited', False):
        print(f"")
        print(f"{'!'*80}")
        print(f"⚠️  QUOTA ALERT: Brevo API limit reached!")
        print(f"   Sent: {result['sent']}")
        print(f"   Skipped: {result.get('skipped_count', 0)}")
        print(f"   Remaining credits: {result.get('remaining_credits', 'unknown')}")
        print(f"   ")
        print(f"   ACTION REQUIRED: Upgrade Brevo plan or reduce frequency")
        print(f"{'!'*80}")
        print(f"")
        
        # ACTIVE ALERT: Send webhook to admin
        await alert_quota_exhausted(
            preference=preference,
            sent=result['sent'],
            skipped=result.get('skipped_count', 0),
            remaining=result.get('remaining_credits', 0)
        )
    
    # Check for high failure rate and alert
    total_attempted = result.get('sent', 0) + result.get('failed', 0)
    if total_attempted > 0:
        failure_rate = result.get('failed', 0) / total_attempted
        await alert_high_failure_rate(
            preference=preference,
            sent=result.get('sent', 0),
            failed=result.get('failed', 0),
            failure_rate=failure_rate
        )
    
    print(f"\n✅ Newsletter send complete!")
    print(f"   Sent: {result.get('sent', 0)}")
    print(f"   Failed: {result.get('failed', 0)}")
    if result.get('quota_limited'):
        print(f"   ⚠️ Quota Limited: {result.get('skipped_count', 0)} skipped")
    print(f"   Remaining credits: {result.get('remaining_credits', 'N/A')}")
    print(f"{'='*80}\n")
    
    # Update last sent timestamp for all SENT subscribers only
    sent_count = result.get('sent', 0)
    if sent_count > 0:
        for i, subscriber in enumerate(subscribers[:sent_count]):
            email = subscriber.get('email')
            if email:
                await appwrite_db.update_last_sent(email)
    
    return result



# Note: Subscriber queries now use Appwrite directly via appwrite_db.get_subscribers_by_preference()
# See newsletter_service.py line 211


async def preview_newsletter_content(preference: str) -> Dict:
    """
    Preview newsletter content without sending emails.
    Useful for testing and debugging.
    """
    articles = await get_newsletter_content(preference)
    
    return {
        "preference": preference,
        "article_count": len(articles),
        "articles": articles,
        "config": PREFERENCE_CONFIG.get(preference, {})
    }
