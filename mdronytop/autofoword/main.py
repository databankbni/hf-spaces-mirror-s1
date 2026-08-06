import os
import asyncio
import json
import re
import time
import datetime
from collections import deque
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import UserAlreadyParticipantError
from telethon.tl.types import MessageEntityTextUrl, MessageEntityMentionName
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
import threading

# সেটিংস (আপনার দেওয়া মানসমূহ)
API_ID = 23971860
API_HASH = "cca89c8922958dd72c5ed1aec14049c3"
SESSION_STRING = os.getenv("SESSION_STRING")
SOURCE_CHANNEL_ID = -1001840799956

# ডেস্টিনেশন গ্রুপ ও ফাইল ম্যানেজমেন্ট
DEST_FILE = "destinations.json"
JOINED_CHANNELS_FILE = "joined_channels.json"

DEFAULT_DESTINATIONS = [
    -1003487235934, -1003408214872, -1002300221011, -1003228142826, 
    "@All_Free_Promote_Here", "@Free_Promotion_V2", "@Free_Promotions_Hero", 
    "@free_promotion_group_21", "@freepromotionchannal", "@freepromotion_2026"
]

INTERVAL = 1700 

app = FastAPI()

# লাইভ লগ রাখার জন্য ডেটা স্ট্রাকচার (সর্বশেষ ১০০টি লগ রাখবে)
live_logs = deque(maxlen=100)

def log_event(message):
    timestamp = datetime.datetime.now().strftime("%I:%M:%S %p")
    formatted_msg = f"[{timestamp}] {message}"
    print(formatted_msg)
    live_logs.append(formatted_msg)

def load_destinations():
    if not os.path.exists(DEST_FILE):
        save_destinations(DEFAULT_DESTINATIONS)
        return DEFAULT_DESTINATIONS
    try:
        with open(DEST_FILE, "r") as f:
            return json.load(f)
    except:
        return DEFAULT_DESTINATIONS

def save_destinations(dest_list):
    with open(DEST_FILE, "w") as f:
        json.dump(dest_list, f, indent=4)

def add_destination(new_target):
    dest_list = load_destinations()
    # সংখ্যা বা ইউজারনেম টাইপ সঠিক করতে ভ্যালিডেশন
    clean_target = int(new_target) if str(new_target).lstrip('-').isdigit() else str(new_target).strip()
    
    # ডুপ্লিকেট চেক (স্ট্রিং ও ইন্টিজার সঠিকভাবে মেলানোর জন্য)
    str_list = [str(x).lower() for x in dest_list]
    if str(clean_target).lower() not in str_list:
        dest_list.append(clean_target)
        save_destinations(dest_list)
        return True
    return False

