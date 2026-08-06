import math
from typing import List, Dict, Any

class ChatAnalyzer:
    def __init__(self, interval_seconds: int = 15):
        self.interval = interval_seconds
        self.hype_keywords = {
            "clip": 3.0, "pog": 3.0, "poggers": 3.0, "pogchamp": 3.0,
            "omg": 2.5, "lol": 2.0, "lmao": 2.5, "rofl": 2.5,
            "w": 2.0, "l": 2.0, "insane": 3.0, "god": 2.5,
            "holy": 2.5, "wtf": 2.5, "nooo": 2.0, "yes": 2.0,
            "🔥": 3.0, "😂": 2.0, "💀": 2.5, "😭": 2.0, "👏": 2.0, "💯": 2.0
        }

    def analyze(
        self,
        messages: List[Dict[str, Any]],
        url: str = "",
        top_n: int = 5,
        before_peak_sec: int = 30,
        after_peak_sec: int = 15,
        min_distance_sec: int = 45,
        duration_mode: str = "short",
        enable_ai_speech: bool = True
    ) -> Dict[str, Any]:
        """
        Analyzes chat messages, computes time-series activity, and identifies top N highlight peaks.
        Supports duration_mode ('short', 'medium', 'long') and AI Speech-to-Text Transcript Analysis.
        """
        if not messages:
            return {"timeline": [], "highlights": [], "total_messages": 0, "duration_seconds": 0}

        # Configure time windows based on requested duration mode
        if duration_mode == "medium":
            before_peak_sec = 60
            after_peak_sec = 60
            min_distance_sec = 130
        elif duration_mode == "long":
            before_peak_sec = 240  # 4 minutes before peak
            after_peak_sec = 210   # 3.5 minutes after peak (total ~7.5 mins / 5-10m recap!)
            min_distance_sec = 480
        elif duration_mode == "viral_bunch":
            top_n = max(top_n, 15)  # Scan entire stream for maximum batch of viral shorts!
            before_peak_sec = 25    # 25 seconds before peak
            after_peak_sec = 15     # 15 seconds after peak (total 40s viral short!)
            min_distance_sec = 35   # Allow closer spacing for action-packed segments

        max_time = max(m["time"] for m in messages)
        num_bins = math.ceil(max_time / self.interval) + 1
        
        bins = [{
            "time": i * self.interval,
            "message_count": 0,
            "hype_score": 0.0,
            "sample_messages": []
        } for i in range(num_bins)]

        # Populate bins
        for msg in messages:
            t = msg["time"]
            idx = int(t // self.interval)
            if 0 <= idx < num_bins:
                bins[idx]["message_count"] += 1
                
                # Calculate weighted hype score
                score = 1.0
                text_lower = msg["message"].lower()
                
                for kw, weight in self.hype_keywords.items():
                    if kw in text_lower:
                        score += weight
                
                # Bonus for exclamation marks or all caps
                if "!" in msg["message"] or (len(msg["message"]) > 3 and msg["message"].isupper()):
                    score += 1.0
                    
                bins[idx]["hype_score"] += score
                
                # Keep up to 10 unique sample messages per bin for UI preview
                msg_str = f"{msg['author']}: {msg['message']}"
                if len(bins[idx]["sample_messages"]) < 10 and msg_str not in bins[idx]["sample_messages"]:
                    bins[idx]["sample_messages"].append(msg_str)

        # Format timeline for chart rendering (round numbers for clean JSON)
        timeline = []
        for b in bins:
            timeline.append({
                "time": b["time"],
                "time_formatted": self._format_time(b["time"]),
                "count": b["message_count"],
                "score": round(b["hype_score"], 1),
                "samples": b["sample_messages"]
            })

        # Find top N peaks with Non-Maximum Suppression (avoid overlapping clips)
        sorted_bins = sorted(bins, key=lambda x: x["hype_score"], reverse=True)
        highlights = []
        selected_times = []
        used_global_samples = set()

        for b in sorted_bins:
            if b["message_count"] == 0 or b["hype_score"] == 0:
                continue
                
            t = b["time"]
            # Check if this peak is too close to an already selected highlight
            is_too_close = any(abs(t - st) < min_distance_sec for st in selected_times)
            
            if not is_too_close:
                selected_times.append(t)
                start_time = max(0.0, t - before_peak_sec)
                end_time = min(max_time, t + after_peak_sec)
                
                # Pick unique top messages for this card that haven't been shown on other cards if possible
                unique_top = [m for m in b["sample_messages"] if m not in used_global_samples]
                if len(unique_top) < 3:
                    unique_top = b["sample_messages"][:5]
                else:
                    unique_top = unique_top[:5]
                for m in unique_top:
                    used_global_samples.add(m)
                
                h_dict = {
                    "id": len(highlights) + 1,
                    "peak_time": t,
                    "peak_time_formatted": self._format_time(t),
                    "start_time": round(start_time, 1),
                    "start_time_formatted": self._format_time(start_time),
                    "end_time": round(end_time, 1),
                    "end_time_formatted": self._format_time(end_time),
                    "duration": round(end_time - start_time, 1),
                    "score": round(b["hype_score"], 1),
                    "message_count": b["message_count"],
                    "title": f"Hype Peak #{len(highlights) + 1} at {self._format_time(t)}",
                    "top_messages": unique_top
                }

                # Integrate AI Speech-to-Text Transcript Analysis
                if enable_ai_speech:
                    try:
                        from services.transcript_analyzer import TranscriptAnalyzer
                        ta = TranscriptAnalyzer()
                        speech_res = ta.analyze_window(url, start_time, end_time)
                        
                        # Blend chat hype score with AI speech sentiment score
                        blended_score = round(b["hype_score"] * (0.7 + 0.6 * speech_res.get("sentiment_score", 0.5)), 1)
                        h_dict["score"] = blended_score
                        h_dict["ai_transcript"] = speech_res.get("transcript", "")
                        h_dict["ai_sentiment_score"] = speech_res.get("sentiment_score", 0.5)
                        h_dict["ai_badge"] = speech_res.get("narrative_badge", "💬 Chat Activity Peak")
                        
                        chat_str = " ".join(b["sample_messages"][:3])
                        h_dict["viral_hook"] = ta.generate_viral_hook(speech_res.get("transcript", ""), speech_res.get("narrative_badge", ""), chat_str)
                        
                        # Use speech-boundary refined timestamps
                        ref_start = speech_res.get("refined_start", start_time)
                        ref_end = speech_res.get("refined_end", end_time)
                        h_dict["start_time"] = ref_start
                        h_dict["start_time_formatted"] = self._format_time(ref_start)
                        h_dict["end_time"] = ref_end
                        h_dict["end_time_formatted"] = self._format_time(ref_end)
                        h_dict["duration"] = round(ref_end - ref_start, 1)
                    except Exception as e:
                        h_dict["ai_transcript"] = "AI Speech analysis unavailable for this window."
                        h_dict["ai_badge"] = "💬 Chat Activity Peak"
                        h_dict["viral_hook"] = "Must-Watch Streamer Moment! 🔥"
                else:
                    h_dict["ai_transcript"] = "AI Speech analysis disabled."
                    h_dict["ai_badge"] = "💬 Chat Activity Peak"
                    h_dict["viral_hook"] = "Must-Watch Streamer Moment! 🔥"

                highlights.append(h_dict)
                if len(highlights) >= top_n:
                    break

        # Sort highlights chronologically
        highlights.sort(key=lambda x: x["start_time"])
        for idx, h in enumerate(highlights):
            h["id"] = idx + 1
            h["title"] = f"Hype Peak #{idx + 1} at {h['peak_time_formatted']}"

        return {
            "timeline": timeline,
            "highlights": highlights,
            "total_messages": len(messages),
            "duration_seconds": round(max_time, 1),
            "duration_formatted": self._format_time(max_time)
        }

    @staticmethod
    def _format_time(seconds: float) -> str:
        sec = int(seconds)
        hrs = sec // 3600
        mins = (sec % 3600) // 60
        secs = sec % 60
        if hrs > 0:
            return f"{hrs:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"
