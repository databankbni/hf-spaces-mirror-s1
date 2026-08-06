"""Core transcription pipeline for the web app.

Flow:
    URL      -> try YouTube subtitles; if none, download audio -> Whisper
    MP4/MOV… -> extract audio (ffmpeg) -> Whisper
    segments -> chunk -> Claude formats into paragraphs + chapters -> TXT

Speech-to-text uses Groq's Whisper API (OpenAI-compatible). Formatting uses
the Anthropic Claude API. Both keys come from environment variables so they can
live in Hugging Face "Secrets" rather than the code.
"""

from __future__ import annotations

import json
import math
import os
import re
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import certifi
import requests
from youtube_transcript_api import YouTubeTranscriptApi

SSL_CTX = ssl.create_default_context(cafile=certifi.where())

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "whisper-large-v3")
# Summary / key points run on Groq's free open LLM (no per-request cost).
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
SUMMARY_MODEL = os.environ.get("SUMMARY_MODEL", "llama-3.3-70b-versatile")
# Free formatting model (used when Claude is turned off). A small, fast model is
# plenty for paragraph-break detection and far less likely to time out (524) than
# the heavy 70b model under Groq's free-tier load.
FORMAT_GROQ_MODEL = os.environ.get("FORMAT_GROQ_MODEL", "llama-3.1-8b-instant")
FORMAT_MODEL = os.environ.get("FORMAT_MODEL", "claude-haiku-4-5")
# rewrite = Claude re-emits full text (best for raw/unpunctuated captions).
# breaks  = Claude returns only paragraph-break line numbers, ~10x cheaper output
#           (best when captions already have punctuation). auto = pick per video.
FORMAT_MODE = os.environ.get("FORMAT_MODE", "auto")

# Self-hosted speech-to-text (used when no GROQ_API_KEY is set — free, no signup).
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")   # tiny|base|small|medium
WHISPER_COMPUTE = os.environ.get("WHISPER_COMPUTE", "int8")

# Proxy for YouTube requests (datacenter IPs are blocked by YouTube).
# Either set WEBSHARE_PROXY_USERNAME + WEBSHARE_PROXY_PASSWORD (recommended),
# or a generic PROXY_URL like http://user:pass@host:port.
WEBSHARE_USER = os.environ.get("WEBSHARE_PROXY_USERNAME")
WEBSHARE_PASS = os.environ.get("WEBSHARE_PROXY_PASSWORD")
PROXY_URL_ENV = os.environ.get("PROXY_URL")
# socks5h routes traffic over SOCKS5 (port 1080) — this evades hosts that filter
# YouTube on the plaintext HTTP CONNECT (port 80). Set PROXY_SCHEME=http to force HTTP.
PROXY_SCHEME = os.environ.get("PROXY_SCHEME", "socks5h")

# Supadata fetches YouTube captions from its own infrastructure (works even when
# the host's direct YouTube access is blocked). native=existing only,
# generate=AI only, auto=native then AI fallback.
SUPADATA_URL = "https://api.supadata.ai/v1/transcript"
SUPADATA_MODE = os.environ.get("SUPADATA_MODE", "auto")

# Gemini (free tier) — the main free engine: ~10 RPM each but a big daily
# request budget and a 1M context, so one video fits in ONE request.
# Two models = two separate quota pools; the second catches 429 collisions.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
GEMINI_MODEL_2 = os.environ.get("GEMINI_MODEL_2", "gemini-2.5-flash")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Transcript translation (free Groq). The heavy model translates better; on
# timeout each chunk individually falls back to the fast small model.
TRANSLATE_MODEL = os.environ.get("TRANSLATE_MODEL", "llama-3.3-70b-versatile")
TRANSLATE_FALLBACK_MODEL = os.environ.get("TRANSLATE_FALLBACK_MODEL", "llama-3.1-8b-instant")
LANG_NAMES = {"ru": "Russian", "en": "English", "uk": "Ukrainian",
              "de": "German", "fr": "French", "es": "Spanish"}

# In-memory caches: re-requesting the same video must not re-spend Supadata
# credits (free plan ~100/mo) or LLM calls. Reset on Space restart — acceptable.
_CACHE_LOCK = threading.Lock()
_SEG_LOCKS: dict[str, threading.Lock] = {}     # per-video: no concurrent double Supadata spend
_SEG_CACHE: dict[tuple, tuple] = {}            # (video_id, lang) -> (segments, title)
_SEG_CACHE_CAP = 60
_RESULT_CACHE: OrderedDict = OrderedDict()     # full-result LRU -> (filename, txt)
_RESULT_CACHE_CAP = 40


def _cache_put(cache: dict, key, value, cap: int) -> None:
    cache[key] = value
    while len(cache) > cap:
        cache.pop(next(iter(cache)), None)


def _proxy_url() -> str | None:
    """A plain proxy URL for yt-dlp / requests, or None.

    Webshare's rotating endpoint needs the username to end with '-rotate'. The
    dashboard already shows it that way, so strip any existing suffix before
    re-adding it — otherwise it doubles to '-rotate-rotate' and the proxy 400s.
    """
    if PROXY_URL_ENV:
        return PROXY_URL_ENV
    if WEBSHARE_USER and WEBSHARE_PASS:
        user = WEBSHARE_USER.removesuffix("-rotate")
        if PROXY_SCHEME.startswith("socks"):
            return f"socks5h://{user}-rotate:{WEBSHARE_PASS}@p.webshare.io:1080"
        return f"http://{user}-rotate:{WEBSHARE_PASS}@p.webshare.io:80"
    return None


def _requests_proxies() -> dict | None:
    url = _proxy_url()
    return {"http": url, "https": url} if url else None


def _subtitle_proxy_config():
    """Proxy config object for youtube-transcript-api, or None."""
    url = _proxy_url()
    if not url:
        return None
    try:
        from youtube_transcript_api.proxies import GenericProxyConfig
        return GenericProxyConfig(http_url=url, https_url=url)
    except Exception as e:
        log(f"proxy config unavailable: {e}")
        return None

TARGET_CHUNK_WORDS = 900
LINE_MAX_WORDS = 45
LINE_BREAK_PAUSE = 1.8          # seconds of silence that force a new line
AUDIO_SEGMENT_SECONDS = 480     # split long audio into ~8-min pieces for Whisper (reliable per-request)
SUBTITLE_LANGS = [l.strip() for l in os.environ.get("SUBTITLE_LANGS", "ru,en").split(",") if l.strip()]


# --------------------------------------------------------------------------- #
# Utilities
# --------------------------------------------------------------------------- #
class TranscribeError(Exception):
    """User-facing error (message is shown in the UI)."""


def log(msg: str) -> None:
    print(f"[transcriber] {msg}", flush=True)


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def safe_filename(name: str, limit: int = 120) -> str:
    name = re.sub(r'[\\/:*?"<>|\n\r\t]', " ", name).strip()
    name = re.sub(r"\s+", " ", name)
    return (name[:limit].rstrip(" .")) or "transcript"


def parse_video_id(arg: str) -> str | None:
    arg = arg.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", arg):
        return arg
    try:
        url = urllib.parse.urlparse(arg)
    except ValueError:
        return None
    if url.netloc.endswith("youtu.be"):
        return url.path.lstrip("/").split("/")[0] or None
    if "youtube" in url.netloc:
        qs = urllib.parse.parse_qs(url.query)
        if "v" in qs:
            return qs["v"][0]
        m = re.match(r"/(?:shorts|embed|live)/([A-Za-z0-9_-]{11})", url.path)
        if m:
            return m.group(1)
    return None


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #
def fetch_meta(video_id: str) -> dict:
    watch_url = f"https://www.youtube.com/watch?v={video_id}"
    oembed = (
        "https://www.youtube.com/oembed?url="
        + urllib.parse.quote(watch_url, safe="")
        + "&format=json"
    )
    try:
        r = requests.get(oembed, timeout=15, proxies=_requests_proxies())
        r.raise_for_status()
        data = r.json()
        return {"url": watch_url, "title": data.get("title", video_id),
                "channel": data.get("author_name", "")}
    except Exception as e:
        log(f"oembed failed: {e}")
        return {"url": watch_url, "title": video_id, "channel": ""}


# --------------------------------------------------------------------------- #
# YouTube subtitles
# --------------------------------------------------------------------------- #
def get_youtube_subtitles(video_id: str) -> list[dict] | None:
    """Return caption segments if the video has usable subtitles, else None."""
    try:
        proxy_config = _subtitle_proxy_config()
        api = YouTubeTranscriptApi(proxy_config=proxy_config) if proxy_config else YouTubeTranscriptApi()
        listing = api.list(video_id)
    except Exception as e:
        log(f"no subtitle listing: {e}")
        return None

    manual = [t for t in listing if not t.is_generated]
    auto = [t for t in listing if t.is_generated]
    chosen = None
    for pool in (manual, auto):
        for lang in SUBTITLE_LANGS:
            for t in pool:
                if t.language_code == lang or t.language_code.startswith(lang + "-"):
                    chosen = t
                    break
            if chosen:
                break
        if chosen:
            break
    if chosen is None:
        chosen = (manual or auto or [None])[0]
    if chosen is None:
        return None

    try:
        fetched = chosen.fetch()
    except Exception as e:
        log(f"subtitle fetch failed: {e}")
        return None
    segments = [{"start": s.start, "dur": s.duration, "text": s.text} for s in fetched]
    return segments or None


# --------------------------------------------------------------------------- #
# Supadata transcript API (third-party YouTube caption fetch)
# --------------------------------------------------------------------------- #
def _supadata_segments(payload: dict) -> list[dict]:
    content = payload.get("content")
    segs: list[dict] = []
    if isinstance(content, list):
        for c in content:
            text = (c.get("text") or "").strip()
            if not text:
                continue
            segs.append({"start": float(c.get("offset", 0)) / 1000.0,
                         "dur": float(c.get("duration", 0)) / 1000.0,
                         "text": text})
    elif isinstance(content, str) and content.strip():
        segs.append({"start": 0.0, "dur": 0.0, "text": content.strip()})
    if not segs:
        raise TranscribeError("Supadata returned an empty transcript.")
    return segs


