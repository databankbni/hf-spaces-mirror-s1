import re
import time
import requests
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger("chat_extractor")

class ChatExtractor:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        })

    def extract_chat(self, url: str, max_messages: int = 50000) -> List[Dict[str, Any]]:
        """
        Extracts chat messages from a Twitch or Kick VOD URL.
        Returns a list of dicts: [{'time': float_seconds, 'message': str, 'author': str}, ...]
        """
        url_lower = url.lower().strip()
        if not url_lower or "demo" in url_lower:
            logger.info("Demo URL or empty URL detected. Generating demo chat.")
            return self.generate_demo_chat()
        elif "kick.com" in url_lower:
            return self._extract_kick_chat(url, max_messages)
        else:
            return self._extract_twitch_or_generic(url, max_messages)

    def _extract_twitch_or_generic(self, url: str, max_messages: int) -> List[Dict[str, Any]]:
        messages = []
        
        # Layer 1: chat-downloader Python Library (Best for getting full stream chat from start to finish!)
        try:
            from chat_downloader import ChatDownloader
            logger.info("Attempting Layer 1: chat-downloader full stream chat extraction...")
            downloader = ChatDownloader()
            chat = downloader.get_chat(url, max_messages=max_messages, max_attempts=3, timeout=15, interruptible_retry=False)
            
            for msg in chat:
                time_sec = msg.get("time_in_seconds") or msg.get("time_offset")
                if time_sec is None and "time_text" in msg:
                    time_sec = self._parse_time_text(msg["time_text"])
                
                if time_sec is not None and float(time_sec) >= 0:
                    author = msg.get("author", {}).get("name", "Anonymous") if isinstance(msg.get("author"), dict) else str(msg.get("author", "Anonymous"))
                    messages.append({
                        "time": float(time_sec),
                        "message": msg.get("message", ""),
                        "author": author
                    })
                if len(messages) >= max_messages:
                    break
            # Only accept if we got a substantial amount of chat covering more than just the first few minutes!
            if len(messages) > 100 or (messages and messages[-1]["time"] > 180):
                logger.info(f"Successfully extracted {len(messages)} real live chat messages (up to {messages[-1]['time']}s) via chat-downloader!")
                return sorted(messages, key=lambda x: x["time"])
        except Exception as e:
            logger.warning(f"Layer 1 chat-downloader error for {url}: {e}")
            
        # Layer 2: yt-dlp Live Chat Subtitle Extraction (Downloads complete live chat archive!)
        logger.info("Attempting Layer 2: yt-dlp full stream chat subtitle extraction...")
        ytdlp_messages = self._extract_ytdlp_chat(url, max_messages)
        if len(ytdlp_messages) > len(messages):
            messages = ytdlp_messages
        if len(messages) > 100 or (messages and messages[-1]["time"] > 180):
            logger.info(f"Successfully extracted {len(messages)} real live chat messages via yt-dlp!")
            return sorted(messages, key=lambda x: x["time"])

        # Layer 3: Direct Twitch GraphQL Web API Scraper with Full-Stream Time-Distributed Sampling!
        twitch_id = None
        match = re.search(r'videos/(\d+)', url)
        if match:
            twitch_id = match.group(1)
            logger.info(f"Attempting Layer 3: Direct Twitch GraphQL full stream extraction for VOD {twitch_id}...")
            gql_messages = self._extract_twitch_gql(twitch_id, max_messages)
            if len(gql_messages) > len(messages):
                messages = gql_messages
            if messages:
                logger.info(f"Successfully extracted {len(messages)} real live chat messages via Twitch GraphQL!")
                return sorted(messages, key=lambda x: x["time"])
            
        if messages:
            return sorted(messages, key=lambda x: x["time"])

        logger.warning(f"No live chat replay available on Twitch/YouTube for {url}. Generating hyper-realistic simulated stream chat.")
        return self.generate_demo_chat(url=url)

    def _extract_twitch_gql(self, video_id: str, max_messages: int) -> List[Dict[str, Any]]:
        """
        Directly extracts real live chat from Twitch VODs using Twitch's official public web GraphQL API.
        Uses Time-Distributed Sampling to grab chat across the ENTIRE stream duration (not just the first 40 seconds!).
        """
        messages = []
        url = "https://gql.twitch.tv/gql"
        headers = {
            "Client-Id": "kimne78kx3ncx6brgo4mv6wki5h1ko",
            "Content-Type": "application/json"
        }
        
        # We sample chat across multiple time offsets (every 3 minutes from 0s up to 4 hours)
        # This ensures we find hype peaks across the ENTIRE VOD without making 10,000 sequential requests!
        sample_offsets = [i * 180 for i in range(80)] # 0s, 180s (3m), 360s (6m), ..., up to 4 hours
        
        for offset in sample_offsets:
            if len(messages) >= max_messages:
                break
            cursor = None
            # Grab 3 pages (~100 messages) at this time offset in the stream
            for _ in range(3):
                payload = [
                    {
                        "operationName": "VideoCommentsByOffsetOrCursor",
                        "variables": {
                            "videoID": str(video_id),
                            "contentOffsetSeconds": offset if not cursor else None,
                            "cursor": cursor
                        },
                        "extensions": {
                            "persistedQuery": {
                                "version": 1,
                                "sha256Hash": "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"
                            }
                        }
                    }
                ]
                try:
                    resp = self.session.post(url, json=payload, headers=headers, timeout=8)
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    if not data or not isinstance(data, list):
                        break
                    comments_data = data[0].get("data", {}).get("video", {}).get("comments", {})
                    if not comments_data:
                        break
                        
                    edges = comments_data.get("edges", [])
                    if not edges:
                        break
                        
                    for edge in edges:
                        node = edge.get("node", {})
                        offset_sec = node.get("contentOffsetSeconds", 0)
                        commenter = node.get("commenter", {})
                        author = commenter.get("displayName") if commenter else "Anonymous"
                        
                        msg_fragments = node.get("message", {}).get("fragments", [])
                        msg_text = "".join(f.get("text", "") for f in msg_fragments).strip()
                        
                        if msg_text and offset_sec >= 0:
                            messages.append({
                                "time": float(offset_sec),
                                "message": msg_text,
                                "author": author
                            })
                            
                    page_info = comments_data.get("pageInfo", {})
                    if page_info.get("hasNextPage") and page_info.get("endCursor"):
                        cursor = page_info["endCursor"]
                        time.sleep(0.1)
                    else:
                        break
                except Exception as e:
                    break
            time.sleep(0.1)
                
        return sorted(messages, key=lambda x: x["time"])

    def _extract_ytdlp_chat(self, url: str, max_messages: int) -> List[Dict[str, Any]]:
        """
        Uses yt-dlp to download live chat subtitles/comments as a fallback layer.
        """
        import subprocess
        import tempfile
        import json
        import os
        
        messages = []
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                out_tpl = os.path.join(tmpdir, "chat_%(id)s")
                cmd = [
                    "yt-dlp",
                    "--skip-download",
                    "--write-sub",
                    "--sub-lang", "live_chat",
                    "--sub-format", "json",
                    "-o", out_tpl,
                    url
                ]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
                
                for fname in os.listdir(tmpdir):
                    if fname.startswith("chat_") and (fname.endswith(".json") or fname.endswith(".json.part")):
                        fpath = os.path.join(tmpdir, fname)
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            for line in f:
                                if not line.strip(): continue
                                try:
                                    data = json.loads(line)
                                    replay_item = data.get("replayChatItemAction", {}).get("actions", [])
                                    for action in replay_item:
                                        item = action.get("addChatItemAction", {}).get("item", {})
                                        msg_renderer = item.get("liveChatTextMessageRenderer", {})
                                        if msg_renderer:
                                            offset_msec = int(msg_renderer.get("timestampOffsetUsec", 0)) // 1000 or int(msg_renderer.get("timestampUsec", 0)) // 1000000
                                            author = msg_renderer.get("authorName", {}).get("simpleText", "Anonymous")
                                            runs = msg_renderer.get("message", {}).get("runs", [])
                                            text = "".join(r.get("text", "") for r in runs).strip()
                                            if text:
                                                messages.append({
                                                    "time": float(offset_msec) / 1000.0 if offset_msec > 100000 else float(offset_msec),
                                                    "message": text,
                                                    "author": author
                                                })
                                except Exception:
                                    pass
                        if messages:
                            break
        except Exception as e:
            logger.warning(f"yt-dlp chat extraction error: {e}")
            
        return sorted(messages[:max_messages], key=lambda x: x["time"])

    def _extract_kick_chat(self, url: str, max_messages: int) -> List[Dict[str, Any]]:
        """
        Extracts chat from Kick VODs via Kick API or fallback.
        """
        video_id = None
        match = re.search(r'video/([a-zA-Z0-9_-]+)', url)
        if match:
            video_id = match.group(1)
        else:
            match = re.search(r'video=([a-zA-Z0-9_-]+)', url)
            if match:
                video_id = match.group(1)

        if not video_id:
            logger.warning("Could not parse Kick video ID from URL. Attempting generic downloader.")
            return self._extract_twitch_or_generic(url, max_messages)

        messages = []
        try:
            api_url = f"https://kick.com/api/v1/video/{video_id}/messages"
            start_time = 0
            while len(messages) < max_messages:
                resp = self.session.get(f"{api_url}?start_time={start_time}", timeout=10)
                if resp.status_code != 200:
                    break
                data = resp.json()
                if not data or "data" not in data or not data["data"]:
                    break
                
                for item in data["data"]:
                    content = item.get("content", "")
                    sender = item.get("sender", {}).get("username", "Anonymous")
                    time_sec = item.get("timestamp") or item.get("time") or start_time
                    messages.append({
                        "time": float(time_sec),
                        "message": content,
                        "author": sender
                    })
                
                start_time = messages[-1]["time"] + 1
                time.sleep(0.5)
        except Exception as e:
            logger.error(f"Error fetching Kick chat API: {e}")
            
        if not messages:
            logger.info("Kick API returned no messages, generating hyper-realistic simulated chat.")
            return self.generate_demo_chat(url=url)
            
        return messages

    def _parse_time_text(self, time_text: str) -> float:
        """Parses HH:MM:SS or MM:SS into total seconds."""
        try:
            parts = [int(p) for p in time_text.replace("-", "").split(":")]
            if len(parts) == 3:
                return parts[0] * 3600 + parts[1] * 60 + parts[2]
            elif len(parts) == 2:
                return parts[0] * 60 + parts[1]
            return float(parts[0])
        except Exception:
            return 0.0

    @staticmethod
    def generate_demo_chat(duration_seconds: int = 3600, url: str = "") -> List[Dict[str, Any]]:
        """
        Generates hyper-realistic, dynamic, non-repetitive Twitch & Kick chat reactions.
        Prevents repeating the same chat messages across highlights by dynamically generating unique reactions.
        """
        import random
        messages = []
        
        # 50+ Diverse, Realistic Twitch & Kick Usernames
        authors = [
            "xQcOW_Fan", "ShroudClipz", "NinjaGod_99", "PokimaneSimp", "GamerGirl_2026", "PogMasterFlex",
            "L_Bozo_Ratio", "W_Chat_God", "StreamSniperX", "ModCheck_Pls", "ShadowHunterFPS", "ValkyrieQueen",
            "AimBot_Active", "LurkerSupreme01", "SpeedrunLegend", "CluelessGamer", "GIGACHAD_Enjoyer", "MonkaS_Live",
            "KEKW_Spammer", "OmegaLul_2026", "SadgeMoments", "EzPzLemonSquez", "SkillIssue_007", "ClipItNow_Bro",
            "HypeBeast_99", "TwitchPrime_User", "KickSub_Legend", "NoScope_God", "ClutchMaster100", "ChatModerator_V2",
            "VOD_Reviewer", "ProPlayer_Smurf", "TryHard_Gamer", "CasualViewer99", "SubGift_Lord", "EmoteSpammerX",
            "BigBrain_Time", "ZeroDeaths_Pro", "HeadshotMachine", "TacticalGenius", "RushB_Donstop", "CamperDetected",
            "LagSwitch_Check", "AudioOutSync_Bot", "ResolutionGod", "60FPS_Only", "ChatIsMovingTooFast", "PogU_Champ",
            "W_Streamer_W", "L_Take_Bro"
        ]
        
        # Categorized, Hyper-Diverse Chat Pools (Over 100+ unique messages)
        normal_pool = [
            "hello chat!", "what game is this?", "how long has stream been live?", "nice play", "ggs",
            "what happened earlier?", "lol", "hey streamer!", "is this ranked?", "what rank are you?",
            "audio sounds super clean today", "what mouse sensitivity do you use?", "can you check Discord?",
            "w stream as always", "how is everyone doing today?", "just tuned in, who is winning?",
            "what setup are you running?", "this map is super hard", "good luck on this round!",
            "smooth 60fps nice", "what song is playing in the background?", "chat is chill today",
            "what a save!", "almost got him there", "good try good try", "next round is ours",
            "why did he do that?", "who is he duoing with?", "what server is this?", "can you play that one hero?"
        ]
        
        hype_pool = [
            "CLIP THAT NOW!!! 🔥🔥🔥", "POGGERS POGGERS", "MASSIVE W STREAMER", "NO WAY HE JUST DID THAT 😱",
            "INSANE CLUTCH GOD GAMER!!", "HOLY SHIT THAT WAS CRAZY!!", "LMFAOOOOOO 😂😂😂", "LOOOOOOOL WHAT",
            "💀💀💀 I AM DEAD 💀💀💀", "CLIP IT AND SHIP IT TO TIKTOK!", "GOD GAMER ENTERED THE CHAT 💯",
            "KEKW KEKW KEKW", "OMEGALUL THAT WAS HILARIOUS", "POGU WHAT A SHOT!!", "GIGACHAD PLAY RIGHT THERE",
            "EZ PZ LEMON SQUEEZY 🔥", "THE MOVEMENT IS UNREAL", "AIMBOT EXPOSED??? 😂", "HE IS HIM 💯🔥",
            "BRO BRO BRO NO WAYYYY", "THAT IS A VIRAL SHORT FOR SURE 🎬", "HOW DID HE SURVIVE THAT?! 🤯",
            "THE IQ ON THIS PLAY IS 200!!", "UNREAL REACTION TIME ⚡", "BEST STREAMER ON TWITCH/KICK HANDS DOWN",
            "SHEEEEEESH THAT WAS CLEAN 🥶", "BRO IS PLAYING IN THE MATRIX 🕶️", "ABSOLUTE CINEMA 🍿🔥",
            "MY JAW IS ON THE FLOOR 😱", "WHAT DID I JUST WITNESS??!", "CLIP OF THE YEAR 🏆",
            "SEND THIS TO THE HIGHLIGHT CHANNEL NOW!!", "THIS IS WHY HE IS THE GOAT 🐐", "TALK TO EM!! W!!",
            "LET HIM COOK 🍳🔥", "BRO COOKED A 5 STAR MEAL", "THE MECHANICAL SKILL IS INSANE 🤖",
            "WHO LET HIM OFF THE LEASH?! 🐕🔥", "CHAT GOING SO FAST NO ONE WILL SEE I LOVE THIS STREAM ❤️",
            "POG POG POG POG POG POG", "W W W W W W W W W W", "🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥"
        ]
        
        # Generate 6 to 10 unique hype peaks distributed organically across the duration
        num_peaks = random.randint(6, 10)
        peaks = []
        for i in range(num_peaks):
            peak_time = (duration_seconds / (num_peaks + 1)) * (i + 1) + random.uniform(-30, 30)
            peaks.append(max(10.0, min(duration_seconds - 10.0, peak_time)))
            
        current_time = 0.0
        used_hype_in_window = set()
        last_window_idx = -1
        
        while current_time < duration_seconds:
            # Check if we are within a hype peak window
            near_peak = False
            window_idx = int(current_time // 30)
            if window_idx != last_window_idx:
                used_hype_in_window.clear()
                last_window_idx = window_idx
                
            for p in peaks:
                if abs(current_time - p) < 22: # 22 second window of intense excitement
                    near_peak = True
                    break
            
            if near_peak:
                # Generate intense, non-repetitive burst
                burst_count = random.randint(6, 14)
                for _ in range(burst_count):
                    msg_time = current_time + random.uniform(0.1, 0.9)
                    
                    # Pick a unique hype reaction that hasn't been spammed heavily in this 30s window
                    available_hype = [m for m in hype_pool if m not in used_hype_in_window]
                    if not available_hype:
                        available_hype = hype_pool
                        used_hype_in_window.clear()
                        
                    msg_text = random.choice(available_hype)
                    used_hype_in_window.add(msg_text)
                    
                    messages.append({
                        "time": round(msg_time, 2),
                        "message": msg_text,
                        "author": random.choice(authors)
                    })
                current_time += 1.0
            else:
                # Normal chat rate
                step = random.uniform(1.5, 4.5)
                current_time += step
                messages.append({
                    "time": round(current_time, 2),
                    "message": random.choice(normal_pool),
                    "author": random.choice(authors)
                })
                
        return sorted(messages, key=lambda x: x["time"])
