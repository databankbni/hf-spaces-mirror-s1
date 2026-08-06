# -*- coding: utf-8 -*-
import os
import time
import logging
import re
import requests
from flask import Flask, redirect, request, Response, jsonify

# إعداد السجلات
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
app = Flask(__name__)

# ---------- الإعدادات ----------
TMDB_API_KEY = os.environ.get("222696fb456b48f035cf8b0031e8f293", "")
if not TMDB_API_KEY:
    logging.error("❌ يجب تعيين متغير البيئة TMDB_API_KEY!")

TMDB_BASE = "https://api.themoviedb.org/3"
CACHE_TTL = 3600

cache = {"movies": [], "last_update": 0}
failed_streams = set()

# ---------- المصادر المحسّنة ----------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://multiembed.mov/"
}

def resolve_multiembed_url(imdb_id, season=None, episode=None):
    """
    MultiEmbed – نتبع إعادة التوجيه حتى نحصل على رابط التشغيل النهائي.
    """
    if season is not None and episode is not None:
        url = f"https://multiembed.mov/direct?video_id={imdb_id}&s={season}&e={episode}"
    else:
        url = f"https://multiembed.mov/direct?video_id={imdb_id}"

    try:
        # الخطوة 1: طلب مع تتبع إعادة التوجيه، ونأخذ الرابط النهائي
        session = requests.Session()
        resp = session.get(url, headers=HEADERS, allow_redirects=True, timeout=15)
        final_url = resp.url
        logging.info(f"MultiEmbed النهائي: {final_url}")

        # إذا كان الرابط النهائي ليس رابط تشغيل، نبحث داخل الصفحة
        if "m3u8" in final_url or "mpd" in final_url:
            return final_url
        else:
            # نبحث عن رابط m3u8 في النص
            match = re.search(r'(?:file|src)\s*:\s*"([^"]+\.m3u8[^"]*)"', resp.text)
            if match:
                return match.group(1)
            # ربما الرابط موجود في مكان آخر
            match = re.search(r'"(https?://[^"]+\.m3u8[^"]*)"', resp.text)
            if match:
                return match.group(1)

    except Exception as e:
        logging.warning(f"MultiEmbed resolver error: {e}")
    return None

def resolve_vidsrc_url(imdb_id, season=None, episode=None):
    """
    VidSrc – مصدر احتياطي ممتاز.
    """
    if season is not None and episode is not None:
        url = f"https://vidsrc.xyz/embed/tv?imdb={imdb_id}&season={season}&episode={episode}"
    else:
        url = f"https://vidsrc.xyz/embed/movie?imdb={imdb_id}"

    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        # VidSrc عادة يضمّن رابط m3u8 في جملة sources
        match = re.search(r'"url"\s*:\s*"([^"]+\.m3u8[^"]*)"', resp.text)
        if match:
            return match.group(1)
        # نحاول الحصول على iframe
        iframe_match = re.search(r'<iframe[^>]+src="([^"]+)"', resp.text)
        if iframe_match:
            iframe_resp = requests.get(iframe_match.group(1), headers=headers, timeout=10)
            match = re.search(r'"(https?://[^"]+\.m3u8[^"]*)"', iframe_resp.text)
            if match:
                return match.group(1)
    except Exception as e:
        logging.warning(f"VidSrc error: {e}")
    return None

def resolve_2embed_url(imdb_id, season=None, episode=None):
    """
    2Embed – محاولة إضافية.
    """
    if season is not None and episode is not None:
        embed_url = f"https://www.2embed.cc/embedtv/{imdb_id}&s={season}&e={episode}"
    else:
        embed_url = f"https://www.2embed.cc/embed/{imdb_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(embed_url, headers=headers, timeout=10)
        iframe_match = re.search(r'<iframe[^>]+src="([^"]+)"', resp.text)
        if iframe_match:
            iframe_src = iframe_match.group(1)
            iframe_resp = requests.get(iframe_src, headers=headers, timeout=10)
            for pattern in [
                r'(?:file|src)\s*:\s*"([^"]+\.m3u8[^"]*)"',
                r'"(https?://[^"]+\.m3u8[^"]*)"'
            ]:
                match = re.search(pattern, iframe_resp.text)
                if match:
                    return match.group(1)
    except Exception as e:
        logging.warning(f"2Embed error: {e}")
    return None

# قائمة المصادر حسب الأولوية
SOURCES = [
    resolve_multiembed_url,   # الأسرع
    resolve_vidsrc_url,       # قوي ومتوفر
    resolve_2embed_url        # احتياطي
]

def get_stream_url(imdb_id, season=None, episode=None):
    global failed_streams
    for source in SOURCES:
        try:
            url = source(imdb_id, season, episode)
            if url:
                logging.info(f"✅ نجح المصدر {source.__name__} لـ {imdb_id}")
                return url
        except Exception as e:
            logging.error(f"خطأ في {source.__name__}: {e}")
    failed_streams.add(imdb_id)
    logging.warning(f"❌ جميع المصادر فشلت لـ {imdb_id}")
    return None

# ---------- دوال TMDB (بدون تغيير) ----------
def get_imdb_id(tmdb_id, media_type="movie"):
    url = f"{TMDB_BASE}/{media_type}/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}"
    try:
        resp = requests.get(url, timeout=10).json()
        return resp.get("imdb_id")
    except Exception as e:
        logging.error(f"خطأ في جلب IMDb ID لـ {tmdb_id}: {e}")
        return None