def _poll_supadata(job_id: str, api_key: str, progress=None) -> dict:
    headers = {"x-api-key": api_key}
    for i in range(150):                       # up to ~2.5 min
        time.sleep(1)
        r = requests.get(f"{SUPADATA_URL}/{job_id}", headers=headers, timeout=30)
        if r.status_code != 200:
            raise TranscribeError(f"Supadata (polling) returned {r.status_code}: {r.text[:150]}")
        d = r.json()
        status = d.get("status")
        if status == "completed":
            return d
        if status == "failed":
            raise TranscribeError("Supadata could not fetch/generate a transcript.")
        if progress and i % 3 == 0:
            progress(0.2, "Processing the video…")
    raise TranscribeError("Supadata: request timed out.")


def fetch_title_noembed(video_id: str) -> str | None:
    """Free video title via noembed.com (their servers fetch YouTube's oEmbed,
    so it works even from hosts whose direct YouTube access is blocked)."""
    try:
        r = requests.get("https://noembed.com/embed",
                         params={"url": f"https://www.youtube.com/watch?v={video_id}"},
                         timeout=6)
        if r.status_code == 200:
            return (r.json().get("title") or "").strip() or None
    except Exception as e:
        log(f"noembed title failed: {e}")
    return None


def get_supadata_title(video_id: str, api_key: str) -> str | None:
    """Best-effort video title via Supadata metadata (costs ~1 extra credit)."""
    if os.environ.get("SUPADATA_FETCH_TITLE", "1") == "0":
        return None
    try:
        r = requests.get("https://api.supadata.ai/v1/youtube/video",
                         params={"id": video_id}, headers={"x-api-key": api_key}, timeout=30)
        if r.status_code == 200:
            return (r.json().get("title") or "").strip() or None
    except Exception as e:
        log(f"supadata title failed: {e}")
    return None


def get_supadata_channel_videos(source: str, limit: int, api_key: str) -> list[str]:
    """Newest video ids of a channel via Supadata (~1 credit per call).
    source: @handle, channel URL or channel id."""
    r = requests.get("https://api.supadata.ai/v1/youtube/channel/videos",
                     params={"id": source, "limit": limit, "type": "video"},
                     headers={"x-api-key": api_key}, timeout=60)
    if r.status_code != 200:
        raise TranscribeError(f"Supadata channel error {r.status_code}: {r.text[:150]}")
    ids = r.json().get("videoIds") or []
    return [i for i in ids if isinstance(i, str) and re.fullmatch(r"[A-Za-z0-9_-]{11}", i)][:limit]


def get_supadata_transcript(url: str, api_key: str, language: str | None,
                            progress=None) -> list[dict]:
    params = {"url": url, "mode": SUPADATA_MODE}
    if language:
        params["lang"] = language
    r = requests.get(SUPADATA_URL, params=params, headers={"x-api-key": api_key}, timeout=90)
    if r.status_code == 200:
        payload = r.json()
    elif r.status_code == 202:
        payload = _poll_supadata(r.json().get("jobId"), api_key, progress=progress)
    elif r.status_code == 206:
        raise TranscribeError("This video has no subtitles (Supadata).")
    elif r.status_code == 429:
        raise TranscribeError(
            "⚠️ Monthly YouTube-link quota is used up (resets on the 1st). "
            "Upload the audio/video FILE instead — that is free and unlimited. / "
            "Месячный лимит ссылок исчерпан — загрузи сам файл (это бесплатно) "
            "или дождись 1-го числа.")
    elif r.status_code == 401:
        raise TranscribeError("Supadata: invalid or missing API key.")
    elif r.status_code == 403:
        raise TranscribeError(
            f"This video is not available to subtitle services "
            f"(age-restricted or blocked): {r.text[:120]}")
    elif r.status_code == 404:
        raise TranscribeError("Video not found or private (Supadata).")
    else:
        raise TranscribeError(f"Supadata returned error {r.status_code}: {r.text[:200]}")
    return _supadata_segments(payload)


# --------------------------------------------------------------------------- #
# Backup caption sources (legal free tiers, used when Supadata quota runs out)
# --------------------------------------------------------------------------- #
def _fix_ms_timestamps(segs: list[dict]) -> list[dict]:
    """Heuristic: if 'seconds' exceed 24h the API actually returned milliseconds."""
    if segs and max(s["start"] for s in segs) > 86400:
        for s in segs:
            s["start"] /= 1000.0
            s["dur"] /= 1000.0
    return segs


def get_apify_transcript(video_id: str) -> list[dict] | None:
    """Apify caption actor: it fetches YouTube captions through its own residential
    proxies, so it works from our blocked datacenter IP. Free plan = $5/mo credit,
    ~$0.01/video ≈ 500 links/month, no card. Returns timestamped segments or None."""
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        return None
    actor = os.environ.get("APIFY_ACTOR", "pintostudio~youtube-transcript-scraper")
    try:
        r = requests.post(
            f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
            params={"token": token},
            json={"videoUrl": f"https://www.youtube.com/watch?v={video_id}"},
            timeout=120)
        if r.status_code not in (200, 201):
            log(f"apify error {r.status_code}: {r.text[:120]}")
            return None
        items = r.json()
        data = None
        if isinstance(items, list) and items:
            first = items[0]
            data = first.get("data") if isinstance(first, dict) else first
        segs = [{"start": float(s.get("start", 0) or 0),
                 "dur": float(s.get("dur", 0) or 0),
                 "text": str(s.get("text") or "").strip()}
                for s in (data or []) if isinstance(s, dict) and str(s.get("text") or "").strip()]
        return segs or None
    except Exception as e:  # noqa: BLE001
        log(f"apify failed: {e}")
        return None


def get_serpapi_transcript(video_id: str) -> list[dict] | None:
    """SerpApi's YouTube transcript engine — fetched through SerpApi's own infra, so it
    works from our blocked datacenter IP. Free tier 250 searches/month, no card.
    Segments carry start_ms/end_ms/snippet → timestamped. Returns segments or None."""
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        return None
    try:
        r = requests.get("https://serpapi.com/search.json",
                         params={"engine": "youtube_video_transcript",
                                 "v": video_id, "api_key": key},
                         timeout=60)
        if r.status_code != 200:
            log(f"serpapi error {r.status_code}: {r.text[:120]}")
            return None
        data = r.json()
        if data.get("error"):
            log(f"serpapi: {str(data['error'])[:120]}")
            return None
        raw = data.get("transcript", [])
        segs = []
        for i, s in enumerate(raw):
            text = str(s.get("snippet") or "").strip()
            if not text:
                continue
            start = float(s.get("start_ms", 0) or 0) / 1000.0
            # no end_ms in this engine → duration = gap to the next segment's start
            nxt = raw[i + 1].get("start_ms") if i + 1 < len(raw) else None
            end = (float(nxt) / 1000.0) if nxt is not None else (start + 4.0)
            segs.append({"start": start, "dur": max(0.5, end - start), "text": text})
        return segs or None
    except Exception as e:  # noqa: BLE001
        log(f"serpapi failed: {e}")
        return None


def get_fallback_transcript(video_id: str) -> tuple[list[dict], str] | None:
    """Try backup transcript providers. Returns (segments, source_note) or None."""
    segs = get_apify_transcript(video_id)   # 500/mo recurring, works from datacenter
    if segs:
        log("fallback source: Apify")
        return _fix_ms_timestamps(segs), "subtitles (Apify)"

    segs = get_serpapi_transcript(video_id)   # 250/mo recurring, works from datacenter
    if segs:
        log("fallback source: SerpApi")
        return segs, "subtitles (SerpApi)"

    key = os.environ.get("TRANSCRIPTAPI_KEY")
    if key:
        try:
            r = requests.get("https://transcriptapi.com/api/v2/youtube/transcript",
                             params={"video_url": video_id, "include_timestamp": "true"},
                             headers={"Authorization": f"Bearer {key}"}, timeout=60)
            if r.status_code == 200:
                segs = [{"start": float(s.get("start", 0) or 0),
                         "dur": float(s.get("duration", 0) or 0),
                         "text": str(s.get("text") or "").strip()}
                        for s in r.json().get("transcript", [])
                        if str(s.get("text") or "").strip()]
                if segs:
                    log("fallback source: TranscriptAPI")
                    return _fix_ms_timestamps(segs), "subtitles (TranscriptAPI)"
            else:
                log(f"transcriptapi error {r.status_code}: {r.text[:120]}")
        except Exception as e:
            log(f"transcriptapi failed: {e}")

    key = os.environ.get("YT_TRANSCRIPT_IO_KEY")
    if key:
        try:
            r = requests.post("https://www.youtube-transcript.io/api/transcripts",
                              headers={"Authorization": f"Basic {key}",
                                       "Content-Type": "application/json"},
                              json={"ids": [video_id]}, timeout=60)
            if r.status_code == 200:
                data = r.json()
                item = data[0] if isinstance(data, list) and data else (
                    data.get(video_id) or data if isinstance(data, dict) else None)
                tracks = None
                if isinstance(item, dict):
                    tracks = (item.get("transcript") or item.get("segments")
                              or item.get("tracks"))
                    if (isinstance(tracks, list) and tracks
                            and isinstance(tracks[0], dict) and "transcript" in tracks[0]):
                        tracks = tracks[0].get("transcript")
                segs = []
                for s in tracks or []:
                    if not isinstance(s, dict):
                        continue
                    text = str(s.get("text") or "").strip()
                    if text:
                        segs.append({"start": float(s.get("start", s.get("offset", 0)) or 0),
                                     "dur": float(s.get("duration", s.get("dur", 0)) or 0),
                                     "text": text})
                if segs:
                    log("fallback source: youtube-transcript.io")
                    return _fix_ms_timestamps(segs), "subtitles (youtube-transcript.io)"
            else:
                log(f"yt-transcript.io error {r.status_code}: {r.text[:120]}")
        except Exception as e:
            log(f"yt-transcript.io failed: {e}")
    return None


def fetch_segments_server(url: str, language: str | None = None) -> tuple[list[dict], str]:
    """Fetch captions for one video URL entirely server-side: Supadata → backup
    providers (proxied, never IP-blocked). Used as the bulk fallback when the Mac
    worker's home IP gets rate-limited by YouTube. Returns (segments, source_note);
    raises TranscribeError if the video genuinely has no subtitles anywhere."""
    video_id = parse_video_id(url) or (url if re.fullmatch(r"[A-Za-z0-9_-]{11}", url) else None)
    if not video_id:
        raise TranscribeError("Could not parse a video id from the URL.")
    watch_url = f"https://www.youtube.com/watch?v={video_id}"
    supa_key = os.environ.get("SUPADATA_API_KEY")
    if supa_key:
        try:
            segs = get_supadata_transcript(watch_url, supa_key, language)
            if segs:
                return segs, "subtitles (Supadata)"
        except TranscribeError as e:
            # even a Supadata "no subtitles" (206) falls through — a backup provider
            # may still have captions for this exact video.
            log(f"bulk server-fetch Supadata failed ({e}); trying backups")
    fb = get_fallback_transcript(video_id)
    if fb is None:
        raise TranscribeError("No subtitles available from any source.")
    return fb


def asr_segments_server(url: str, language: str | None = None) -> tuple[list[dict], str]:
    """Last resort for a video with NO captions anywhere: download the audio track
    (proxied) and transcribe it with Whisper (Groq → local). Returns (segments, note)."""
    video_id = parse_video_id(url) or (url if re.fullmatch(r"[A-Za-z0-9_-]{11}", url) else None)
    watch_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else url
    with tempfile.TemporaryDirectory() as workdir:
        audio = download_youtube_audio(watch_url, workdir)
        segments = run_asr(audio, workdir, language)
    if not segments:
        raise TranscribeError("Speech recognition produced no text.")
    return segments, "speech recognition (Whisper)"


# --------------------------------------------------------------------------- #
# Audio handling (ffmpeg + Whisper)
# --------------------------------------------------------------------------- #
def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise TranscribeError(f"ffmpeg failed: {proc.stderr.strip()[:400]}")


def extract_audio(src_path: str, workdir: str) -> str:
    """Downmix any media file to a compact mono 16 kHz Opus track."""
    out = os.path.join(workdir, "audio.ogg")
    _run(["ffmpeg", "-y", "-i", src_path, "-vn", "-ac", "1", "-ar", "16000",
          "-c:a", "libopus", "-b:a", "20k", out])
    return out


def download_youtube_audio(url: str, workdir: str) -> str:
    """Download the audio track of a YouTube video as compact Opus."""
    out = os.path.join(workdir, "audio.ogg")
    cmd = [
        "yt-dlp", "-f", "bestaudio/best", "-x", "--audio-format", "opus",
        "--postprocessor-args", "ffmpeg:-ac 1 -ar 16000 -b:a 20k",
        "-o", os.path.join(workdir, "audio.%(ext)s"),
    ]
    proxy = _proxy_url()
    if proxy:
        cmd += ["--proxy", proxy]
    cmd.append(url)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise TranscribeError(
            "Failed to download audio from YouTube (the video may be private or "
            "YouTube blocked the server request). Details: "
            + proc.stderr.strip()[-300:]
        )
    if not os.path.exists(out):
        cand = list(Path(workdir).glob("audio.*"))
        if not cand:
            raise TranscribeError("yt-dlp did not produce an audio file.")
        out = str(cand[0])
    return out


def _audio_duration(path: str) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True)
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def _split_audio(path: str, workdir: str) -> list[tuple[str, float]]:
    """Split audio into <=AUDIO_SEGMENT_SECONDS pieces by RE-ENCODING each one.

    Re-encoding (rather than `-c copy`) guarantees each piece is a valid,
    self-contained Opus file with a proper header — stream-copy splitting of
    Opus/Ogg produces headerless fragments that Whisper servers reject.
    """
    duration = _audio_duration(path)
    if duration <= AUDIO_SEGMENT_SECONDS:
        return [(path, 0.0)]
    seg_dir = os.path.join(workdir, "segments")
    os.makedirs(seg_dir, exist_ok=True)
    n = math.ceil(duration / AUDIO_SEGMENT_SECONDS)
    parts: list[tuple[str, float]] = []
    for i in range(n):
        start = i * AUDIO_SEGMENT_SECONDS
        out = os.path.join(seg_dir, f"seg_{i:04d}.ogg")
        _run(["ffmpeg", "-y", "-ss", str(start), "-t", str(AUDIO_SEGMENT_SECONDS),
              "-i", path, "-vn", "-ac", "1", "-ar", "16000",
              "-c:a", "libopus", "-b:a", "20k", out])
        if os.path.exists(out) and os.path.getsize(out) > 0:
            parts.append((out, float(start)))
    return parts or [(path, 0.0)]


def _whisper_one(path: str, offset: float, api_key: str, language: str | None) -> list[dict]:
    """Send one audio chunk to Groq, retrying transient 5xx/429/network errors."""
    last_err = ""
    for attempt in range(4):
        try:
            with open(path, "rb") as f:
                files = {"file": (os.path.basename(path), f, "application/ogg")}
                data = {"model": GROQ_MODEL, "response_format": "verbose_json",
                        "temperature": "0"}
                if language:
                    data["language"] = language
                resp = requests.post(
                    GROQ_URL, headers={"Authorization": f"Bearer {api_key}"},
                    files=files, data=data, timeout=300)
        except requests.RequestException as e:
            last_err = f"network: {e}"
            time.sleep(2 * (attempt + 1))
            continue
        if resp.status_code == 200:
            payload = resp.json()
            segs = []
            for s in payload.get("segments", []):
                text = (s.get("text") or "").strip()
                if not text:
                    continue
                start = float(s.get("start", 0.0)) + offset
                end = float(s.get("end", start)) + offset
                segs.append({"start": start, "dur": max(0.0, end - start), "text": text})
            return segs
        if resp.status_code in (429, 500, 502, 503, 529):    # transient — back off and retry
            last_err = f"{resp.status_code}: {resp.text[:150]}"
            log(f"Groq transient error, retry {attempt + 1}/4 ({last_err})")
            time.sleep(2 ** (attempt + 1))                    # 2, 4, 8, 16s
            continue
        raise TranscribeError(f"Groq Whisper returned error {resp.status_code}: {resp.text[:300]}")
    raise TranscribeError(f"Groq Whisper unavailable after 4 attempts ({last_err}).")


def whisper_transcribe(audio_path: str, workdir: str, api_key: str,
                       language: str | None, progress=None) -> list[dict]:
    parts = _split_audio(audio_path, workdir)
    n = len(parts)
    log(f"transcribing {n} audio segment(s) via Groq")
    all_segs: list[dict] = []
    for i, (path, offset) in enumerate(parts):    # sequential: keeps memory low, order stable
        if progress:
            progress(0.3 + 0.18 * i / max(1, n), f"Transcribing speech {i + 1}/{n}…")
        all_segs.extend(_whisper_one(path, offset, api_key, language))
    all_segs.sort(key=lambda s: s["start"])
    if not all_segs:
        raise TranscribeError("Whisper found no speech in the audio.")
    return all_segs


# Lazily-loaded local model (only built if we actually need it).
_LOCAL_MODEL = None


def _get_local_model():
    global _LOCAL_MODEL
    if _LOCAL_MODEL is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise TranscribeError(
                "faster-whisper is not installed — speech recognition is unavailable."
            ) from e
        log(f"loading local Whisper model '{WHISPER_MODEL}' ({WHISPER_COMPUTE})")
        _LOCAL_MODEL = WhisperModel(WHISPER_MODEL, device="cpu", compute_type=WHISPER_COMPUTE)
    return _LOCAL_MODEL


def local_whisper_transcribe(audio_path: str, language: str | None) -> list[dict]:
    """Run faster-whisper on the server. Free, no API key, no geo-block."""
    model = _get_local_model()
    segments, _info = model.transcribe(
        audio_path, language=language, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500})
    out: list[dict] = []
    for s in segments:                            # generator — streams as it decodes
        text = (s.text or "").strip()
        if text:
            out.append({"start": float(s.start), "dur": max(0.0, float(s.end) - float(s.start)),
                        "text": text})
    if not out:
        raise TranscribeError("Whisper found no speech in the audio.")
    return out


def run_asr(audio_path: str, workdir: str, language: str | None, progress=None) -> list[dict]:
    """Dispatch to Groq (fast, needs key); fall back to local faster-whisper on failure."""
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        try:
            return whisper_transcribe(audio_path, workdir, groq_key, language, progress=progress)
        except TranscribeError as e:
            log(f"Groq failed ({e}); falling back to local Whisper")
            if progress:
                progress(0.32, "Transcribing locally — a bit slower…")
    return local_whisper_transcribe(audio_path, language)


# --------------------------------------------------------------------------- #
# Grouping + chunking (shared with the offline tool)
# --------------------------------------------------------------------------- #
def build_lines(segments: list[dict]) -> list[dict]:
    lines: list[dict] = []
    cur_words: list[str] = []
    cur_start = None
    prev_end = None
    for seg in segments:
        text = " ".join((seg["text"] or "").split())
        if not text:
            continue
        marker = text.strip("[]").lower()
        if marker in ("музыка", "music", "аплодисменты", "applause", "смех", "laughter"):
            continue
        gap = (seg["start"] - prev_end) if prev_end is not None else 0.0
        if cur_words and (gap > LINE_BREAK_PAUSE or len(cur_words) >= LINE_MAX_WORDS):
            lines.append({"start": cur_start, "text": " ".join(cur_words)})
            cur_words = []
        if not cur_words:
            cur_start = seg["start"]
            if lines:
                lines[-1]["gap_after"] = gap
        cur_words.extend(text.split())
        prev_end = seg["start"] + seg["dur"]
    if cur_words:
        lines.append({"start": cur_start, "text": " ".join(cur_words)})
    return lines


