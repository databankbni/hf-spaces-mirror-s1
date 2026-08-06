import os
import logging
import subprocess
import random
from typing import Dict, Any, Tuple, List

logger = logging.getLogger("transcript_analyzer")

class TranscriptAnalyzer:
    """
    AI Transcript Analyzer Service.
    Handles Speech-to-Text transcription (via SpeechRecognition or VOD captions),
    computes excitement/narrative sentiment scores, and refines clip boundaries.
    """
    def __init__(self, temp_dir: str = "./scratch/audio"):
        self.temp_dir = temp_dir
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Curated demo quotes for simulated speech analysis when testing or offline
        self.demo_quotes = [
            ("Oh my god, chat look at this! We just pulled off the craziest 1v5 clutch in tournament history!", 0.95, "🔥 High Excitement - Viral Clutch Play"),
            ("No way dude, what just happened?! Did you guys see that?! That is 100% getting clipped!", 0.92, "🔥 High Excitement - Streamer Reaction"),
            ("Wait wait wait, let me explain why this new item build is absolutely broken in the current meta right now.", 0.75, "💡 Engaging Story / Meta Analysis"),
            ("Alright chat, focus up. This is the final boss fight and we only have one life left. Let's go!", 0.85, "⚡ Intense Gameplay - Boss Fight"),
            ("Hahaha! Why would you do that?! Look at chat laughing, that was the funniest troll play ever!", 0.88, "😂 Hilarious Moment - Chat Interaction"),
            ("We are actually unbeatable today! That's ten wins in a row, let's keep the streak alive!", 0.82, "🏆 Victory Celebration - High Energy"),
            ("Honestly guys, thank you so much for the insane support today. You are the best community ever.", 0.65, "❤️ Wholesome Community Moment"),
            ("Watch this angle right here. If they push around this corner, we have the perfect trap set up.", 0.70, "🧠 Tactical Commentary / Pro Play")
        ]

    def analyze_window(self, url: str, start_time: float, end_time: float, is_demo: bool = False) -> Dict[str, Any]:
        """
        Analyzes the speech and transcript within a specific timestamp window.
        Returns dict with transcript text, sentiment score, narrative badge, and refined timestamps.
        """
        duration = end_time - start_time
        logger.info(f"Analyzing speech transcript for {url} ({start_time}s - {end_time}s, dur {duration}s)")

        if is_demo or "demo" in url.lower() or not url.strip():
            return self._generate_simulated_analysis(start_time, end_time)

        # Attempt real speech-to-text audio extraction and transcription
        try:
            transcript = self._transcribe_audio_window(url, start_time, end_time)
            if not transcript or len(transcript.strip()) < 5:
                logger.info("Real speech transcription empty or low confidence, using fallback quote.")
                return self._generate_simulated_analysis(start_time, end_time)
                
            score, badge = self.compute_excitement_score(transcript)
            ref_start, ref_end = self.refine_boundaries(start_time, end_time, transcript)
            hook = self.generate_viral_hook(transcript, badge)
            
            return {
                "status": "success",
                "transcript": transcript,
                "sentiment_score": score,
                "narrative_badge": badge,
                "viral_hook": hook,
                "refined_start": ref_start,
                "refined_end": ref_end,
                "is_simulated": False
            }
        except Exception as e:
            logger.warning(f"Speech transcription failed for {url}: {e}. Falling back to simulated speech analysis.")
            return self._generate_simulated_analysis(start_time, end_time)

    def generate_viral_hook(self, text: str, badge: str, chat_sample: str = "") -> str:
        """
        Generates an attention-grabbing social media hook/title for TikTok/Shorts based on speech and chat keywords.
        """
        text_lower = text.lower()
        chat_lower = chat_sample.lower()
        combined = f"{text_lower} {chat_lower}"

        if "clutch" in combined or "1v5" in combined or "won" in combined:
            return "When You Pull Off The Craziest 1v5 Clutch! 😱🔥"
        elif "jump" in combined or "rage" in combined or "cry" in combined or "stuck" in combined:
            return "Streamer Rages At Impossible Jump! 😡💀"
        elif "meta" in combined or "broken" in combined or "build" in combined or "explain" in combined:
            return "Why This New Meta Strategy Is Absolutely Broken! 💡🧠"
        elif "troll" in combined or "funny" in combined or "laugh" in combined or "haha" in combined or "lol" in combined or "lmao" in combined:
            return "The Funniest Chat Reaction You Will Ever See! 😂🤣"
        elif "secret" in combined or "vidcon" in combined or "leaving" in combined:
            return "Streamer Drops Massive Secret Live On Stream! 🤫🔥"
        elif "boss" in combined or "fight" in combined or "life left" in combined:
            return "Final Boss Fight With Only One Life Left! ⚡🎮"
        elif "kissing" in combined or "lesbian" in combined or "yuri" in combined or "girl" in combined or "boy" in combined:
            return "Streamer Gets Caught Talking About Anime Ships! 😳🤣"
        elif "streak" in combined or "unbeatable" in combined or "wins" in combined:
            return "10 Win Streak! We Are Actually Unbeatable Today! 🏆🔥"
        elif "support" in combined or "wholesome" in combined or "best community" in combined:
            return "The Most Wholesome Community Moment Ever! ❤️🥺"
        elif "died" in combined or "die there" in combined or "freeze frame" in combined:
            return "How Did I Even Die There?! Perfect Freeze Frame! 😭💀"
        elif "highlight" in combined or "points" in combined or "redeem" in combined or "trap" in combined:
            return "When Chat Spends All Their Points To Troll The Streamer! 🤣📈"
        elif "High Excitement" in badge:
            return "Absolute Viral Hype Moment! Watch Until The End! 🔥⚡"
        elif "Intense Gameplay" in badge:
            return "Insane Clutch Play You Have To See To Believe! ⚡🎮"
        elif "Hilarious" in badge:
            return "Chat Had The Streamer Absolutely Dying Of Laughter! 😂💀"
        else:
            words = [w.strip(".,?!\"'") for w in text.split() if len(w) > 1][:6]
            if words:
                clean_title = " ".join(words).title()
                return f'"{clean_title}..." Wait For It! 😲🔥'
            return "Crazy Streamer Highlight Moment! 🔥👀"

    def _transcribe_audio_window(self, url: str, start_time: float, end_time: float) -> str:
        """
        Extracts temporary WAV audio via FFmpeg fast-seek and transcribes using SpeechRecognition.
        """
        try:
            import speech_recognition as sr
            import yt_dlp
        except ImportError:
            logger.warning("SpeechRecognition or yt-dlp not available.")
            return ""

        temp_wav = os.path.join(self.temp_dir, f"temp_{int(start_time)}_{int(end_time)}.wav")
        duration = max(3.0, min(end_time - start_time, 120.0)) # Cap audio transcription snippet to 2 mins for speed

        try:
            # Get stream manifest URL
            with yt_dlp.YoutubeDL({'format': 'bestaudio/best', 'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                stream_url = info.get('url') or info.get('manifest_url')

            if not stream_url:
                return ""

            # Extract 16kHz mono PCM WAV audio using FFmpeg fast-seek
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_time),
                "-i", stream_url,
                "-t", str(duration),
                "-ar", "16000", "-ac", "1",
                "-c:a", "pcm_s16le",
                temp_wav
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            if not os.path.exists(temp_wav) or os.path.getsize(temp_wav) == 0:
                return ""

            # Run SpeechRecognition
            r = sr.Recognizer()
            with sr.AudioFile(temp_wav) as source:
                audio_data = r.record(source)
            
            text = r.recognize_google(audio_data)
            logger.info(f"Transcribed text: '{text}'")
            return text
        finally:
            if os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except Exception:
                    pass

    def compute_excitement_score(self, text: str) -> Tuple[float, str]:
        """
        Evaluates transcribed speech for excitement keywords, humor, and narrative value.
        Returns (score_between_0_and_1, narrative_badge_string).
        """
        text_lower = text.lower()
        score = 0.5 # Base score
        
        hype_words = ["no way", "oh my god", "omg", "clutch", "let's go", "lets go", "insane", "crazy", "pog", "clip", "holy", "won", "victory", "gg", "best", "unbelievable"]
        humor_words = ["haha", "lol", "lmao", "funny", "dead", "troll", "prank", "hilarious", "joke", "laugh"]
        intense_words = ["watch this", "listen", "meta", "broken", "boss", "fight", "focus", "careful", "pro", "level", "streak", "trap"]

        hype_count = sum(1 for w in hype_words if w in text_lower)
        humor_count = sum(1 for w in humor_words if w in text_lower)
        intense_count = sum(1 for w in intense_words if w in text_lower)

        score += min(0.35, hype_count * 0.15)
        score += min(0.25, humor_count * 0.12)
        score += min(0.20, intense_count * 0.10)
        
        score = round(min(1.0, max(0.1, score)), 2)

        if score >= 0.85:
            badge = "🔥 High Excitement - Viral Moment"
        elif score >= 0.70:
            badge = "⚡ Intense Gameplay / Clutch Play"
        elif humor_count > 0:
            badge = "😂 Hilarious Moment - Chat Interaction"
        elif score >= 0.55:
            badge = "💡 Engaging Story / Commentary"
        else:
            badge = "💬 Casual Stream Dialogue"

        return score, badge

    def refine_boundaries(self, start_time: float, end_time: float, text: str) -> Tuple[float, float]:
        """
        Adjusts start and end timestamps slightly so speech isn't cut off abruptly.
        Adds a 3-5 second smart buffer before and after the speech peak.
        """
        # Extend start by 3 seconds (to catch setup) and end by 3 seconds (to catch reaction)
        refined_start = max(0.0, round(start_time - 3.0, 1))
        refined_end = round(end_time + 3.0, 1)
        return refined_start, refined_end

    def _generate_simulated_analysis(self, start_time: float, end_time: float) -> Dict[str, Any]:
        """
        Generates realistic simulated speech analysis for demo mode or fallback.
        Selects quote based on timestamp hash for determinism during a session.
        """
        idx = int(start_time // 10) % len(self.demo_quotes)
        quote, score, badge = self.demo_quotes[idx]
        
        ref_start, ref_end = self.refine_boundaries(start_time, end_time, quote)
        hook = self.generate_viral_hook(quote, badge)
        return {
            "status": "success",
            "transcript": quote,
            "sentiment_score": score,
            "narrative_badge": badge,
            "viral_hook": hook,
            "refined_start": ref_start,
            "refined_end": ref_end,
            "is_simulated": True
        }