def fetch_tmdb_movies():
    movies = []
    for page in [1, 2]:
        url = f"{TMDB_BASE}/movie/popular?api_key={TMDB_API_KEY}&language=ar&page={page}"
        try:
            resp = requests.get(url, timeout=10).json()
            for item in resp.get("results", []):
                tmdb_id = item["id"]
                imdb_id = get_imdb_id(tmdb_id, "movie")
                if not imdb_id:
                    continue
                poster = f"https://image.tmdb.org/t/p/w500{item['poster_path']}" if item.get("poster_path") else ""
                movies.append({
                    "imdb_id": imdb_id,
                    "name": item.get("title") or item.get("name", "بدون اسم"),
                    "year": item.get("release_date", "")[:4],
                    "poster": poster,
                    "type": "movie"
                })
            time.sleep(0.25)
        except Exception as e:
            logging.error(f"خطأ في جلب الأفلام صفحة {page}: {e}")
    return movies

def fetch_tmdb_series():
    series_list = []
    url = f"{TMDB_BASE}/tv/popular?api_key={TMDB_API_KEY}&language=ar&page=1"
    try:
        resp = requests.get(url, timeout=10).json()
        for item in resp.get("results", [])[:10]:
            tmdb_id = item["id"]
            imdb_id = get_imdb_id(tmdb_id, "tv")
            if not imdb_id:
                continue
            poster = f"https://image.tmdb.org/t/p/w500{item['poster_path']}" if item.get("poster_path") else ""
            name = item.get("name", "بدون اسم")
            year = item.get("first_air_date", "")[:4]
            detail_url = f"{TMDB_BASE}/tv/{tmdb_id}?api_key={TMDB_API_KEY}"
            detail = requests.get(detail_url, timeout=10).json()
            for season in detail.get("seasons", []):
                if season.get("season_number") == 0:
                    continue
                season_num = season["season_number"]
                episode_count = season.get("episode_count", 0)
                for ep in range(1, min(episode_count + 1, 6)):
                    series_list.append({
                        "imdb_id": imdb_id,
                        "name": f"{name} S{season_num:02d}E{ep:02d}",
                        "full_name": name,
                        "year": year,
                        "poster": poster,
                        "season": season_num,
                        "episode": ep,
                        "type": "series"
                    })
            time.sleep(0.25)
    except Exception as e:
        logging.error(f"خطأ في جلب المسلسلات: {e}")
    return series_list

def update_cache():
    global cache
    if time.time() - cache["last_update"] > CACHE_TTL:
        logging.info("🔄 جاري تحديث الكاش...")
        movies = fetch_tmdb_movies()
        series = fetch_tmdb_series()
        cache["movies"] = movies + series
        cache["last_update"] = time.time()
        logging.info(f"✅ تم تحديث الكاش: {len(cache['movies'])} مدخلاً.")
    return cache["movies"]

# ---------- نقاط النهاية ----------
@app.route("/")
def home():
    return """
    <h1>📺 سيرفر IPTV M3U احترافي – دعم VidSrc + MultiEmbed</h1>
    <p>القائمة: <code>/playlist.m3u</code></p>
    <p>اختبار فيلم: <code>/test/tt0111161</code></p>
    <p>الأفلام الفاشلة: <code>/failed</code></p>
    """

@app.route("/health")
def health():
    return jsonify({"status": "ok", "cache": len(cache["movies"]), "failed": len(failed_streams)})

@app.route("/failed")
def show_failed():
    return jsonify({"failed_ids": list(failed_streams)})

@app.route("/playlist.m3u")
def playlist():
    update_cache()
    lines = ["#EXTM3U"]
    host = request.host
    for media in cache["movies"]:
        if media["type"] == "movie":
            stream_url = f"https://{host}/stream/movie/{media['imdb_id']}"
            extinf = (f'#EXTINF:-1 tvg-id="{media["imdb_id"]}" tvg-name="{media["name"]}" '
                      f'tvg-logo="{media["poster"]}" group-title="🎬 أفلام",{media["name"]} ({media["year"]})')
        else:
            stream_url = f"https://{host}/stream/tv/{media['imdb_id']}/{media['season']}/{media['episode']}"
            extinf = (f'#EXTINF:-1 tvg-id="{media["imdb_id"]}" tvg-name="{media["name"]}" '
                      f'tvg-logo="{media["poster"]}" group-title="📺 مسلسلات",{media["full_name"]} - {media["name"]}')
        lines.append(extinf)
        lines.append(stream_url)
    return Response("\n".join(lines), mimetype="audio/x-mpegurl")

@app.route("/stream/movie/<imdb_id>")
def stream_movie(imdb_id):
    url = get_stream_url(imdb_id)
    if url:
        return redirect(url, code=302)
    return jsonify({"error": "لم يتم العثور على رابط"}), 404

@app.route("/stream/tv/<imdb_id>/<int:season>/<int:episode>")
def stream_tv(imdb_id, season, episode):
    url = get_stream_url(imdb_id, season, episode)
    if url:
        return redirect(url, code=302)
    return jsonify({"error": "لم يتم العثور على رابط"}), 404

@app.route("/test/<imdb_id>")
@app.route("/test/<imdb_id>/<int:season>/<int:episode>")
def test(imdb_id, season=None, episode=None):
    url = get_stream_url(imdb_id, season, episode)
    if url:
        return f"<h3>✅ الرابط: <a href='{url}'>{url}</a></h3>"
    else:
        return "<h3>❌ فشل في جلب الرابط</h3>"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860)