def load_joined_data():
    if not os.path.exists(JOINED_CHANNELS_FILE):
        return {}
    try:
        with open(JOINED_CHANNELS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_joined_data(data):
    with open(JOINED_CHANNELS_FILE, "w") as f:
        json.dump(data, f, indent=4)

# ব্রাউজারে লাইভ লগ ও কন্ট্রোল দেখার ওয়েব পেজ
@app.get("/logs", response_class=HTMLResponse)
def get_logs(msg: str = None, err: str = None):
    log_html = "".join([f"<p style='font-family: monospace; margin: 5px 0; border-bottom: 1px solid #222; padding-bottom: 3px;'>{log}</p>" for log in reversed(live_logs)])
    
    # নোটিফিকেশন অ্যালার্ট
    notification = ""
    if msg == "success":
        notification = "<div style='background-color: #1b5e20; color: #fff; padding: 12px; border-radius: 5px; margin-bottom: 15px; font-weight: bold;'>✅ নতুন গ্রুপ/চ্যানেল সফলভাবে যোগ করা হয়েছে!</div>"
    elif msg == "exists":
        notification = "<div style='background-color: #b71c1c; color: #fff; padding: 12px; border-radius: 5px; margin-bottom: 15px; font-weight: bold;'>ℹ️ এই গ্রুপ/চ্যানেলটি ইতিমধ্যে লিস্টে বিদ্যমান রয়েছে।</div>"
    elif msg == "error":
        notification = f"<div style='background-color: #b71c1c; color: #fff; padding: 12px; border-radius: 5px; margin-bottom: 15px; font-weight: bold;'>❌ ভুল হয়েছে: {err}</div>"

    return f"""
    <html>
        <head>
            <title>Auto-Forwarder Control Panel</title>
            <meta http-equiv="refresh" content="5">
            <style>
                body {{ background-color: #0f0f0f; color: #00FF66; padding: 20px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }}
                h2 {{ color: #ffffff; margin-bottom: 10px; }}
                .container {{ background-color: #141414; padding: 20px; border-radius: 8px; height: 50vh; overflow-y: auto; border: 1px solid #333; box-shadow: 0px 0px 10px rgba(0, 255, 102, 0.1); }}
                .form-box {{ background-color: #141414; padding: 20px; border-radius: 8px; border: 1px solid #333; margin-bottom: 20px; }}
                .info {{ color: #888; font-size: 0.9em; margin-bottom: 15px; }}
                input[type="text"] {{ width: 70%; padding: 12px; border-radius: 5px; border: 1px solid #444; background-color: #222; color: #fff; font-size: 1em; outline: none; }}
                button {{ background-color: #00FF66; color: #000; font-weight: bold; padding: 12px 25px; border: none; border-radius: 5px; cursor: pointer; font-size: 1em; transition: 0.2s; }}
                button:hover {{ background-color: #00cc52; }}
            </style>
        </head>
        <body>
            <h2>Auto-Forwarder Control Panel 🟢</h2>
            <div class="info">পেজটি প্রতি ৫ সেকেন্ড পর পর অটো-রিফ্রেশ হবে। নিচের ফর্ম থেকে নতুন গ্রুপ যোগ করতে পারবেন।</div>
            
            {notification}
            
            <!-- নতুন গ্রুপ যোগ করার ফর্ম -->
            <div class="form-box">
                <h3 style="color: #fff; margin-top: 0; margin-bottom: 12px;">➕ নতুন ডেস্টিনেশন গ্রুপ/চ্যানেল যোগ করুন</h3>
                <form action="/add-web-group" method="post" style="display: flex; gap: 10px;">
                    <input type="text" name="target" placeholder="যেমন: @Free_Promotion_V2 বা আইডি -1002300221011" required>
                    <button type="submit">যোগ করুন</button>
                </form>
            </div>

            <h3 style="color: #fff;">📜 লাইভ রান লোগস:</h3>
            <div class="container">
                {log_html if log_html else "<p style='color: #888;'>কোনো লগ নেই এখনো। মেইন লুপ শুরু হওয়া পর্যন্ত অপেক্ষা করুন...</p>"}
            </div>
        </body>
    </html>
    """

@app.post("/add-web-group")
def api_add_web_group(target: str = Form(...)):
    """
    ওয়েব ফর্ম থেকে ডাটা রিসিভ করে ডুপ্লিকেট চেক করার ফাংশন
    """
    try:
        added = add_destination(target)
        if added:
            log_event(f"➕ ওয়েব ফর্মের মাধ্যমে লিস্টে নতুন গ্রুপ যোগ করা হয়েছে: {target}")
            return RedirectResponse(url="/logs?msg=success", status_code=303)
        else:
            return RedirectResponse(url="/logs?msg=exists", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/logs?msg=error&err={str(e)}", status_code=303)

@app.get("/")
@app.api_route("/", methods=["GET", "HEAD"])
def read_root():
    return RedirectResponse(url="/logs")

@app.post("/add-group")
def api_add_group(target: str):
    try:
        added = add_destination(target)
        if added:
            return {"status": "Success", "message": f"'{target}' সফলভাবে যোগ করা হয়েছে।"}
        else:
            return {"status": "Exists", "message": f"'{target}' ইতিমধ্যে লিস্টে বিদ্যমান রয়েছে।"}
    except Exception as e:
        return {"status": "Error", "message": str(e)}

def extract_telegram_target(link_or_text):
    if not link_or_text:
        return None
        
    link = link_or_text.strip().rstrip(".,;!)[]{}")
    
    if link.startswith("@"):
        return f"@{link.lstrip('@')}"
        
    if "+" in link or "joinchat/" in link:
        match = re.search(r"(?:\+|joinchat/)([a-zA-Z0-9_-]+)", link)
        if match:
            return f"join_private:{match.group(1)}"
    else:
        match = re.search(r"(?:t\.me|telegram\.me|telegram\.dog)/([a-zA-Z0-9_]+)", link)
        if match:
            username = match.group(1)
            if username.lower() not in ["share", "addstickers", "joinchat", "s", "c"]:
                return f"@{username}"
                
    return None

def extract_targets_from_message(chat_msg):
    targets = set()
    text = chat_msg.text or ""
    
    usernames = re.findall(r"@([a-zA-Z0-9_]+)", text)
    for u in usernames:
        targets.add(f"@{u}")
        
    links = re.findall(r"(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)/\S+", text)
    for link in links:
        parsed = extract_telegram_target(link)
        if parsed:
            targets.add(parsed)
            
    if chat_msg.buttons:
        for row in chat_msg.buttons:
            for btn in row:
                if hasattr(btn, 'url') and btn.url:
                    parsed = extract_telegram_target(btn.url)
                    if parsed:
                        targets.add(parsed)
                if hasattr(btn, 'text') and btn.text:
                    btn_usernames = re.findall(r"@([a-zA-Z0-9_]+)", btn.text)
                    for u in btn_usernames:
                        targets.add(f"@{u}")
                        
    if chat_msg.entities:
        for entity in chat_msg.entities:
            if isinstance(entity, MessageEntityTextUrl):
                parsed = extract_telegram_target(entity.url)
                if parsed:
                    targets.add(parsed)
                    
    return targets

def is_mentioned_in_message(chat_msg, my_info):
    """
    মেসেজে আপনার অ্যাকাউন্টের নাম, আইডি বা ইউজারনেম মেনশন করা আছে কি না যাচাই করার জন্য বিশেষ ফিল্টার
    """
    text = (chat_msg.text or "").lower()
    my_id = str(my_info["id"])
    
    # ১. সরাসরি আইডি টেক্সট চেক
    if my_id in text:
        return True
        
    # ২. টেলিগ্রাম ইন্টারনাল মেনশন সত্ত্বা (Entity) চেক
    if chat_msg.entities:
        for entity in chat_msg.entities:
            if isinstance(entity, MessageEntityMentionName) and str(entity.user_id) == my_id:
                return True
                
    # ৩. ইমোজি বা অন্যান্য স্পেশাল ক্যারেক্টার ছাড়া নামের মূল অংশ চেক
    first_name = my_info["first_name"] or ""
    clean_first = re.sub(r'[^\w\s]', '', first_name).strip().lower()
    if clean_first and clean_first in text:
        return True
        
    # নামের একাধিক শব্দ থাকলে বড় শব্দগুলো চেক করা
    if clean_first:
        words = [w for w in clean_first.split() if len(w) > 2]
        for w in words:
            if w in text:
                return True
                
    # ৪. ইউজারনেম চেক
    username = my_info["username"].lower() if my_info["username"] else ""
    if username and username in text:
        return True
        
    return False

def is_warning_message(chat_msg, my_info):
    """
    গ্রুপের মেসেজটি আমাদের উদ্দেশ্যে পাঠানো জয়েনিং ওয়ার্নিং কি না তা ডিটেক্ট করা
    """
    if chat_msg.sender_id == my_info["id"]:
        return False
        
    # আমরা মেনশনড না থাকলে এটি অন্যদের সাধারণ বিজ্ঞাপন পোস্ট, কোনো ওয়ার্নিং নয়
    if not is_mentioned_in_message(chat_msg, my_info):
        return False
        
    text = (chat_msg.text or "").lower()
    
    # সাবস্ক্রিপশন ওয়ার্নিং-এর সাধারণ কিওয়ার্ডসমূহ
    keywords = ["subscribe", "join", "channels", "write in", "to write", "fsub", "force", "promotion", "group", "সদস্য", "জয়েন", "বাধ্যতামূলক", "সাবস্ক্রাইব"]
    has_keyword = any(kw in text for kw in keywords)
    
    has_buttons = True if chat_msg.buttons else False
    
    if has_keyword and (has_buttons or "@" in text or "t.me" in text):
        return True
        
    return False

async def join_target(client, target):
    try:
        if target.startswith("join_private:"):
            invite_hash = target.split(":", 1)[1]
            log_event(f"🔗 প্রাইভেট জয়েন রিকোয়েস্ট পাঠানো হচ্ছে। হ্যাশ: {invite_hash}...")
            await client(ImportChatInviteRequest(invite_hash))
            log_event(f"✅ প্রাইভেট চ্যানেলে সফলভাবে জয়েন করা হয়েছে!")
            return True
        else:
            username = target.lstrip('@')
            log_event(f"📣 পাবলিক চ্যানেলে জয়েন করা হচ্ছে: @{username}...")
            entity = await client.get_entity(username)
            await client(JoinChannelRequest(entity))
            log_event(f"✅ সফলভাবে জয়েন করা হয়েছে: @{username}")
            return True
    except UserAlreadyParticipantError:
        log_event(f"ℹ️ ইতিমধ্যে {target} চ্যানেলে জয়েন করা আছেন।")
        return False  # ইতিমধ্যে জয়েনড থাকলে False যাতে ডাবল পোস্টিং লুপ ট্রিগার না হয়
    except Exception as e:
        log_event(f"❌ জয়েন করতে ব্যর্থ {target}: {e}")
        return False

async def leave_channel_safely(client, channel_target):
    try:
        if channel_target.startswith("join_private:"):
            invite_hash = channel_target.split(":", 1)[1]
            try:
                entity = await client.get_entity(invite_hash)
                await client(LeaveChannelRequest(entity))
                log_event(f"🧹 ৭ দিন পূর্ণ হওয়ায় প্রাইভেট চ্যানেল থেকে লিভ নেওয়া হয়েছে: {channel_target}")
                return True
            except Exception as e_res:
                try:
                    entity = await client.get_entity(f"https://t.me/+{invite_hash}")
                    await client(LeaveChannelRequest(entity))
                    log_event(f"🧹 ৭ দিন পূর্ণ হওয়ায় প্রাইভেট চ্যানেল থেকে লিভ নেওয়া হয়েছে: {channel_target}")
                    return True
                except Exception as e_link:
                    log_event(f"❌ প্রাইভেট চ্যানেল থেকে লিভ নিতে সম্পূর্ণ ব্যর্থ: {e_link}")
                    return False
        else:
            username = channel_target.lstrip('@')
            entity = await client.get_entity(username)
            await client(LeaveChannelRequest(entity))
            log_event(f"🧹 ৭ দিন পূর্ণ হওয়ায় পাবলিক চ্যানেল থেকে লিভ নেওয়া হয়েছে: @{username}")
            return True
    except Exception as e:
        log_event(f"❌ চ্যানেল {channel_target} থেকে লিভ নেওয়ার সময় ত্রুটি: {e}")
        return False

async def check_and_leave_old_channels(client):
    while True:
        try:
            joined_data = load_joined_data()
            current_time = time.time()
            updated_data = {}
            
            for channel, join_time in joined_data.items():
                if current_time - join_time >= 604800: # ৭ দিন
                    success = await leave_channel_safely(client, channel)
                    if not success:
                        updated_data[channel] = join_time
                else:
                    updated_data[channel] = join_time
                    
            save_joined_data(updated_data)
        except Exception as e:
            log_event(f"Cleanup error: {e}")
            
        await asyncio.sleep(86400)

async def scan_and_join_required_channels(client, group_id, my_info):
    log_event(f"🔍 {group_id} গ্রুপে কোনো ফোর্স-জয়েন নির্দেশিকা আছে কিনা স্ক্যান করা হচ্ছে...")
    joined_any = False
    
    # গ্রুপের সর্বশেষ ১০টি মেসেজ স্ক্যান করা হচ্ছে
    async for chat_msg in client.iter_messages(group_id, limit=10):
        if is_warning_message(chat_msg, my_info):
            targets = extract_targets_from_message(chat_msg)
            
            # সোর্স আইডি, গ্রুপ আইডি বা নিজের ইউজারনেম ফিল্টার করা
            filtered_targets = []
            for target in targets:
                clean_t = target.lower()
                if clean_t not in [str(SOURCE_CHANNEL_ID).lower(), str(group_id).lower(), f"@{my_info['username'].lower()}"]:
                    filtered_targets.append(target)
            
            if filtered_targets:
                log_event(f"⚠️ {group_id}-এ ফোর্স-জয়েন লিংক সনাক্ত হয়েছে: {filtered_targets}")
                for target in filtered_targets:
                    joined = await join_target(client, target)
                    if joined:
                        joined_any = True
                        joined_data = load_joined_data()
                        joined_data[target] = time.time()
                        save_joined_data(joined_data)
                        await asyncio.sleep(3)
                break 
                
    return joined_any

async def start_repeater():
    if not SESSION_STRING:
        log_event("❌ ভুল: SESSION_STRING পরিবেশ ভেরিয়েবলে বসানো হয়নি!")
        return

    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    
    try:
        log_event("⚙️ টেলিগ্রাম সার্ভারে কানেক্ট করা হচ্ছে...")
        await client.connect()
    except Exception as e:
        log_event(f"❌ কানেক্ট করতে ব্যর্থ: {e}")
        return
        
    if not await client.is_user_authorized():
        log_event("❌ সেশন অথরাইজড নয়! আপনার SESSION_STRING মেয়াদোত্তীর্ণ বা ভুল। দয়া করে নতুন সেশন জেনারেট করে বসান।")
        return
        
    log_event("⚙️ গ্রুপ এবং ডায়ালগগুলো লোড করা হচ্ছে...")
    await client.get_dialogs() 
    
    # অ্যাকাউন্টের ইনফো লোড
    me = await client.get_me()
    my_info = {
        "id": me.id,
        "first_name": me.first_name or "",
        "last_name": me.last_name or "",
        "username": me.username or ""
    }
    log_event(f"👤 সফলভাবে লগইন করা হয়েছে: {my_info['first_name']} (@{my_info['username']}) [ID: {my_info['id']}]")
    
    asyncio.create_task(check_and_leave_old_channels(client))
    log_event("🚀 অটো-পোস্ট এবং অটো-জয়েন সক্রিয় হয়েছে...")
    
    while True:
        try:
            DESTINATION_GROUP_IDS = load_destinations()
            
            last_msg = None
            async for message in client.iter_messages(SOURCE_CHANNEL_ID, limit=1):
                last_msg = message
                break
            
            if last_msg:
                for group_id in DESTINATION_GROUP_IDS:
                    try:
                        log_event(f"📨 মেসেজ পাঠানো হচ্ছে: {group_id}")
                        await client.forward_messages(group_id, last_msg)
                        log_event(f"✅ মেসেজ পাঠানো হয়েছে: {group_id}")
                        
                        await asyncio.sleep(4)
                        
                        joined = await scan_and_join_required_channels(client, group_id, my_info)
                        if joined:
                            log_event(f"🔄 প্রয়োজনীয় চ্যানেলে জয়েন সম্পন্ন! {group_id}-এ আবার মেসেজ পাঠানো হচ্ছে...")
                            await asyncio.sleep(3)
                            await client.forward_messages(group_id, last_msg)
                            log_event(f"✅ পুনরায় মেসেজ পাঠানো সফল হয়েছে: {group_id}")
                        
                        await asyncio.sleep(5)
                        
                    except Exception as e:
                        err_str = str(e)
                        log_event(f"❌ {group_id} এ পাঠাতে সরাসরি সমস্যা হয়েছে: {err_str}")
                        
                        if any(kw in err_str.lower() for kw in ["channel", "chat", "join", "not a member", "subscribe", "forbidden"]):
                            joined = await scan_and_join_required_channels(client, group_id, my_info)
                            if joined:
                                try:
                                    await asyncio.sleep(5)
                                    await client.forward_messages(group_id, last_msg)
                                    log_event(f"✅ জয়েন করার পর মেসেজ সফলভাবে রি-ফরোয়ার্ড হয়েছে: {group_id}")
                                except Exception as retry_err:
                                    log_event(f"❌ পুনরায় পাঠাতে ব্যর্থ {group_id}: {retry_err}")
            
            log_event(f"💤 পরবর্তী ফরোয়ার্ডের জন্য {INTERVAL} SECOND অপেক্ষা করা হচ্ছে...")
            await asyncio.sleep(INTERVAL)
            
        except Exception as e:
            log_event(f"⚠️ মেইন লুপে সমস্যা: {e}")
            await asyncio.sleep(60)

def run_bg():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_repeater())

if __name__ == "__main__":
    threading.Thread(target=run_bg, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=7860)