import os
import json
import logging
import subprocess
import requests
import re
import hashlib
import tempfile
import time
from typing import Optional, List, Dict
from urllib.parse import urlparse

from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from supabase import create_client, Client
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
app = FastAPI()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

openai_client = OpenAI()

PEXELS_API_KEY = "ZmtOO3adEOKSykB5pKq4DeErmcXqGccgToz145ozQ2fhu7QQiwXXcoOf"
PIXABAY_API_KEY = "55632949-a171fe55171f9250e7ee637b6"

# Fish Audio Credentials
FISH_API_KEY = "009c7d78b9ba4687a13ed389879525a6"
FISH_REF_ID = "e9d530604e61435b95d27618cf86aa29"

class DuckingRequest(BaseModel):
    vo_url: Optional[str] = None
    bgm_url: str
    video_id: str
    act_type: Optional[str] = None
    visual_queries: Optional[str] = None
    visualqueries: Optional[str] = None


@app.post("/process-audio")
async def process_audio(req: DuckingRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(run_pipeline, req)
    return {"status": "processing", "video_id": req.video_id}


def clean_text(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text).lower().strip()


def normalize_query(query: str) -> str:
    banned_words = {
        "cinematic", "moody", "dramatic", "4k", "slow", "motion", "close",
        "up", "macro", "abstract", "shot", "shots", "scene", "scenes"
    }
    words = [w.strip().lower() for w in re.split(r"\s+", query) if w.strip()]
    words = [w for w in words if w not in banned_words]
    return " ".join(words) if words else "business"


def semantic_bucket(query: str) -> str:
    q = normalize_query(query)
    rules = [
        ("phone", ["phone", "smartphone", "mobile", "iphone", "screen", "app"]),
        ("money", ["money", "cash", "dollar", "banknote", "coins", "counting", "payment"]),
        ("office", ["office", "laptop", "desk", "computer", "meeting", "coworking"]),
        ("market", ["market", "chart", "stocks", "trading", "finance", "economy", "graph", "statistics", "data"]),
        ("night", ["night", "dark", "bed", "sleep", "room", "blue light"]),
        ("people", ["person", "people", "man", "woman", "team", "crowd"]),
    ]
    for bucket, kws in rules:
        if any(k in q for k in kws):
            return bucket
    return q[:40] if q else "generic"


def make_url_signature(url: str) -> str:
    parsed = urlparse(url)
    base = f"{parsed.netloc}{parsed.path}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def get_search_queries(scene: Dict, idx: int) -> List[str]:
    queries = []
    for key in ["primary", "secondary", "tertiary"]:
        raw_q = scene.get(key, "")
        if raw_q:
            clean_q = normalize_query(raw_q)
            if clean_q and clean_q not in queries:
                queries.append(clean_q)

    fallbacks = [
        "person working dark room",
        "smartphone screen close up",
        "money payment banking",
        "office desk laptop",
        "stressed person night",
        "business analytics chart"
    ]
    backup = fallbacks[idx % len(fallbacks)]
    
    if backup not in queries:
        queries.append(backup)
        
    return queries[:4]


def contains_negative_keywords(candidate: Dict, scene: Dict) -> bool:
    negatives_str = scene.get("negative", "")
    if not negatives_str:
        return False
        
    neg_words = [w.strip().lower() for w in negatives_str.split(",") if w.strip()]
    if not neg_words:
        return False

    text_to_check = " ".join([
        candidate.get("query", ""),
        candidate.get("provider_id", ""),
        candidate.get("bucket", ""),
        candidate.get("url", "")
    ]).lower()
    
    return any(w in text_to_check for w in neg_words)


def fetch_pexels_candidates(scene: Dict, idx: int) -> List[Dict]:
    candidates = []
    headers = {"Authorization": PEXELS_API_KEY}

    for q_attempt in get_search_queries(scene, idx):
        try:
            params = {"query": q_attempt, "per_page": 15, "orientation": "landscape"}
            res = requests.get(
                "https://api.pexels.com/videos/search",
                params=params,
                headers=headers,
                timeout=20
            )
            res.raise_for_status()
            data = res.json()

            for video in data.get("videos", []):
                files = video.get("video_files", [])

                url = next((f.get("link") for f in files if f.get("width") == 1920 and f.get("height") == 1080), None)
                if not url:
                    url = next((f.get("link") for f in files if f.get("width") == 1280 and f.get("height") == 720), None)
                if not url:
                    url = next((f.get("link") for f in files if f.get("link")), None)

                if url:
                    candidates.append({
                        "provider": "pexels",
                        "url": url,
                        "provider_id": str(video.get("id", "")),
                        "query": q_attempt,
                        "bucket": semantic_bucket(q_attempt),
                        "duration": video.get("duration", 0)
                    })

            if candidates:
                break

        except Exception as e:
            logging.error(f"Pexels error for '{q_attempt}': {str(e)}")

    return candidates


def fetch_pixabay_candidates(scene: Dict, idx: int) -> List[Dict]:
    candidates = []

    for q_attempt in get_search_queries(scene, idx):
        try:
            params = {
                "key": PIXABAY_API_KEY,
                "q": q_attempt,
                "video_type": "film",
                "orientation": "horizontal",
                "per_page": 15,
                "safesearch": "true"
            }
            res = requests.get("https://pixabay.com/api/videos/", params=params, timeout=20)
            res.raise_for_status()
            data = res.json()

            for hit in data.get("hits", []):
                videos = hit.get("videos", {})
                url = None

                for quality in ["large", "medium", "small", "tiny"]:
                    candidate = videos.get(quality, {}).get("url")
                    if candidate:
                        url = candidate
                        break

                if url:
                    candidates.append({
                        "provider": "pixabay",
                        "url": url,
                        "provider_id": str(hit.get("id", "")),
                        "query": q_attempt,
                        "bucket": semantic_bucket(q_attempt),
                        "duration": hit.get("duration", 0)
                    })

            if candidates:
                break

        except Exception as e:
            logging.error(f"Pixabay error for '{q_attempt}': {str(e)}")

    return candidates


def choose_best_candidate(
    scene: Dict,
    idx: int,
    used_url_signatures: set,
    used_provider_ids: set,
    used_buckets: Dict[str, int],
    target_duration: float
) -> Optional[Dict]:
    
    preferred_provider = "pexels" if idx % 2 == 0 else "pixabay"
    secondary_provider = "pixabay" if preferred_provider == "pexels" else "pexels"

    fetch_map = {"pexels": fetch_pexels_candidates, "pixabay": fetch_pixabay_candidates}

    pool = fetch_map[preferred_provider](scene, idx)
    if not pool:
        logging.info(f"Brak wyników z {preferred_provider}, odpalam fallback na {secondary_provider}.")
        pool = fetch_map[secondary_provider](scene, idx)

    if not pool:
        return None

    seen_local = set()
    unique_pool = []

    for item in pool:
        sig = make_url_signature(item["url"])
        local_key = (item["provider"], item.get("provider_id"), sig)
        if local_key not in seen_local:
            seen_local.add(local_key)
            item["url_signature"] = sig
            unique_pool.append(item)

    clean_pool = [item for item in unique_pool if not contains_negative_keywords(item, scene)]

    strong_filtered = [
        item for item in clean_pool 
        if item["url_signature"] not in used_url_signatures 
        and f"{item['provider']}:{item.get('provider_id', '')}" not in used_provider_ids
    ]

    if not strong_filtered:
        strong_filtered = [x for x in clean_pool if x["url_signature"] not in used_url_signatures]
    if not strong_filtered:
        strong_filtered = clean_pool

    strong_filtered.sort(
        key=lambda x: (
            0 if x.get("duration", 0) >= target_duration else 1, 
            used_buckets.get(x["bucket"], 0)
        )
    )

    if strong_filtered:
        chosen = strong_filtered[0]
        used_url_signatures.add(chosen["url_signature"])
        used_provider_ids.add(f"{chosen['provider']}:{chosen.get('provider_id', '')}")
        used_buckets[chosen["bucket"]] = used_buckets.get(chosen["bucket"], 0) + 1
        return chosen

    return None


def download_file(url: str, path: str):
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 512):
                if chunk:
                    f.write(chunk)