def split_chunks(lines: list[dict]) -> list[list[dict]]:
    total = sum(len(l["text"].split()) for l in lines)
    n = max(1, round(total / TARGET_CHUNK_WORDS))
    if n == 1:
        return [lines]
    target = total / n
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    cur_words = 0
    for line in lines:
        cur.append(line)
        cur_words += len(line["text"].split())
        if len(chunks) < n - 1 and cur_words >= target * 0.75:
            gap = line.get("gap_after") or 0.0
            if cur_words >= target or gap >= LINE_BREAK_PAUSE:
                chunks.append(cur)
                cur, cur_words = [], 0
    if cur:
        chunks.append(cur)
    return chunks


# --------------------------------------------------------------------------- #
# Formatting with Claude
# --------------------------------------------------------------------------- #
def basic_format(lines: list[dict]) -> tuple[str, list[dict]]:
    """Free fallback: group lines into paragraphs by pauses. No LLM, no chapters."""
    paras: list[str] = []
    cur: list[str] = []
    cur_words = 0
    cur_start = None
    for l in lines:
        if not cur:
            cur_start = l["start"]
        cur.append(l["text"])
        cur_words += len(l["text"].split())
        gap = l.get("gap_after") or 0.0
        if cur_words >= 110 or gap >= 2.5:
            paras.append(f"[{fmt_ts(cur_start)}] " + " ".join(cur))
            cur, cur_words = [], 0
    if cur:
        paras.append(f"[{fmt_ts(cur_start)}] " + " ".join(cur))
    return "\n\n".join(paras), []


def _anthropic_client(api_key: str):
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def _format_prompt(chunk_text: str, idx: int, total: int) -> str:
    return f"""Ты форматируешь фрагмент {idx} из {total} расшифровки речи (транскрипт видео).

Ниже сырой текст: каждая строка начинается с таймкода [М:СС], затем распознанная речь.

ЗАДАЧА — привести к читаемому виду:
1. Сохрани ВСЁ содержание и авторскую лексику дословно. Нельзя пересказывать, сокращать, выбрасывать предложения, «улучшать» стиль. Авторские повторы сохраняй.
2. Разрешено чинить только артефакты распознавания: пунктуация, заглавные буквы, склейка разорванных слов, очевидные ослышки. Непонятное оставляй как есть.
3. Разбей на логические абзацы по смыслу (обычно 3–8 предложений). Абзац = одна мысль.
4. Каждый абзац начинай С НОВОЙ СТРОКИ с таймкода в квадратных скобках и пробела: «[М:СС] текст…», где таймкод — это метка строки, с которой начинается абзац (ближайшая предшествующая).
5. Между абзацами — одна пустая строка. Никаких заголовков, markdown, звёздочек, ссылок — только абзацы обычным текстом.

Верни ТОЛЬКО отформатированный текст, без комментариев.

СЫРОЙ ТЕКСТ:
{chunk_text}"""


def _breaks_prompt(numbered: str, idx: int, total: int) -> str:
    return f"""Фрагмент {idx}/{total} транскрипта, разбитый на пронумерованные строки. Текст УЖЕ с пунктуацией — переписывать или менять его НЕ нужно.

Задача: определить, где начинаются логические абзацы по смыслу (обычно 3–8 предложений на абзац, абзац = одна мысль).

Начинай новый абзац ТОЛЬКО на строке, которая начинает новое предложение (предыдущая строка заканчивается точкой, «!», «?» или «…») — не разрывай предложение посередине.

Верни СТРОГО JSON без пояснений:
{{"breaks": [номера строк, с которых начинается новый абзац]}}
Строка 1 всегда начинает абзац — включи её. Номера по возрастанию.

СТРОКИ:
{numbered}"""


def _chapters_prompt(outline_text: str, timestamps: list[str]) -> str:
    ts_list = ", ".join(timestamps)
    return f"""Ниже краткая структура видео — начало каждого абзаца с таймкодом [М:СС].

Выбери 5–9 смысловых разделов (глав), покрывающих всё видео. Первая глава — в самом начале.

Требования:
- Заголовок 2–6 слов на языке транскрипта, без нумерации и знаков форматирования.
- Таймкод каждой главы ДОЛЖЕН точно совпадать с таймкодом одного из абзацев ниже.
- Допустимые таймкоды (выбирай только из них): {ts_list}

Верни строго JSON-массив вида:
[{{"ts": "0:00", "title": "Название"}}, ...]
Только JSON, без пояснений.

СТРУКТУРА:
{outline_text}"""


def _claude_text(client, prompt: str, max_tokens: int) -> str:
    resp = client.messages.create(
        model=FORMAT_MODEL, max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def _groq_text(prompt: str, max_tokens: int, api_key: str, model: str | None = None,
               attempts: int = 3, wait_cap: float = 12) -> str:
    """LLM text via Groq's free open model, retrying rate-limit / transient errors.

    attempts/wait_cap tune the patience: formatting fails fast (it has a
    fallback), translation waits out per-minute token limits (429 storms).
    """
    last = ""
    for attempt in range(attempts):
        try:
            resp = requests.post(
                GROQ_CHAT_URL, headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model or FORMAT_GROQ_MODEL,
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.2, "max_tokens": max_tokens},
                timeout=60)
        except requests.RequestException as e:
            last = str(e)
            time.sleep(2 * (attempt + 1))
            continue
        if resp.status_code == 200:
            return (resp.json()["choices"][0]["message"]["content"] or "").strip()
        # 408 + Cloudflare 52x (esp. 524 = upstream timeout) are transient — back off & retry.
        if resp.status_code in (408, 429, 500, 502, 503, 520, 522, 523, 524, 525, 529):
            last = f"{resp.status_code}: {resp.text[:120]}"
            wait = resp.headers.get("retry-after")
            try:
                delay = float(wait) if wait else 2 ** (attempt + 1)
            except ValueError:
                delay = 2 ** (attempt + 1)
            time.sleep(min(delay, wait_cap))
            continue
        raise TranscribeError(f"Groq LLM error {resp.status_code}: {resp.text[:200]}")
    raise TranscribeError(f"Groq LLM unavailable after retries ({last}).")


def _thinking_cfg(model: str) -> dict:
    # Gemini 3 uses thinkingLevel; 2.x uses thinkingBudget. Either way thinking
    # must be minimal or it silently eats the output budget.
    if model.startswith("gemini-3"):
        return {"thinkingLevel": "LOW"}
    return {"thinkingBudget": 0}


def _gemini_one(prompt: str, max_tokens: int, api_key: str, model: str,
                attempts: int = 3, wait_cap: float = 70) -> str:
    last = ""
    for attempt in range(attempts):
        try:
            resp = requests.post(
                GEMINI_URL.format(model=model),
                headers={"X-goog-api-key": api_key},
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": 0.2,
                                           "maxOutputTokens": max_tokens,
                                           "thinkingConfig": _thinking_cfg(model)}},
                timeout=180)
        except requests.RequestException as e:
            last = str(e)
            time.sleep(3 * (attempt + 1))
            continue
        if resp.status_code == 200:
            try:
                j = resp.json()
                cand = j["candidates"][0]
                if cand.get("finishReason") == "MAX_TOKENS":
                    raise TranscribeError("Gemini: output truncated (MAX_TOKENS)")
                parts = cand["content"]["parts"]
                return "".join(p.get("text", "") for p in parts
                               if not p.get("thought")).strip()
            except (KeyError, IndexError, ValueError):
                raise TranscribeError(f"Gemini: unexpected response {resp.text[:200]}")
        if resp.status_code in (408, 429, 500, 502, 503, 504):
            last = f"{resp.status_code}: {resp.text[:120]}"
            wait = resp.headers.get("retry-after")
            try:
                delay = float(wait) if wait else 5 * (attempt + 1)
            except ValueError:
                delay = 5 * (attempt + 1)
            time.sleep(min(delay, wait_cap))   # free tier: 10 RPM — waits are normal
            continue
        raise TranscribeError(f"Gemini error {resp.status_code}: {resp.text[:200]}")
    raise TranscribeError(f"Gemini unavailable after retries ({last}).")


def _gemini_text(prompt: str, max_tokens: int, api_key: str, fast: bool = False) -> str:
    """Gemini with a two-model quota pool: primary, then the fallback model.

    fast=True is the interactive lane: someone is watching a progress bar, so
    fail over quickly instead of patiently waiting out rate-limit windows."""
    attempts, cap = (2, 15) if fast else (3, 70)
    try:
        return _gemini_one(prompt, max_tokens, api_key, GEMINI_MODEL,
                           attempts=attempts, wait_cap=cap)
    except TranscribeError as e:
        log(f"{GEMINI_MODEL} failed ({str(e)[:80]}); trying {GEMINI_MODEL_2}")
        return _gemini_one(prompt, max_tokens, api_key, GEMINI_MODEL_2,
                           attempts=attempts, wait_cap=cap)


def _is_punctuated(lines: list[dict]) -> bool:
    """True if the source text already has sentence punctuation (→ breaks mode)."""
    text = " ".join(l["text"] for l in lines)
    words = text.split()
    if len(words) < 50:
        return False
    marks = sum(text.count(c) for c in ".!?…")
    return marks / len(words) >= 0.03


def _breaks_paragraphs(raw: str, lines: list[dict]) -> list[str]:
    """Assemble paragraphs from original lines using Claude's break line numbers."""
    breaks: list[int] = []
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            for b in json.loads(m.group(0)).get("breaks", []):
                bi = int(b)
                if 1 <= bi <= len(lines):
                    breaks.append(bi)
    except Exception as e:
        log(f"breaks parse failed: {e}")
    breaks = sorted(set(breaks))
    if not breaks or breaks[0] != 1:
        breaks = [1] + breaks
    bounds = breaks + [len(lines) + 1]
    paras: list[str] = []
    for k in range(len(breaks)):
        seg = lines[breaks[k] - 1: bounds[k + 1] - 1]
        text = " ".join(l["text"].strip() for l in seg if l["text"].strip())
        if text:
            paras.append(f"[{fmt_ts(seg[0]['start'])}] {text}")
    return paras


def _pick_chapters(text_fn, body: str) -> list[dict]:
    """Chapter selection over a compact outline (paragraph starts only) — cheap."""
    timestamps = re.findall(r"^\[([\d:]+)\]", body, flags=re.MULTILINE)
    if not timestamps:
        return []
    outline = "\n".join(" ".join(p.split()[:16]) for p in body.split("\n\n") if p.strip())
    try:
        raw = text_fn(_chapters_prompt(outline, timestamps), 1500)
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            valid = set(timestamps)
            return [c for c in json.loads(m.group(0))
                    if isinstance(c, dict) and c.get("ts") in valid and c.get("title")]
    except Exception as e:
        log(f"chapter selection failed: {e}")
    return []


def format_transcript(chunks: list[list[dict]], text_fn, max_workers: int = 6,
                      progress=None, force_mode: str | None = None) -> tuple[str, list[dict]]:
    """Format chunks in parallel with the given LLM text function (Claude or Groq).

    force_mode: override FORMAT_MODE — free Groq must always use "breaks",
    because a full-text "rewrite" request exceeds its free-tier per-request
    token limit (HTTP 413) on typical chunk sizes.
    """
    total = len(chunks)
    all_lines = [l for c in chunks for l in c]
    mode = force_mode or FORMAT_MODE
    if mode == "auto":
        mode = "breaks" if _is_punctuated(all_lines) else "rewrite"
    log(f"format mode: {mode}")

    def do_chunk(i: int) -> tuple[int, list[str]]:
        if mode == "breaks":
            numbered = "\n".join(f"{j + 1}. {l['text']}" for j, l in enumerate(chunks[i]))
            raw = text_fn(_breaks_prompt(numbered, i + 1, total), 800)
            return i, _breaks_paragraphs(raw, chunks[i])
        raw = "\n".join(f"[{fmt_ts(l['start'])}] {l['text']}" for l in chunks[i])
        formatted = text_fn(_format_prompt(raw, i + 1, total), 8000)
        return i, [p.strip() for p in formatted.split("\n\n") if p.strip()]

    results: dict[int, list[str]] = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, total)) as ex:
        futures = {ex.submit(do_chunk, i): i for i in range(total)}
        done = 0
        for fut in as_completed(futures):
            i, paras = fut.result()
            results[i] = paras
            done += 1
            if progress:
                progress(0.5 + 0.4 * done / total, f"Formatting {done}/{total}")

    body_paras: list[str] = []
    for i in range(total):
        body_paras.extend(results[i])
    body = "\n\n".join(body_paras).strip()
    chapters = _pick_chapters(text_fn, body)
    return body, chapters


# --------------------------------------------------------------------------- #
# Bulk mode: whole video in ONE LLM request (paragraphs + chapters together)
# --------------------------------------------------------------------------- #
def _bulk_prompt(numbered: str) -> str:
    return f"""Транскрипт видео, разбитый на пронумерованные строки. Текст менять НЕЛЬЗЯ.

Задачи:
1. breaks — номера строк, с которых начинаются логические абзацы (обычно 3–8 предложений на абзац; строка 1 всегда включена; номера по возрастанию; новый абзац только там, где предыдущая строка заканчивает предложение).
2. chapters — 5–9 смысловых глав, покрывающих всё видео. У каждой: "line" — номер строки начала главы (ДОЛЖЕН входить в breaks; первая глава — строка 1) и "title" — 2–6 слов на языке транскрипта.

Верни СТРОГО JSON без пояснений:
{{"breaks": [1, ...], "chapters": [{{"line": 1, "title": "..."}}, ...]}}

СТРОКИ:
{numbered}"""


def bulk_format_one(text_fn, lines: list[dict]) -> tuple[str, list[dict]]:
    """Format a whole video with a single LLM call (needs a big-context model)."""
    numbered = "\n".join(f"{j + 1}. {l['text']}" for j, l in enumerate(lines))
    raw = text_fn(_bulk_prompt(numbered), 6000)
    if not re.search(r"\{.*\}", raw, re.DOTALL):
        raise TranscribeError("bulk formatter returned no JSON")
    paras = _breaks_paragraphs(raw, lines)      # reads "breaks" from the JSON
    if len(lines) > 40 and len(paras) <= 1:     # degenerate: one giant paragraph
        raise TranscribeError("bulk formatter returned no usable paragraph breaks")
    body = "\n\n".join(paras)
    chapters: list[dict] = []
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        chapters_raw = json.loads(m.group(0)).get("chapters", []) if m else []
    except Exception as e:
        log(f"bulk chapters parse failed: {e}")
        chapters_raw = []
    para_ts = set(re.findall(r"^\[([\d:]+)\]", body, flags=re.MULTILINE))
    for c in chapters_raw:
        try:
            n = int(c.get("line"))
            title = str(c.get("title") or "").strip()
        except (TypeError, ValueError):
            continue
        if 1 <= n <= len(lines) and title:
            ts = fmt_ts(lines[n - 1]["start"])
            if ts in para_ts:                   # chapter must sit on a paragraph start
                chapters.append({"ts": ts, "title": title})
    return body, chapters


def _bulk_build(segments: list[dict], payload: dict, source_note: str) -> dict:
    """Shared tail of the bulk endpoints: segments → formatted TXT (+ optional SRT),
    with the views/published/captured header. Engine order Gemini → Groq → basic."""
    meta = {"title": str(payload.get("title") or "transcript"),
            "channel": str(payload.get("channel") or ""),
            "url": str(payload.get("url") or ""),
            "views": payload.get("views"),
            "published": str(payload.get("published") or ""),
            "captured": str(payload.get("captured") or "")}
    want_summary = bool(payload.get("want_summary"))
    translate_to = str(payload.get("translate_to") or "").strip() or None

    lines = build_lines(segments)
    if not lines:
        return {"error": "no text (music or no speech)"}   # don't ship a header-only file
    gemini_key = os.environ.get("GEMINI_API_KEY")
    groq_key = os.environ.get("GROQ_API_KEY")
    body = None
    chapters: list[dict] = []
    if gemini_key:
        try:
            body, chapters = bulk_format_one(
                lambda p, mt: _gemini_text(p, mt, gemini_key), lines)
        except TranscribeError as e:
            log(f"bulk gemini failed ({e}); trying Groq")
            body = None
    if body is None and groq_key:
        try:
            body, chapters = format_transcript(
                split_chunks(lines),
                lambda p, mt: _groq_text(p, mt, groq_key, attempts=5, wait_cap=30),
                max_workers=3, force_mode="breaks")
        except TranscribeError as e:
            log(f"bulk groq failed ({e}); basic paragraphs")
            body = None
    if body is None:
        body, chapters = basic_format(lines)

    if translate_to and groq_key and body:
        try:
            body = translate_body(body, translate_to, groq_key)
        except TranscribeError as e:
            log(f"bulk translation failed ({e}); keeping original language")
    summary = None
    if want_summary and groq_key and body:
        summary = summarize(body, groq_key)

    txt = assemble_txt(meta, source_note, body, chapters, summary=summary)
    out = {"filename": f"{safe_filename(meta['title'])}.txt", "txt": txt,
           "source": source_note}
    if payload.get("want_srt"):
        srt = to_srt(segments)
        if srt:
            out["srt_filename"] = f"{safe_filename(meta['title'])}.srt"
            out["srt"] = srt
    return out


def bulk_asr(audio_path, payload) -> dict:
    """Bulk AUDIO path: the Mac worker downloaded the audio track (its home IP works)
    and uploaded it here; we transcribe it with Whisper and format the TXT. Used for
    videos with NO captions anywhere, since the cloud's own YouTube audio access is
    blocked (datacenter IP)."""
    try:
        if isinstance(payload, str):
            payload = json.loads(payload or "{}")
        payload = payload or {}
        if not audio_path or not os.path.exists(audio_path):
            return {"error": "no audio uploaded"}
        lang = str(payload.get("language") or "") or None
        with tempfile.TemporaryDirectory() as workdir:
            audio = extract_audio(audio_path, workdir)   # ffmpeg downmix (cloud has it)
            segs = run_asr(audio, workdir, lang)
        segments = [{"start": float(s.get("start", 0)), "dur": float(s.get("dur", 0)),
                     "text": str(s.get("text", ""))}
                    for s in (segs or []) if str(s.get("text", "")).strip()]
        if not segments:
            return {"error": "speech recognition produced no text"}
        return _bulk_build(segments, payload, "speech recognition (Whisper)")
    except Exception as e:  # noqa: BLE001 — API endpoint must return JSON, not raise
        log(f"bulk_asr crashed: {e}")
        return {"error": str(e)[:300]}


def bulk_format(payload) -> dict:
    """Cloud half of bulk mode: the Mac worker fetches captions locally (home IP —
    YouTube allows it) and posts raw segments here; we format and return the TXT.
    Engine order: Gemini (1 request/video, huge daily budget) → Groq → basic."""
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        segments = [{"start": float(s.get("start", 0)), "dur": float(s.get("dur", 0)),
                     "text": str(s.get("text", ""))}
                    for s in (payload.get("segments") or [])
                    if str(s.get("text", "")).strip()]
        source_note = "subtitles (fetched locally)"
        # Fallback: the Mac worker's home IP got rate-limited by YouTube, so it asked
        # us to fetch the captions server-side (Supadata → backups, never blocked).
        # If there are no captions anywhere and allow_asr is set, transcribe the audio.
        if not segments and payload.get("fetch") and payload.get("url"):
            url = str(payload["url"])
            lang = str(payload.get("language") or "") or None
            try:
                fetched, source_note = fetch_segments_server(url, lang)
            except TranscribeError as cap_err:
                if payload.get("allow_asr"):
                    try:
                        fetched, source_note = asr_segments_server(url, lang)
                    except TranscribeError as asr_err:
                        return {"error": f"no subtitles; audio failed: {str(asr_err)[:200]}"}
                else:
                    return {"error": str(cap_err)[:300]}
            segments = [{"start": float(s.get("start", 0)), "dur": float(s.get("dur", 0)),
                         "text": str(s.get("text", ""))}
                        for s in fetched if str(s.get("text", "")).strip()]
        if not segments:
            return {"error": "no segments"}
        return _bulk_build(segments, payload, source_note)
    except Exception as e:  # noqa: BLE001 — API endpoint must return JSON, not raise
        log(f"bulk_format crashed: {e}")
        return {"error": str(e)[:300]}


# --------------------------------------------------------------------------- #
# Summary + key points (free Groq LLM)
# --------------------------------------------------------------------------- #
def summarize(body: str, api_key: str) -> dict | None:
    """Summary + key points via Groq's free open LLM. Output in the video's language."""
    text = re.sub(r"^\[[\d:]+\]\s*", "", body, flags=re.MULTILINE)  # drop timestamps
    text = text[:26000]
    prompt = (
        "Below is a video transcript. In the SAME LANGUAGE as the transcript, produce:\n"
        "1) summary — a 2-4 sentence overview of what the video is about;\n"
        "2) key_points — 5-8 key takeaways, each a short single line.\n"
        'Return STRICT JSON only: {"summary": "...", "key_points": ["...", "..."]}.\n\n'
        "TRANSCRIPT:\n" + text
    )
    try:
        resp = requests.post(
            GROQ_CHAT_URL, headers={"Authorization": f"Bearer {api_key}"},
            json={"model": SUMMARY_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.3, "max_tokens": 1400,
                  "response_format": {"type": "json_object"}},
            timeout=120)
    except requests.RequestException as e:
        log(f"summary request failed: {e}")
        return None
    if resp.status_code != 200:
        log(f"summary failed: {resp.status_code} {resp.text[:200]}")
        return None
    try:
        content = resp.json()["choices"][0]["message"]["content"]
        d = json.loads(content)
        summary = (d.get("summary") or "").strip()
        points = [str(k).strip() for k in d.get("key_points", []) if str(k).strip()]
        return {"summary": summary, "key_points": points} if (summary or points) else None
    except Exception as e:
        log(f"summary parse failed: {e}")
        return None


# --------------------------------------------------------------------------- #
# Translation (free Groq LLM)
# --------------------------------------------------------------------------- #
def _translate_prompt(block: str, lang_name: str) -> str:
    return f"""Translate the transcript excerpt below into {lang_name}.

STRICT RULES:
- Each paragraph starts with a timestamp like [12:34] — keep it EXACTLY as is at the start of the translated paragraph.
- Keep the same paragraphs: same count, separated by one blank line. Do not merge or split them.
- Translate the full content faithfully — no summarizing, no additions, no comments.
- Return ONLY the translated text.

TEXT:
{block}"""


def _chunk_paragraphs(paras: list[str], limit: int) -> list[list[str]]:
    chunks: list[list[str]] = []
    cur: list[str] = []
    cur_len = 0
    for p in paras:
        if cur and cur_len + len(p) > limit:
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(p)
        cur_len += len(p)
    if cur:
        chunks.append(cur)
    return chunks


def _translate_gemini(paras: list[str], lang_name: str, api_key: str,
                      progress=None) -> str:
    """Fast path: Gemini swallows ~12k chars per request with no TPM waits —
    a whole video translates in a couple of calls instead of ~20 Groq chunks."""
    chunks = _chunk_paragraphs(paras, 12000)
    out: list[str] = []
    for i, ch in enumerate(chunks):
        if progress:
            progress(0.84 + 0.08 * i / len(chunks),
                     f"Translating {i + 1}/{len(chunks)}…")
        t = _gemini_text(_translate_prompt("\n\n".join(ch), lang_name), 30000, api_key)
        if not t.strip():
            raise TranscribeError("Gemini returned an empty translation")
        out.append(t.strip())
    return "\n\n".join(out)


def translate_body(body: str, target: str, api_key: str, progress=None) -> str:
    """Translate formatted paragraphs, preserving timestamps and paragraph breaks."""
    paras = [p for p in body.split("\n\n") if p.strip()]
    if not paras:
        return body
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        try:
            return _translate_gemini(paras, LANG_NAMES.get(target, target),
                                     gemini_key, progress=progress)
        except TranscribeError as e:
            log(f"gemini translation failed ({e}); falling back to Groq")
    chunks: list[list[str]] = []
    cur: list[str] = []
    cur_len = 0
    for p in paras:
        if cur and cur_len + len(p) > 2600:
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(p)
        cur_len += len(p)
    if cur:
        chunks.append(cur)

    lang_name = LANG_NAMES.get(target, target)
    n = len(chunks)
    log(f"translating {n} chunk(s) to {lang_name}")

    def one(i: int) -> tuple[int, str]:
        # Patient retries: a long video legitimately needs several minutes of
        # per-minute-token-limit pacing on the free tier — wait it out.
        prompt = _translate_prompt("\n\n".join(chunks[i]), lang_name)
        try:
            return i, _groq_text(prompt, 4000, api_key, model=TRANSLATE_MODEL,
                                 attempts=6, wait_cap=45)
        except TranscribeError as e:
            log(f"translate chunk {i + 1} on {TRANSLATE_MODEL} failed ({e}); using fallback model")
            return i, _groq_text(prompt, 4000, api_key, model=TRANSLATE_FALLBACK_MODEL,
                                 attempts=6, wait_cap=45)

    out: list[str] = [""] * n
    done = 0
    with ThreadPoolExecutor(max_workers=min(3, n)) as ex:
        futures = {ex.submit(one, i): i for i in range(n)}
        for fut in as_completed(futures):
            i, text = fut.result()
            text = text.strip()
            if not text:   # empty completion — keep the original rather than losing content
                log(f"translate chunk {i + 1} returned empty — keeping original text")
                text = "\n\n".join(chunks[i])
            out[i] = text
            done += 1
            if progress:
                progress(0.84 + 0.08 * done / n, f"Translating {done}/{n}…")
    return "\n\n".join(out)


# --------------------------------------------------------------------------- #
# Usage / quota report
# --------------------------------------------------------------------------- #
def _usage_bar(left: int, total: int, width: int = 10) -> str:
    filled = max(0, min(width, round(width * left / total))) if total > 0 else 0
    return "▓" * filled + "░" * (width - filled)


def supadata_left() -> int | None:
    """Remaining Supadata credits — one cheap call, no LLM probes."""
    key = os.environ.get("SUPADATA_API_KEY")
    if not key:
        return None
    try:
        r = requests.get("https://api.supadata.ai/v1/me",
                         headers={"x-api-key": key}, timeout=20)
        d = r.json() if r.status_code == 200 else {}
        total = d.get("maxCredits") or d.get("creditsLimit")
        used = d.get("usedCredits", d.get("creditsUsed"))
        if isinstance(total, (int, float)) and isinstance(used, (int, float)):
            return max(0, int(total) - int(used))
    except Exception as e:
        log(f"supadata balance failed: {e}")
    return None


APIFY_FREE_LINKS = 500   # $5 free credit ÷ ~$0.01/video
SERPAPI_FREE = 250       # free tier searches/month


def _apify_left() -> int | None:
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        return None
    try:
        r = requests.get("https://api.apify.com/v2/users/me/usage/monthly",
                         params={"token": token}, timeout=15)
        if r.status_code == 200:
            used = float(r.json().get("data", {})
                         .get("totalUsageCreditsUsdAfterVolumeDiscount", 0) or 0)
            return int(max(0.0, 5.0 - used) / 0.01)
    except Exception as e:  # noqa: BLE001
        log(f"apify balance failed: {e}")
    return None


def _serpapi_left() -> int | None:
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        return None
    try:
        r = requests.get("https://serpapi.com/account.json",
                         params={"api_key": key}, timeout=15)
        if r.status_code == 200:
            return int(r.json().get("plan_searches_left", 0) or 0)
    except Exception as e:  # noqa: BLE001
        log(f"serpapi balance failed: {e}")
    return None


def _supadata_left_total() -> tuple[int, int] | None:
    key = os.environ.get("SUPADATA_API_KEY")
    if not key:
        return None
    try:
        r = requests.get("https://api.supadata.ai/v1/me",
                         headers={"x-api-key": key}, timeout=15)
        d = r.json() if r.status_code == 200 else {}
        total = d.get("maxCredits") or d.get("creditsLimit")
        used = d.get("usedCredits", d.get("creditsUsed"))
        if isinstance(total, (int, float)) and isinstance(used, (int, float)):
            return (max(0, int(total) - int(used)), int(total))
    except Exception as e:  # noqa: BLE001
        log(f"supadata usage failed: {e}")
    return (0, 100)   # exhausted-estimate fallback so the ring still counts the rest


def usage_json() -> dict:
    """Machine-readable remaining credits/limits (used by /usage and the Mini App).
    The 'supadata' field is the COMBINED YouTube-link capacity across every caption
    source (Supadata + Apify + SerpApi + backups), queried live where possible."""
    out: dict = {"supadata": None, "groq": [], "claude": bool(os.environ.get("ANTHROPIC_API_KEY"))}

    # combined YouTube-link capacity — query the 3 live sources in parallel to stay snappy
    left_total, cap_total = 0, 0
    tasks = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        if os.environ.get("SUPADATA_API_KEY"):
            tasks["supa"] = ex.submit(_supadata_left_total)
        if os.environ.get("APIFY_TOKEN"):
            tasks["apify"] = ex.submit(_apify_left)
        if os.environ.get("SERPAPI_KEY"):
            tasks["serp"] = ex.submit(_serpapi_left)
        results = {k: f.result() for k, f in tasks.items()}
    if "supa" in results and results["supa"]:
        l, t = results["supa"]; left_total += l; cap_total += t
    if "apify" in results:
        left_total += results["apify"] if results["apify"] is not None else APIFY_FREE_LINKS
        cap_total += APIFY_FREE_LINKS
    if "serp" in results:
        left_total += results["serp"] if results["serp"] is not None else SERPAPI_FREE
        cap_total += SERPAPI_FREE
    backups = (100 if os.environ.get("TRANSCRIPTAPI_KEY") else 0) \
        + (25 if os.environ.get("YT_TRANSCRIPT_IO_KEY") else 0)
    left_total += backups
    cap_total += backups
    if cap_total:
        out["supadata"] = {"left": left_total, "total": cap_total}

    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        for label, model in (("paragraphs", FORMAT_GROQ_MODEL),
                             ("summary & translation", SUMMARY_MODEL)):
            try:
                r = requests.post(
                    GROQ_CHAT_URL, headers={"Authorization": f"Bearer {groq_key}"},
                    json={"model": model, "messages": [{"role": "user", "content": "hi"}],
                          "max_tokens": 1}, timeout=20)
                out["groq"].append({"label": label,
                                    "left": int(r.headers.get("x-ratelimit-remaining-requests", 0))})
            except Exception:
                out["groq"].append({"label": label, "left": None})

    # (all caption sources are now summed into out["supadata"] above — the ring)
    return out


def usage_report() -> str:
    """Plain-language (Russian) snapshot of remaining credits/limits."""
    d = usage_json()
    lines: list[str] = ["📊 Сколько осталось"]

    if d["supadata"]:
        left, total = d["supadata"]["left"], d["supadata"]["total"]
        lines.append(f"\n🎬 Видео с YouTube:\n{_usage_bar(left, total)}  {left} из {total} в месяц")
    RU = {"paragraphs": "абзацы", "summary & translation": "саммари и перевод",
          "🛟 backup subtitles (auto)": "🛟 запас субтитров (включится сам)"}
    if d["groq"]:
        lines.append("\n🧠 Бесплатный ИИ:")
        for g in d["groq"]:
            left = g["left"]
            if left is None:
                lines.append(f"⚠️ {RU.get(g['label'], g['label'])}: сервис не ответил")
            elif isinstance(left, str):
                lines.append(f"{RU.get(g['label'], g['label'])}: {left} видео")
            else:
                mark = "✅" if left > 200 else "⚠️"
                lines.append(f"{mark} {RU.get(g['label'], g['label'])}: {left} на сегодня")
    if d["claude"]:
        lines.append("\n✨ Claude: ~$0.03–0.05 за видео, баланс — console.anthropic.com")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# SRT subtitles + Q&A over a transcript
# --------------------------------------------------------------------------- #
def _srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(segments: list[dict]) -> str | None:
    """Standard .srt from raw caption segments (original language only).
    Returns None when the segments carry no usable timing."""
    timed = [s for s in segments if float(s.get("dur") or 0) > 0 and str(s.get("text", "")).strip()]
    if len(timed) < 5:
        return None
    blocks = []
    for i, s in enumerate(timed, 1):
        start = float(s["start"])
        end = start + max(0.5, float(s["dur"]))
        blocks.append(f"{i}\n{_srt_time(start)} --> {_srt_time(end)}\n"
                      f"{str(s['text']).strip()}\n")
    return "\n".join(blocks)


def answer_question(transcript: str, question: str) -> str:
    """Answer a question strictly from the transcript (free Gemini → Groq)."""
    question = (question or "").strip()[:1000]
    gemini_key = os.environ.get("GEMINI_API_KEY")
    groq_key = os.environ.get("GROQ_API_KEY")

    def prompt(body_limit: int) -> str:
        return (f"Ниже транскрипт видео с таймкодами вида [М:СС]. Ответь на вопрос "
                f"пользователя ТОЛЬКО по содержанию транскрипта, на языке вопроса. "
                f"Укажи таймкоды мест, где об этом говорится. Если ответа в "
                f"транскрипте нет — честно скажи об этом.\n\n"
                f"ВОПРОС: {question}\n\nТРАНСКРИПТ:\n{transcript[:body_limit]}")

    if gemini_key:
        try:
            return _gemini_text(prompt(150000), 2000, gemini_key)
        except TranscribeError as e:
            log(f"qa gemini failed ({e}); trying groq")
    if groq_key:
        return _groq_text(prompt(20000), 1500, groq_key,
                          model=SUMMARY_MODEL, attempts=4, wait_cap=30)
    raise TranscribeError("No free AI is configured for Q&A.")


def _gemini_grounded(prompt: str, max_tokens: int, api_key: str, model: str,
                     attempts: int = 3) -> tuple[str, list[dict]]:
    """Gemini WITH Google Search grounding — returns (text, sources[])."""
    last = ""
    for attempt in range(attempts):
        try:
            resp = requests.post(
                GEMINI_URL.format(model=model),
                headers={"X-goog-api-key": api_key},
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "tools": [{"google_search": {}}],
                      "generationConfig": {"temperature": 0.3,
                                           "maxOutputTokens": max_tokens,
                                           "thinkingConfig": _thinking_cfg(model)}},
                timeout=180)
        except requests.RequestException as e:
            last = str(e)
            time.sleep(3 * (attempt + 1))
            continue
        if resp.status_code == 200:
            try:
                cand = resp.json()["candidates"][0]
                if cand.get("finishReason") == "MAX_TOKENS":
                    raise TranscribeError("Gemini: output truncated (MAX_TOKENS)")
                parts = cand.get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts
                               if not p.get("thought")).strip()
                sources, seen = [], set()
                for ch in cand.get("groundingMetadata", {}).get("groundingChunks", []):
                    web = ch.get("web") or {}
                    uri = web.get("uri")
                    if uri and uri not in seen:
                        seen.add(uri)
                        sources.append({"title": (web.get("title") or uri)[:120], "uri": uri})
                if not text:
                    raise TranscribeError("Gemini returned an empty review")
                return text, sources
            except (KeyError, IndexError, ValueError):
                raise TranscribeError(f"Gemini: unexpected response {resp.text[:200]}")
        if resp.status_code in (408, 429, 500, 502, 503, 504):
            last = f"{resp.status_code}: {resp.text[:120]}"
            wait = resp.headers.get("retry-after")
            try:
                delay = float(wait) if wait else 5 * (attempt + 1)
            except ValueError:
                delay = 5 * (attempt + 1)
            time.sleep(min(delay, 30))
            continue
        raise TranscribeError(f"Gemini error {resp.status_code}: {resp.text[:200]}")
    raise TranscribeError(f"Gemini unavailable after retries ({last}).")


def factcheck_transcript(transcript: str) -> dict:
    """AI review of a (factual/educational) video: dubious claims checked against
    web sources, the other side where relevant, an overall trust verdict."""
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        raise TranscribeError("Fact-check needs a Gemini key (GEMINI_API_KEY).")
    transcript = re.sub(r"^\[[\d:]+\]\s*", "", transcript or "", flags=re.MULTILINE)
    prompt = (
        "Ты — дотошный критический рецензент. Ниже транскрипт видео (обычно учебного "
        "или про факты). На ЯЗЫКЕ транскрипта дай короткий, конкретный разбор в таком виде:\n\n"
        "🔍 ПРОВЕРКА ФАКТОВ\n"
        "Перечисли конкретные утверждения из видео, которые сомнительны, устарели, "
        "преувеличены или ошибочны. Для каждого: короткая цитата/суть → в чём проблема → "
        "что показывают надёжные источники (сверься через веб-поиск). Бесспорные и точные "
        "вещи НЕ перечисляй. Если серьёзных ошибок нет — честно так и напиши.\n\n"
        "⚖️ ДРУГАЯ СТОРОНА\n"
        "Там, где тема дискуссионная, кратко изложи иную обоснованную точку зрения "
        "(1–3 пункта). Если тема бесспорная — пропусти этот раздел.\n\n"
        "✅ ИТОГ\n"
        "1–2 фразы: насколько в целом можно доверять фактам в этом видео.\n\n"
        "ВАЖНО: активно используй веб-поиск, чтобы проверить конкретные утверждения — "
        "особенно статистику, цифры, даты, имена, научные и исторические факты, а также "
        "всё актуальное. Для каждого проверенного спорного пункта опирайся на найденные "
        "источники, а не на общие слова. Не выдумывай проблемы там, где их нет.\n\n"
        "ТРАНСКРИПТ:\n" + transcript[:120000])
    try:
        text, sources = _gemini_grounded(prompt, 3500, gemini_key, GEMINI_MODEL)
    except TranscribeError as e:
        log(f"factcheck on {GEMINI_MODEL} failed ({e}); trying {GEMINI_MODEL_2}")
        text, sources = _gemini_grounded(prompt, 3500, gemini_key, GEMINI_MODEL_2)
    return {"text": text, "sources": sources[:12]}


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def _section(label: str) -> str:
    return f"{'═' * 52}\n  {label}\n{'═' * 52}"


def assemble_txt(meta: dict, source_note: str, body: str, chapters: list[dict],
                 summary: dict | None = None) -> str:
    # at least 6 "=" so the web preview always recognises the underline as a header
    header_lines = [meta["title"], "=" * max(6, min(len(meta["title"]), 60))]
    info = []
    if meta.get("channel"):
        info.append(f"Channel: {meta['channel']}")
    if meta.get("url"):
        info.append(f"Source: {meta['url']}")
    if meta.get("published"):
        info.append(f"Published: {meta['published']}")
    if meta.get("views") not in (None, ""):
        try:
            views_str = f"{int(meta['views']):,}"
        except (ValueError, TypeError):
            views_str = str(meta["views"])
        cap = f" (as of {meta['captured']})" if meta.get("captured") else ""
        info.append(f"Views: {views_str}{cap}")
    info.append(source_note)
    header_lines.append("  ·  ".join(info))

    parts: list[str] = ["\n".join(header_lines)]

    if summary:
        if summary.get("summary"):
            parts.append(_section("SUMMARY") + "\n\n" + summary["summary"])
        if summary.get("key_points"):
            kp = "\n".join(f"•  {p}" for p in summary["key_points"])
            parts.append(_section("KEY POINTS") + "\n\n" + kp)
    if chapters:
        outline = "\n".join(f"[{c['ts']}]  {c['title']}" for c in chapters)
        parts.append(_section("OUTLINE") + "\n\n" + outline)

    pending = {c["ts"]: c["title"] for c in chapters}
    body_parts: list[str] = []
    for para in body.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        m = re.match(r"^\[([\d:]+)\]", para)
        if m and m.group(1) in pending:
            title = pending.pop(m.group(1))
            body_parts.append(f"{'─' * 50}\n{title.upper()}\n{'─' * 50}")
        body_parts.append(para)
    parts.append(_section("TRANSCRIPT") + "\n\n" + "\n\n".join(body_parts))

    return "\n\n\n".join(parts) + "\n"


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def transcribe(url: str | None, file_path: str | None, language: str | None,
               want_summary: bool = True, use_claude: bool = False,
               translate_to: str | None = None, paid_title: bool = True,
               progress=None) -> tuple[str, str, str | None]:
    """Main entry. Returns (filename, txt_content, srt_content_or_None).

    Formatting engine: Claude (paid, best quality) when use_claude is on and a
    key exists; otherwise Groq's free open LLM; otherwise basic pause-based
    paragraphs (no LLM at all). Summary + key points always use free Groq.
    translate_to: optional language code — translate the result (free Groq).
    """
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    groq_key = os.environ.get("GROQ_API_KEY")
    translate_to = (translate_to or "").strip() or None

    def prog(frac, msg):
        if progress:
            progress(frac, msg)
        log(msg)

    rkey = None
    with tempfile.TemporaryDirectory() as workdir:
        segments = None
        meta = {"title": "transcript", "channel": "", "url": ""}
        source_note = ""

        if url and url.strip():
            video_id = parse_video_id(url)
            if not video_id:
                raise TranscribeError("This does not look like a YouTube link or video ID.")
            # Same link + same settings → instant answer, zero credits/LLM calls.
            rkey = (video_id, language or "", bool(want_summary), bool(use_claude),
                    translate_to or "")
            with _CACHE_LOCK:
                hit = _RESULT_CACHE.get(rkey)
                if hit is not None:
                    _RESULT_CACHE.move_to_end(rkey)
            if hit is not None:
                prog(1.0, "Done (cached)")
                return hit
            watch_url = f"https://www.youtube.com/watch?v={video_id}"
            supa_key = os.environ.get("SUPADATA_API_KEY")
            if supa_key:
                skey = (video_id, language or "")
                with _CACHE_LOCK:
                    vlock = _SEG_LOCKS.setdefault(video_id, threading.Lock())
                    if len(_SEG_LOCKS) > 200:      # keep the lock table bounded
                        keep = {k[0] for k in _SEG_CACHE} | {video_id}
                        for vid in [v for v in _SEG_LOCKS if v not in keep][:50]:
                            del _SEG_LOCKS[vid]
                with vlock:            # concurrent requests for one video pay Supadata once
                    with _CACHE_LOCK:  # the dict itself is shared across per-video locks
                        cached = _SEG_CACHE.get(skey)
                    if cached is not None:
                        segments, title = cached
                        if title == video_id:      # earlier title fetch failed — retry it
                            title = (fetch_title_noembed(video_id)
                                     or (get_supadata_title(video_id, supa_key)
                                         if paid_title else None)
                                     or video_id)
                            if title != video_id:
                                with _CACHE_LOCK:
                                    _cache_put(_SEG_CACHE, skey, (segments, title),
                                               _SEG_CACHE_CAP)
                        prog(0.2, "Subtitles from cache…")
                        source_note = "subtitles (Supadata)"  # same note as fresh — files stay identical
                    else:
                        prog(0.12, "Fetching subtitles…")
                        # free title fetch runs in PARALLEL with the transcript
                        title_box: dict = {}
                        t_th = threading.Thread(
                            target=lambda: title_box.__setitem__(
                                "t", fetch_title_noembed(video_id)),
                            daemon=True)
                        t_th.start()
                        try:
                            segments = get_supadata_transcript(watch_url, supa_key,
                                                               language, progress=prog)
                            source_note = "subtitles (Supadata)"
                        except TranscribeError as e:
                            # any Supadata failure except a clean "no subtitles":
                            # give the backup sources a chance before giving up
                            if "no subtitles" in str(e).lower():
                                raise
                            prog(0.15, "Trying a backup subtitle source…")
                            fb = get_fallback_transcript(video_id)
                            if fb is None:
                                raise
                            segments, source_note = fb
                        t_th.join(timeout=7)
                        title = (title_box.get("t")
                                 or (get_supadata_title(video_id, supa_key)
                                     if paid_title else None)
                                 or video_id)
                        with _CACHE_LOCK:
                            _cache_put(_SEG_CACHE, skey, (segments, title), _SEG_CACHE_CAP)
                meta = {"url": watch_url, "title": title, "channel": ""}
            else:
                meta = fetch_meta(video_id)
                prog(0.08, "Checking YouTube subtitles…")
                segments = get_youtube_subtitles(video_id)
                if segments:
                    source_note = "YouTube subtitles"
                else:
                    prog(0.18, "No subtitles — downloading audio…")
                    audio = download_youtube_audio(meta["url"], workdir)
                    prog(0.3, "Transcribing speech…")
                    segments = run_asr(audio, workdir, language, progress=prog)
                    source_note = "speech recognition (Whisper)"
        elif file_path:
            meta["title"] = safe_filename(Path(file_path).stem)
            prog(0.15, "Extracting audio from the file…")
            audio = extract_audio(file_path, workdir)
            prog(0.3, "Transcribing speech…")
            segments = run_asr(audio, workdir, language, progress=prog)
            source_note = "speech recognition (Whisper)"
        else:
            raise TranscribeError("Provide a video link or upload a file.")

        if not segments:
            raise TranscribeError("Could not get text from this source.")

        lines = build_lines(segments)
        gemini_key = os.environ.get("GEMINI_API_KEY")
        body = None
        chapters: list[dict] = []
        text_fn = None
        if use_claude and anthropic_key:
            try:
                client = _anthropic_client(anthropic_key)
                text_fn = lambda p, mt: _claude_text(client, p, mt)
                prog(0.5, "Formatting into paragraphs…")
                body, chapters = format_transcript(split_chunks(lines), text_fn,
                                                   max_workers=6, progress=prog)
            except Exception as e:  # noqa: BLE001 — fall through to the free engines
                log(f"claude formatting failed ({e}); falling back to free engines")
                body = None
                rkey = None
        if body is None and gemini_key:
            # Best free engine: the whole video in one request, chapters included.
            # fast=True — a user is watching; fail over quickly rather than wait.
            try:
                text_fn = lambda p, mt: _gemini_text(p, mt, gemini_key, fast=True)
                prog(0.5, "Formatting into paragraphs…")
                body, chapters = bulk_format_one(text_fn, lines)
            except TranscribeError as e:
                log(f"gemini formatting failed ({e}); trying Groq")
                body = None
        if body is None and groq_key:
            # Interactive lane: fail fast to basic_format instead of waiting out
            # rate-limit windows for minutes.
            text_fn = lambda p, mt: _groq_text(p, mt, groq_key, attempts=3, wait_cap=12)
            prog(0.5, "Formatting into paragraphs…")
            try:
                body, chapters = format_transcript(split_chunks(lines), text_fn,
                                                   max_workers=3, progress=prog,
                                                   force_mode="breaks")
            except TranscribeError as e:
                # Free Groq overloaded/timed out — still deliver a usable result
                # via pause-based paragraphs instead of failing the whole job.
                log(f"free formatting failed ({e}); falling back to basic paragraphs")
                prog(0.9, "Using simple paragraphs…")
                body, chapters = basic_format(lines)
                rkey = None   # degraded output — don't cache it; a retry should re-try the LLM
        if body is None:
            text_fn = None
            prog(0.9, "Formatting into paragraphs…")
            body, chapters = basic_format(lines)
            if gemini_key or groq_key:
                rkey = None   # degraded relative to available engines — don't cache

        translated = False
        if translate_to and groq_key and body:
            prog(0.84, "Translating…")
            try:
                body = translate_body(body, translate_to, groq_key, progress=prog)
                # chapter titles must match the translated text — regenerate them
                chapters = _pick_chapters(text_fn, body) if text_fn else []
                source_note += f" · translated to {LANG_NAMES.get(translate_to, translate_to)}"
                translated = True
            except TranscribeError as e:
                log(f"translation failed ({e}); keeping the original language")
        if translate_to and not translated:
            rkey = None   # translation was requested but not delivered — never cache that

        summary = None
        if want_summary and groq_key and body:
            prog(0.93, "Summary & key points…")
            summary = summarize(body, groq_key)

        prog(0.95, "Building the file…")
        txt = assemble_txt(meta, source_note, body, chapters, summary=summary)
        srt = to_srt(segments)   # original language; None when no usable timing
        suffix = f" [{translate_to.upper()}]" if (translate_to and translated) else ""
        filename = f"{safe_filename(meta['title'])}{suffix}.txt"
        if rkey is not None:
            with _CACHE_LOCK:
                _RESULT_CACHE[rkey] = (filename, txt, srt)
                _RESULT_CACHE.move_to_end(rkey)
                while len(_RESULT_CACHE) > _RESULT_CACHE_CAP:
                    _RESULT_CACHE.popitem(last=False)
        return filename, txt, srt
