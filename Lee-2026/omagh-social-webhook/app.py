# automation/social-engine/webhook-service/app.py
"""
Hugging Face Secrets Needed:
1. FB_PAGE_ID: The ID of your Facebook Page
2. FB_ACCESS_TOKEN: Permanent Page Access Token
3. SUPABASE_URL: Your Supabase project URL
4. WHATSAPP_VERIFY_TOKEN: Secret for Meta Webhook setup
"""
import os
import requests
import json
import logging
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Love Omagh Webhook Listener")

# Environment Variables
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")

# CTA constant
CTA = "\n\n📍 Check the 30-day trend and full leaderboard at loveomagh.com/oil"

@app.get("/")
async def health():
    return {"status": "Social Webhook Active"}

@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    
    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(content=challenge)
    
    raise HTTPException(status_code=403, detail="Verification failed")

@app.post("/webhook")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    
    try:
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [{}])
        
        if messages and "text" in messages[0]:
            raw_text = messages[0]["text"]["body"].strip()
            
            # Logic: Parse the command
            # Case 1: "A1", "B3" etc (Length 2)
            if len(raw_text) == 2:
                choice = raw_text[0].upper()
                vibe_index = raw_text[1] # e.g. "1"
                
                if choice in ["A", "B"]:
                    captions = get_daily_menu()
                    vibe_map = {"1": "optimist", "2": "pragmatist", "3": "local"}
                    vibe_key = vibe_map.get(vibe_index, "optimist")
                    final_caption = captions.get(vibe_key, "")
                    
                    # Process in background so Meta gets a 200 OK instantly
                    background_tasks.add_task(post_to_facebook, choice, final_caption)

            # Case 2: "B - My custom text"
            elif " - " in raw_text:
                parts = raw_text.split(" - ", 1)
                choice = parts[0].strip().upper()
                custom_text = parts[1].strip()
                
                if choice in ["A", "B"]:
                    # Process in background so Meta gets a 200 OK instantly
                    background_tasks.add_task(post_to_facebook, choice, custom_text)
                    
    except Exception as e:
        logger.error(f"❌ Error processing webhook: {e}")

    return {"status": "ok"}

def get_daily_menu():
    """Fetch the generated captions from Supabase Storage."""
    url = f"{SUPABASE_URL}/storage/v1/object/public/social-assets/daily_menu.json"
    try:
        import subprocess
        import json
        result = subprocess.run(["curl", "-s", "-4", url], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return json.loads(result.stdout)
        return {}
    except:
        return {}

def post_to_facebook(choice, caption):
    """Post image and caption to Facebook as a Feed Post."""
    filename = "option_a.png" if choice == "A" else "option_b.png"
    image_url = f"{SUPABASE_URL}/storage/v1/object/public/social-assets/{filename}"
    
    final_text = f"{caption}{CTA}"
    
    import time
    import subprocess
    
    # Bypassing Python's entire SSL/Networking stack using cURL
    # cURL handles MTU and TLS handshakes much more reliably in containerized environments
    post_url = f"https://graph.facebook.com/v21.0/{FB_PAGE_ID}/photos"
    
    try:
        result = subprocess.run([
            "curl", "-s", "-4", "-X", "POST", post_url,
            "--data-urlencode", f"url={image_url}",
            "--data-urlencode", f"message={final_text}",
            "--data-urlencode", "published=true",
            "--data-urlencode", f"access_token={FB_ACCESS_TOKEN}"
        ], capture_output=True, text=True, timeout=30)
        
        logger.info(f"FB Post Response (curl): {result.returncode} - {result.stdout}")
        return '"id"' in result.stdout
        
    except Exception as e:
        logger.error(f"❌ FB API Error (curl): {e}")
        return False

from pydantic import BaseModel

class PublishRequest(BaseModel):
    image_url: str
    caption: str

@app.post("/publish-direct")
async def publish_direct(req: PublishRequest, background_tasks: BackgroundTasks):
    """
    Direct publishing endpoint used by the new Social Studio.
    Expects a public image_url and the final caption text.
    """
    try:
        final_text = req.caption
        
        def post_task():
            import subprocess
            post_url = f"https://graph.facebook.com/v21.0/{FB_PAGE_ID}/photos"
            try:
                result = subprocess.run([
                    "curl", "-s", "-4", "-X", "POST", post_url,
                    "--data-urlencode", f"url={req.image_url}",
                    "--data-urlencode", f"message={final_text}",
                    "--data-urlencode", "published=true",
                    "--data-urlencode", f"access_token={FB_ACCESS_TOKEN}"
                ], capture_output=True, text=True, timeout=120)
                logger.info(f"Direct FB Post Response (curl): {result.returncode} - {result.stdout}")
            except Exception as e:
                logger.error(f"❌ Direct FB API Error (curl): {e}")

        # Process in background so Studio gets instant 200 OK
        background_tasks.add_task(post_task)
        return {"status": "ok", "message": "Publishing to Facebook in background"}
    except Exception as e:
        logger.error(f"❌ Error in /publish-direct: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