def probe_duration_seconds(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def make_motion_video(src_url: str, scene_duration_sec: float, idx: int, v_id: str) -> str:
    temp_dir = tempfile.gettempdir()
    raw_path = os.path.join(temp_dir, f"scene_raw_{v_id}_{idx}.mp4")
    out_path = os.path.join(temp_dir, f"scene_fx_{v_id}_{idx}.mp4")

    download_file(src_url, raw_path)
    input_duration = max(0.1, probe_duration_seconds(raw_path))
    target = max(0.5, scene_duration_sec)

    if input_duration >= target:
        video_start = max(0.0, min((input_duration - target) / 2, input_duration - target))
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(video_start),
            "-i", raw_path,
            "-t", str(target),
            "-an", 
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            out_path
        ]
    else:
        loops = int(target // input_duration) + 2
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", str(loops),
            "-i", raw_path,
            "-t", str(target),
            "-an",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            out_path
        ]

    subprocess.run(cmd, check=True)
    return out_path


def robust_supabase_upload(local_file_path: str, storage_filename: str, content_type: str) -> str:
    upload_url = f"{SUPABASE_URL}/storage/v1/object/audio-outputs/{storage_filename}"
    public_url = f"{SUPABASE_URL}/storage/v1/object/public/audio-outputs/{storage_filename}"
    
    headers = {
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "apikey": SUPABASE_KEY,
        "Content-Type": content_type,
        "x-upsert": "true"
    }
    
    max_retries = 5
    for attempt in range(max_retries):
        try:
            with open(local_file_path, "rb") as f:
                res = requests.post(upload_url, headers=headers, data=f, timeout=120)
                res.raise_for_status()
            return public_url
        except Exception as e:
            logging.warning(f"Błąd przesyłania do Supabase [{storage_filename}] (Próba {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(4)
            else:
                logging.error(f"Nie udało się przesłać pliku {storage_filename}.")
                raise e
    return public_url


def upload_motion_clip(local_path: str, v_id: str, idx: int) -> str:
    storage_name = f"scene_fx_{v_id}_{idx}.mp4"
    return robust_supabase_upload(local_path, storage_name, "video/mp4")


def generate_fish_audio(scenes: List[Dict], v_id: str, generated_temp_files: List[str]) -> str:
    chunks = []
    current_chunk = ""
    
    for scene in scenes:
        text = scene.get("text", "")
        if len(current_chunk) + len(text) > 2500:
            chunks.append(current_chunk.strip())
            current_chunk = text + " "
        else:
            current_chunk += text + " "
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
        
    chunk_files = []
    
    if not chunks:
        raise ValueError("BŁĄD KRYTYCZNY: Brak tekstu do wygenerowania. Sprawdź mapowanie w Text Aggregator.")
        
    for i, text_chunk in enumerate(chunks):
        if not text_chunk.strip(): continue
        
        logging.info(f"Generowanie głosu Fish Audio: Pakiet {i+1}/{len(chunks)}")
        
        payload = {
            "text": text_chunk,
            "format": "mp3",
            "mp3_bitrate": 192,
            "reference_id": FISH_REF_ID,
            "temperature": 0.55,
            "top_p": 0.7,
            "condition_on_previous_chunks": True,
            "prosody": {"speed": 1, "volume": 0, "normalize_loudness": True}
        }
        headers = {
            "Authorization": f"Bearer {FISH_API_KEY}",
            "Content-Type": "application/json",
            "model": "s2-pro"
        }
        
        res = requests.post("https://api.fish.audio/v1/tts", json=payload, headers=headers, timeout=120)
        res.raise_for_status()
        
        chunk_path = os.path.join(tempfile.gettempdir(), f"vo_chunk_{v_id}_{i}.mp3")
        with open(chunk_path, "wb") as f:
            f.write(res.content)
            
        chunk_files.append(chunk_path)
        generated_temp_files.append(chunk_path)
        
    concat_file = os.path.join(tempfile.gettempdir(), f"concat_{v_id}.txt")
    generated_temp_files.append(concat_file)
    
    if not chunk_files:
        raise ValueError("BŁĄD: Nie wygenerowano żadnego pliku audio przez Fish Audio.")
    
    with open(concat_file, "w") as f:
        for cf in chunk_files:
            f.write(f"file '{cf}'\n")
            
    master_vo_path = os.path.join(tempfile.gettempdir(), f"vo_raw_{v_id}.mp3")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", master_vo_path], check=True)
    
    return master_vo_path


def run_pipeline(req: DuckingRequest):
    v_id = req.video_id
    generated_temp_files = []

    bgm_ext = ".mp3" if ".mp3" in req.bgm_url.lower() else ".wav" if ".wav" in req.bgm_url.lower() else ".mp3"
    bgm_raw = os.path.join(tempfile.gettempdir(), f"bgm_raw_{v_id}{bgm_ext}")
    vo_mp3_cloud = os.path.join(tempfile.gettempdir(), f"vo_cloud_{v_id}.mp3")
    out_p = os.path.join(tempfile.gettempdir(), f"master_{v_id}.mp3")
    json_p = os.path.join(tempfile.gettempdir(), f"timestamps_{v_id}.json")
    
    generated_temp_files.extend([bgm_raw, vo_mp3_cloud, out_p, json_p])
    RENDERLY_API_KEY = os.getenv("RENDERLY_API_KEY")

    try:
        scenario_data = req.visualqueries or req.visual_queries or req.act_type
        scenes = []

        if scenario_data:
            parts = scenario_data.split(";;")
            for p in parts:
                p = p.strip()
                if not p:
                    continue
                elements = [e.strip() for e in p.split("|")]
                scene_dict = {
                    "text": elements[0] if len(elements) > 0 else "",
                    "primary": elements[1] if len(elements) > 1 and elements[1] else "business",
                    "secondary": elements[2] if len(elements) > 2 and elements[2] else "",
                    "tertiary": elements[3] if len(elements) > 3 and elements[3] else "",
                    "negative": elements[4] if len(elements) > 4 and elements[4] else "",
                    "screen_text": elements[5] if len(elements) > 5 and elements[5] else ""
                }
                scene_dict["tag"] = scene_dict["primary"]
                scenes.append(scene_dict)
        else:
            scenes.append({"text": "", "primary": "business", "secondary": "", "tertiary": "", "negative": "", "screen_text": "", "tag": "business"})

        num_queries = len(scenes)

        if req.vo_url and req.vo_url.startswith("http"):
            vo_raw = os.path.join(tempfile.gettempdir(), f"vo_raw_{v_id}.mp3")
            download_file(req.vo_url, vo_raw)
            generated_temp_files.append(vo_raw)
        else:
            vo_raw = generate_fish_audio(scenes, v_id, generated_temp_files)

        download_file(req.bgm_url, bgm_raw)

        subprocess.run(
            ["ffmpeg", "-y", "-i", vo_raw, "-codec:a", "libmp3lame", "-b:a", "128k", vo_mp3_cloud],
            check=True
        )

        # TRANSCRIBE WITH WHISPER (Added "segment" for SRT)
        transcription = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=open(vo_mp3_cloud, "rb"),
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"] # <--- DODANO "segment"
        )

        # GENERATING SRT SUBTITLES
        srt_path = os.path.join(tempfile.gettempdir(), f"subtitles_{v_id}.srt")
        generated_temp_files.append(srt_path)
        
        def format_srt_time(seconds):
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            millis = int((seconds - int(seconds)) * 1000)
            return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

        with open(srt_path, "w", encoding="utf-8") as srt_file:
            if hasattr(transcription, "segments") and transcription.segments:
                for i, segment in enumerate(transcription.segments):
                    start_val = segment.get("start", 0) if isinstance(segment, dict) else getattr(segment, "start", 0)
                    end_val = segment.get("end", 0) if isinstance(segment, dict) else getattr(segment, "end", 0)
                    text_val = segment.get("text", "") if isinstance(segment, dict) else getattr(segment, "text", "")
                    
                    start_time = format_srt_time(start_val)
                    end_time = format_srt_time(end_val)
                    
                    srt_file.write(f"{i+1}\n")
                    srt_file.write(f"{start_time} --> {end_time}\n")
                    srt_file.write(f"{text_val.strip()}\n\n")
                    
        srt_url = robust_supabase_upload(srt_path, f"subtitles_{v_id}.srt", "application/x-subrip")
        logging.info(f"Gotowe napisy SRT na Supabase: {srt_url}")

        fps = 30
        total_duration_sec = getattr(transcription, "duration", 47.0)
        total_frames = int(round(total_duration_sec * fps))
        video_id_counter = 5000
        video_overlays = []

        whisper_words_clean = []
        if hasattr(transcription, "words") and transcription.words:
            for w in transcription.words:
                word_text = w.get("word", "") if isinstance(w, dict) else getattr(w, "word", "")
                start_time = w.get("start", 0.0) if isinstance(w, dict) else getattr(w, "start", 0.0)
                end_time = w.get("end", 0.0) if isinstance(w, dict) else getattr(w, "end", 0.0)
                
                clean_w = re.sub(r"[^\w]", "", word_text.lower())
                if clean_w:
                    whisper_words_clean.append({
                        "word": clean_w, 
                        "start": start_time, 
                        "end": end_time
                    })

        prev_end_frame = 0
        current_whisper_idx = 0
        
        used_url_signatures = set()
        used_provider_ids = set()
        used_buckets = {}

        for idx, scene in enumerate(scenes):
            scene_text = scene["text"]
            clean_scene_text = re.sub(r"\(.*?\)|\[.*?\]", "", scene_text)
            scene_words = [re.sub(r"[^\w]", "", w.lower()) for w in clean_scene_text.split() if re.sub(r"[^\w]", "", w.lower())]
            
            next_scene_words = []
            if idx + 1 < num_queries:
                nxt_text = scenes[idx+1]["text"]
                nxt_cln = re.sub(r"\(.*?\)|\[.*?\]", "", nxt_text)
                next_scene_words = [re.sub(r"[^\w]", "", w.lower()) for w in nxt_cln.split() if re.sub(r"[^\w]", "", w.lower())]
            
            end_sec = None
            
            if (scene_words or next_scene_words) and current_whisper_idx < len(whisper_words_clean):
                anchor_len = min(3, len(scene_words)) if scene_words else 0
                anchors = scene_words[-anchor_len:] if anchor_len > 0 else []
                
                next_anchor_len = min(3, len(next_scene_words)) if next_scene_words else 0
                next_anchors = next_scene_words[:next_anchor_len] if next_anchor_len > 0 else []

                search_limit = min(len(whisper_words_clean), current_whisper_idx + len(scene_words) + 25)
                
                best_match_time = None
                first_fuzzy_match_time = None
                first_fuzzy_match_idx = None
                
                for i in range(current_whisper_idx, search_limit):
                    if anchor_len > 0 and i + anchor_len <= len(whisper_words_clean):
                        match_count = sum(1 for j in range(anchor_len) if whisper_words_clean[i+j]["word"] == anchors[j])
                        if match_count == anchor_len:
                            best_match_time = whisper_words_clean[i + anchor_len - 1]["end"]
                            current_whisper_idx = i + anchor_len
                            break
                        elif anchor_len >= 3 and match_count >= 2:
                            if first_fuzzy_match_time is None:
                                first_fuzzy_match_time = whisper_words_clean[i + anchor_len - 1]["end"]
                                first_fuzzy_match_idx = i + anchor_len
                    
                    if next_anchor_len > 0 and i + next_anchor_len <= len(whisper_words_clean):
                        next_match_count = sum(1 for j in range(next_anchor_len) if whisper_words_clean[i+j]["word"] == next_anchors[j])
                        if next_match_count == next_anchor_len:
                            if i > 0:
                                best_match_time = whisper_words_clean[i - 1]["end"]
                            else:
                                best_match_time = whisper_words_clean[0]["start"]
                            current_whisper_idx = i
                            break
                
                if best_match_time is not None:
                    end_sec = best_match_time
                elif first_fuzzy_match_time is not None:
                    end_sec = first_fuzzy_match_time
                    current_whisper_idx = first_fuzzy_match_idx
            
            if end_sec is None:
                remaining_time = total_duration_sec - (prev_end_frame / fps)
                remaining_scenes = num_queries - idx
                end_sec = (prev_end_frame / fps) + (remaining_time / remaining_scenes)

            start_frame = prev_end_frame
            end_frame = int(round(end_sec * fps))

            if idx == num_queries - 1:
                end_frame = max(end_frame, total_frames)

            if end_frame - start_frame < 15:
                end_frame = start_frame + 15

            duration_frames = end_frame - start_frame
            prev_end_frame = end_frame
            scene_duration_sec = max(0.5, duration_frames / fps)

            # VIDEO LAYER
            candidate = choose_best_candidate(
                scene,
                idx,
                used_url_signatures,
                used_provider_ids,
                used_buckets,
                target_duration=scene_duration_sec
            )

            if candidate:
                source_url = candidate["url"]
                source_name = f"{candidate['provider']}:{candidate.get('provider_id', '')}"
            else:
                fallbacks = [
                    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4",
                    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4",
                    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerFun.mp4",
                    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerJoyrides.mp4"
                ]
                source_url = fallbacks[idx % len(fallbacks)]
                source_name = "fallback"

            processed_local = make_motion_video(source_url, scene_duration_sec, idx, v_id)
            generated_temp_files.append(processed_local)
            processed_url = upload_motion_clip(processed_local, v_id, idx)

            video_overlays.append({
                "id": video_id_counter,
                "type": "video",
                "src": processed_url,
                "from": start_frame,
                "durationInFrames": duration_frames,
                "row": 1,
                "top": 0,
                "left": 0,
                "width": 1920,
                "height": 1080,
                "styles": {
                    "objectFit": "cover",
                    "opacity": 1,
                    "zIndex": 1
                }
            })
            video_id_counter += 1

            # TEXT LAYER (Cinematic overlay)
            screen_txt = scene.get("screen_text", "").strip()
            if screen_txt:
                logging.info(f"Dodaję nakładkę tekstową: '{screen_txt}' dla sceny {idx + 1}")
                video_overlays.append({
                    "id": video_id_counter,
                    "type": "text",
                    "content": screen_txt,
                    "from": start_frame,
                    "durationInFrames": duration_frames,
                    "row": 0,
                    "top": 440,
                    "left": 0,
                    "width": 1920,
                    "height": 200,
                    "rotation": 0,
                    "styles": {
                        "fontSize": "6rem",
                        "fontWeight": "900",
                        "color": "#FFFFFF",
                        "fontFamily": "font-sans",
                        "textAlign": "center",
                        "backgroundColor": "rgba(0,0,0,0.65)",
                        "zIndex": 9999
                    }
                })
                video_id_counter += 1

        out_p_name = f"master_{v_id}.mp3"
        json_p_name = f"timestamps_{v_id}.json"
        
        filter_str = (
            "[0:a]asplit=2[vo_ctrl][vo_clean]; "
            "[1:a]volume=0.12[bg_pre]; "
            "[bg_pre][vo_ctrl]sidechaincompress=threshold=0.08:ratio=4:attack=100:release=800[bg_ducked]; "
            "[vo_clean][bg_ducked]amix=inputs=2:duration=first:dropout_transition=2[mixed]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", vo_raw,
            "-i", bgm_raw,
            "-filter_complex", filter_str,
            "-map", "[mixed]",
            "-codec:a", "libmp3lame",
            "-b:a", "192k",
            "-vn",
            out_p
        ]
        subprocess.run(cmd, check=True)

        master_audio_url = robust_supabase_upload(out_p, out_p_name, "audio/mpeg")
        
        with open(json_p, "w", encoding="utf-8") as f:
            json.dump(video_overlays, f, ensure_ascii=False, indent=2)
        robust_supabase_upload(json_p, json_p_name, "application/json")

        sound_layer = {
            "id": 8999,
            "type": "sound",
            "src": master_audio_url,
            "from": 0,
            "durationInFrames": total_frames,
            "row": 2,
            "top": 0,
            "left": 0,
            "width": 1920,
            "height": 1080,
            "styles": {}
        }

        renderly_payload = {
            "inputProps": {
                "width": 1920,
                "height": 1080,
                "fps": fps,
                "durationInFrames": total_frames,
                "backgroundColor": "#000000",
                "src": master_audio_url,
                "overlays": [sound_layer] + video_overlays
            }
        }

        render_res = requests.post(
            "https://renderly.video/api/v1/renders",
            json=renderly_payload,
            headers={
                "Authorization": f"Bearer {RENDERLY_API_KEY}",
                "Content-Type": "application/json"
            },
            timeout=45
        )

        if render_res.status_code in [200, 201]:
            logging.info(f"SUKCES Renderly: {render_res.text}")
        else:
            logging.error(f"Błąd Renderly: {render_res.status_code} | {render_res.text}")

    except Exception as e:
        logging.error(f"BŁĄD PIPELINE: {str(e)}", exc_info=True)

    finally:
        for p in generated_temp_files:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass