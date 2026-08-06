import os
import json
import time
import secrets
import asyncio
import threading
import base64
import html
import re
import urllib.request
import urllib.parse
import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Config ─────────────────────────────────────────────────────────────────────
SIMKL_CLIENT_ID     = os.environ.get("SIMKL_CLIENT_ID", "")
TMDB_API_KEY        = os.environ.get("TMDB_API_KEY", "")
YOUTUBE_API_KEY     = os.environ.get("YOUTUBE_API_KEY", "")
BASE_URL            = os.environ.get("BASE_URL", "https://vito200204-stremio-trakt-personal-hf-space.hf.space").rstrip("/")
HIDE_WATCHED        = os.environ.get("HIDE_WATCHED", "true").lower() in ("1", "true", "yes", "on")
MIN_VOTE_COUNT      = int(os.environ.get("MIN_VOTE_COUNT", "20"))
MIN_RATING          = float(os.environ.get("MIN_RATING", "0"))
EXCLUDE_REALITY     = os.environ.get("EXCLUDE_REALITY", "true").lower() in ("1", "true", "yes", "on")
ONLY_RELEASED       = os.environ.get("ONLY_RELEASED", "true").lower() in ("1", "true", "yes", "on")
FAST_CATALOGS       = os.environ.get("FAST_CATALOGS", "true").lower() in ("1", "true", "yes", "on")
CATALOG_TRAILERS    = os.environ.get("CATALOG_TRAILERS", "false").lower() in ("1", "true", "yes", "on")
CATALOG_LIMIT       = int(os.environ.get("CATALOG_LIMIT", "24"))
PRELOAD_CATALOGS    = os.environ.get("PRELOAD_CATALOGS", "false").lower() in ("1", "true", "yes", "on")
BACKGROUND_REFRESH  = os.environ.get("BACKGROUND_REFRESH", "false").lower() in ("1", "true", "yes", "on")
MAX_TRANSLATED_EPISODES = int(os.environ.get("MAX_TRANSLATED_EPISODES", "50"))

SIMKL_BASE   = "https://api.simkl.com"
SIMKL_APP_NAME = "nuvio-simkl-personal"
SIMKL_APP_VERSION = "7.9.0"
TMDB_BASE    = "https://api.themoviedb.org/3"
TMDB_POSTER  = "https://image.tmdb.org/t/p/w500"
TMDB_ORIG    = "https://image.tmdb.org/t/p/original"
TOKEN_FILE   = "/tmp/simkl_tokens.json"

# ── Cache ──────────────────────────────────────────────────────────────────────
_cache = {}
CACHE_TTL = 6 * 60 * 60            # 6 ore per catalog normali
CACHE_TTL_PERSONAL = 24 * 60 * 60  # 24 ore per raccomandazioni personali
CACHE_TTL_TRENDING = 2 * 60 * 60
CACHE_TTL_PERSONAL_FAST = 15 * 60
CACHE_TTL_WATCHED = 60 * 60
CACHE_TTL_TMDB_DETAILS = 7 * 24 * 60 * 60
CACHE_VERSION = "v790-simkl"
ANIME_DESC_CACHE_PREFIX = "anime_desc_it_v5"

GENRE_CATALOGS = {
    "action": {"name": "Azione", "movie": "28", "series": "10759"},
    "adventure": {"name": "Avventura", "movie": "12", "series": "10759"},
    "animation": {"name": "Animazione", "movie": "16", "series": "16"},
    "horror": {"name": "Horror", "movie": "27", "series": None},
    "thriller": {"name": "Thriller", "movie": "53", "series": "9648"},
    "scifi": {"name": "Sci-Fi", "movie": "878", "series": "10765"},
    "fantasy": {"name": "Fantasy", "movie": "14", "series": "10765"},
    "crime": {"name": "Crime", "movie": "80", "series": "80"},
    "comedy": {"name": "Commedia", "movie": "35", "series": "35"},
    "drama": {"name": "Dramma", "movie": "18", "series": "18"},
    "romance": {"name": "Romantici", "movie": "10749", "series": "18"},
    "mystery": {"name": "Mistero", "movie": "9648", "series": "9648"},
    "war": {"name": "Guerra", "movie": "10752", "series": "10768"},
    "western": {"name": "Western", "movie": "37", "series": "37"},
    "history": {"name": "Storia", "movie": "36", "series": None},
    "music": {"name": "Musica", "movie": "10402", "series": None},
    "documentary": {"name": "Documentari", "movie": "99", "series": "99"},
}

EXCLUDED_GENRE_LANGUAGES = {"hi", "ta", "te", "ml", "kn", "bn", "mr", "pa"}
PREFERRED_DISCOVERY_LANGUAGES = {"en", "it", "fr", "es", "de", "ja", "ko"}

MOVIE_GENRE_OPTIONS = [item["name"] for item in GENRE_CATALOGS.values() if item.get("movie")]
SERIES_GENRE_OPTIONS = [item["name"] for item in GENRE_CATALOGS.values() if item.get("series")]
MOVIE_GENRE_EXTRA = [{"name": "genre", "isRequired": True, "options": MOVIE_GENRE_OPTIONS}, {"name": "skip"}]
SERIES_GENRE_EXTRA = [{"name": "genre", "isRequired": True, "options": SERIES_GENRE_OPTIONS}, {"name": "skip"}]

HOME_CINEMA_MOVIE_IDS = [
    693134,   # Dune: Part Two
    438631,   # Dune
    335984,   # Blade Runner 2049
    157336,   # Interstellar
    76341,    # Mad Max: Fury Road
    361743,   # Top Gun: Maverick
    19995,    # Avatar
    76600,    # Avatar: The Way of Water
    27205,    # Inception
    603,      # The Matrix
    872585,   # Oppenheimer
    324857,   # Spider-Man: Into the Spider-Verse
    569094,   # Spider-Man: Across the Spider-Verse
    49026,    # The Dark Knight Rises
    155,      # The Dark Knight
    414906,   # The Batman
    530915,   # 1917
    374720,   # Dunkirk
    354912,   # Coco
    508442,   # Soul
    11,       # Star Wars
    1891,     # The Empire Strikes Back
    24428,    # The Avengers
    299534,   # Avengers: Endgame
    284054,   # Black Panther
    299536,   # Avengers: Infinity War
    634649,   # Spider-Man: No Way Home
    330459,   # Rogue One
    240832,   # Lucy
    106646,   # The Wolf of Wall Street
    120,      # The Lord of the Rings: The Fellowship of the Ring
    121,      # The Lord of the Rings: The Two Towers
    122,      # The Lord of the Rings: The Return of the King
    49051,    # The Hobbit: An Unexpected Journey
    496243,   # Parasite
    575264,   # Mission: Impossible - Dead Reckoning Part One
    562,      # Die Hard
    955,      # Mission: Impossible II
]

SAGA_COLLECTION_QUERIES = [
    "Star Wars Collection",
    "Harry Potter Collection",
    "The Lord of the Rings Collection",
    "The Hobbit Collection",
    "Dune Collection",
    "The Matrix Collection",
    "Jurassic Park Collection",
    "Avatar Collection",
    "Mission: Impossible Collection",
    "James Bond Collection",
    "Fast & Furious Collection",
    "Pirates of the Caribbean Collection",
    "Indiana Jones Collection",
    "Rocky Collection",
    "Creed Collection",
    "John Wick Collection",
    "Die Hard Collection",
    "Terminator Collection",
    "Alien Collection",
    "Predator Collection",
    "Planet of the Apes Collection",
    "Mad Max Collection",
    "Back to the Future Collection",
    "Ghostbusters Collection",
    "Men in Black Collection",
    "The Hunger Games Collection",
    "Twilight Collection",
    "The Chronicles of Narnia Collection",
    "Toy Story Collection",
    "Shrek Collection",
    "Kung Fu Panda Collection",
    "How to Train Your Dragon Collection",
    "Despicable Me Collection",
    "Ice Age Collection",
    "Cars Collection",
    "The Incredibles Collection",
    "Finding Nemo Collection",
    "Spider-Man Collection",
    "The Amazing Spider-Man Collection",
    "Deadpool Collection",
    "Guardians of the Galaxy Collection",
    "The Avengers Collection",
    "X-Men Collection",
    "Batman Collection",
    "The Dark Knight Collection",
    "Superman Collection",
    "Wonder Woman Collection",
    "Aquaman Collection",
    "Scream Collection",
    "Halloween Collection",
    "Friday the 13th Collection",
    "A Nightmare on Elm Street Collection",
    "Saw Collection",
    "Final Destination Collection",
    "The Conjuring Collection",
    "Insidious Collection",
    "Paranormal Activity Collection",
]

EXCLUDED_SERIES_GENRES = "10764,10767"  # Reality, Talk

def cache_get(key):
    # 1. Prima controlla cache in-memory (velocissima)
    e = _cache.get(key)
    if e and time.time() - e["ts"] < e.get("ttl", CACHE_TTL):
        return e["data"]
    # 2. Poi controlla Redis (persistente tra restart)
    data = redis_get_sync(f"cat:{key}")
    if data:
        _cache[key] = {"ts": time.time(), "data": data}
        return data
    return None

def cache_set(key, data, ttl=CACHE_TTL):
    _cache[key] = {"ts": time.time(), "data": data, "ttl": ttl}
    # Salva su Redis in background (non blocca la risposta)
    threading.Thread(target=redis_set_sync, args=(f"cat:{key}", data, ttl), daemon=True).start()


# ── Keep-alive ─────────────────────────────────────────────────────────────────
def keep_alive():
    while True:
        try: urllib.request.urlopen(f"{BASE_URL}/health", timeout=10)
        except: pass
        time.sleep(25 * 60)

threading.Thread(target=keep_alive, daemon=True).start()

def background_refresh():
    """Aggiorna i catalog in background ogni 5 ore."""
    if not BACKGROUND_REFRESH:
        return
    import urllib.request
    import time as time_module
    catalogs = [
        "catalog/movie/trending-movies.json",
        "catalog/movie/toprated-movies.json",
        "catalog/movie/italian-movies.json",
        "catalog/movie/similar-watchlist-movies.json",
        "catalog/movie/similar-history-movies.json",
        "catalog/movie/netflix-movies.json",
        "catalog/movie/disney-movies.json",
        "catalog/movie/prime-movies.json",
        "catalog/movie/kids-movies.json",
        "catalog/series/trending-series.json",
        "catalog/series/toprated-series.json",
        "catalog/series/italian-series.json",
        "catalog/series/similar-watchlist-series.json",
        "catalog/series/similar-history-series.json",
        "catalog/series/netflix-series.json",
        "catalog/series/disney-series.json",
        "catalog/series/prime-series.json",
        "catalog/series/kids-series.json",
        "catalog/series/kitsu-series.json",
        "catalog/series/kitsu-movies.json",
    ]
    while True:
        time_module.sleep(5 * 60 * 60)  # Ogni 5 ore
        print("[REFRESH] Aggiornamento catalog in background...")
        for cat in catalogs:
            try:
                urllib.request.urlopen(f"{BASE_URL}/{cat}", timeout=30)
            except: pass
        print("[REFRESH] Completato!")

threading.Thread(target=background_refresh, daemon=True).start()

@app.on_event("startup")
async def preload_catalogs():
    """Precarica tutti i catalog in Redis all'avvio."""
    await asyncio.sleep(2)  # Aspetta che il server sia pronto
    # Carica token Simkl da Redis all'avvio
    load_tokens()
    if not PRELOAD_CATALOGS:
        print("[PRELOAD] Disattivato. Usa /admin/refresh per riscaldare i cataloghi.")
        return
    catalog_ids = [
        ("movie", "trending-movies"),
        ("movie", "toprated-movies"),
        ("movie", "italian-movies"),
        ("movie", "similar-watchlist-movies"),
        ("movie", "similar-history-movies"),
        ("movie", "netflix-movies"),
        ("movie", "disney-movies"), ("movie", "prime-movies"),
        ("movie", "kids-movies"),
        ("series", "trending-series"), ("series", "toprated-series"),
        ("series", "italian-series"),
        ("series", "similar-watchlist-series"),
        ("series", "similar-history-series"),
        ("series", "netflix-series"), ("series", "disney-series"),
        ("series", "prime-series"), ("series", "kids-series"),
        ("series", "kitsu-series"), ("series", "kitsu-movies"),
        ("movie", "personal-movies"), ("series", "personal-series"),
    ]
    print("[PRELOAD] Avvio precaricamento catalog...")
    for media_type, catalog_id in catalog_ids:
        try:
            cache_key = f"{catalog_id}:{media_type}:1"
            if cache_get(cache_key) is None:
                async with httpx.AsyncClient(timeout=5) as c:
                    await c.get(f"{BASE_URL}/catalog/{media_type}/{catalog_id}.json")
                print(f"[PRELOAD] {catalog_id} caricato")
            else:
                print(f"[PRELOAD] {catalog_id} già in cache")
        except: pass
    print("[PRELOAD] Completato!")

# ── Redis token helpers ────────────────────────────────────────────────────────
REDIS_URL   = os.environ.get("UPSTASH_REDIS_REST_URL", "")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

def redis_get_sync(key):
    if not REDIS_URL or not REDIS_TOKEN: return None
    try:
        data = redis_command_sync(["GET", key])
        result = data.get("result") if data else None
        if result is None:
            return None
        if isinstance(result, (dict, list, int, float, bool)):
            return result
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
                if isinstance(parsed, str):
                    try:
                        return json.loads(parsed)
                    except:
                        return parsed
                return parsed
            except:
                return result
    except Exception as e:
        print(f"[REDIS GET] Errore: {e}")
    return None

def redis_command_sync(command):
    if not REDIS_URL or not REDIS_TOKEN: return None
    try:
        body = json.dumps(command).encode()
        req = urllib.request.Request(
            REDIS_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {REDIS_TOKEN}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[REDIS CMD] Errore: {e}")
    return None

def redis_set_sync(key, value, ttl=CACHE_TTL):
    if not REDIS_URL or not REDIS_TOKEN: return
    try:
        # Usa Upstash REST API con POST e body JSON
        command = ["SET", key, json.dumps(value)]
        if ttl:
            command.extend(["EX", int(ttl)])
        body = json.dumps(command).encode()
        req = urllib.request.Request(
            REDIS_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {REDIS_TOKEN}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            result = json.loads(r.read())
            return result
    except Exception as e:
        print(f"[REDIS SET] Errore: {e}")

def redis_delete_sync(key):
    return redis_command_sync(["DEL", key])

def redis_scan_delete_prefix(prefix, limit=1000):
    if not REDIS_URL or not REDIS_TOKEN:
        return 0
    deleted = 0
    cursor = "0"
    while True:
        data = redis_command_sync(["SCAN", cursor, "MATCH", f"{prefix}*", "COUNT", 100])
        result = data.get("result") if data else None
        if not result or len(result) < 2:
            break
        cursor = str(result[0])
        keys = result[1] or []
        for key in keys:
            redis_delete_sync(key)
            deleted += 1
            if deleted >= limit:
                return deleted
        if cursor == "0":
            break
    return deleted

# ── Token ──────────────────────────────────────────────────────────────────────
def load_tokens():
    # 1. Redis è la fonte persistente: sopravvive a rebuild e restart HF.
    try:
        d = redis_get_sync("simkl_tokens")
        if d:
            print("[TOKEN] Caricato da Redis")
            with open(TOKEN_FILE, "w") as f: json.dump(d, f)
            return d
        else:
            print("[TOKEN] Redis: nessun token trovato")
    except Exception as e:
        print(f"[TOKEN] Errore Redis: {e}")
    # 2. Fallback dal file locale del container
    try:
        with open(TOKEN_FILE) as f:
            d = json.load(f)
            if d: return d
    except: pass
    # 3. Infine dal Secret HF
    env = os.environ.get("SIMKL_TOKEN_JSON", "")
    if env:
        try:
            d = json.loads(env)
            with open(TOKEN_FILE, "w") as f: json.dump(d, f)
            return d
        except: pass
    return {}

def save_tokens(data):
    # Salva su file locale
    with open(TOKEN_FILE, "w") as f: json.dump(data, f)
    # Salva su Redis senza TTL: il token resta dopo rebuild/restart dello Space.
    redis_set_sync("simkl_tokens", data, ttl=None)
    print("[TOKEN] Salvato su Redis e file locale")

def token_status():
    redis_enabled = bool(REDIS_URL and REDIS_TOKEN)
    redis_tokens = redis_get_sync("simkl_tokens") if redis_enabled else None
    file_tokens = None
    try:
        with open(TOKEN_FILE) as f:
            file_tokens = json.load(f)
    except: pass
    tokens = redis_tokens or file_tokens or {}
    expires_at = tokens.get("expires_at", 0)
    return {
        "redis_enabled": redis_enabled,
        "redis_has_tokens": bool(redis_tokens),
        "file_has_tokens": bool(file_tokens),
        "has_access_token": bool(tokens.get("access_token")),
        "has_refresh_token": False,
        "expires_at": expires_at,
        "expires_in_seconds": int(expires_at - time.time()) if expires_at else None,
        "valid_now": bool(tokens.get("access_token")),
    }

def get_valid_token():
    t = load_tokens()
    if not t: return None
    return t.get("access_token")

def simkl_headers(token=None):
    h = {
        "Content-Type": "application/json",
        "simkl-api-key": SIMKL_CLIENT_ID,
        "User-Agent": f"NuvioSimklPersonal/{SIMKL_APP_VERSION}",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

# ── TMDB helper ────────────────────────────────────────────────────────────────
async def tmdb_get(path, params=None, lang="it-IT"):
    if not TMDB_API_KEY: return {}
    p = {"api_key": TMDB_API_KEY, "language": lang}
    if params: p.update(params)
    volatile = path.startswith("/discover") or path.startswith("/search") or path.startswith("/trending")
    cache_key = None
    if not volatile:
        safe_params = {k: v for k, v in p.items() if k != "api_key"}
        cache_key = f"tmdb:{lang}:{path}:{json.dumps(safe_params, sort_keys=True)}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{TMDB_BASE}{path}", params=p)
            data = r.json() if r.status_code == 200 else {}
            if cache_key and data:
                cache_set(cache_key, data, ttl=CACHE_TTL_TMDB_DETAILS)
            return data
    except: return {}

async def tmdb_get_with_fallback(path, params=None):
    """Prova in italiano, se non c'è overview prende inglese e traduce."""
    d = await tmdb_get(path, params, lang="it-IT")
    if d and not d.get("overview"):
        d_en = await tmdb_get(path, params, lang="en-US")
        if d_en and d_en.get("overview"):
            # Traduci in italiano con Claude
            d["overview"] = await translate_to_italian(d_en["overview"])
    return d

async def fetch_simkl(path, params=None, token=None):
    if not SIMKL_CLIENT_ID:
        return []
    try:
        request_params = {
            "client_id": SIMKL_CLIENT_ID,
            "app-name": SIMKL_APP_NAME,
            "app-version": SIMKL_APP_VERSION,
        }
        if params:
            request_params.update(params)
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{SIMKL_BASE}{path}", headers=simkl_headers(token), params=request_params)
            return r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"[SIMKL] {path}: {e}")
        return []

# ── Manifest ───────────────────────────────────────────────────────────────────
MANIFEST = {
    "id": "community.vito.personal.v6",
    "version": "7.9.0",
    "name": "🎬 Il Mio Addon",
    "description": "Cataloghi Simkl personali, trending, streaming provider italiani e anime.",
    "logo": "https://simkl.in/img_favicon/v2/favicon-96x96.png",
    "resources": ["catalog", "meta"],
    "types": ["movie", "series"],
    "idPrefixes": ["tt", "tmdb", "trakt", "kitsu", "mal", "anilist", "anidb"],
    "behaviorHints": {"configurable": True, "configurationRequired": False},
    "catalogs": [
        {"type": "movie",  "id": "search-movies",   "name": "🔍 Cerca",              "extra": [{"name": "search", "isRequired": True}]},
        {"type": "series", "id": "search-series",   "name": "🔍 Cerca",              "extra": [{"name": "search", "isRequired": True}]},
        {"type": "movie",  "id": "personal-movies", "name": "⭐ Consigliati per Te", "extra": [{"name": "skip"}]},
        {"type": "movie",  "id": "similar-history-movies", "name": "🧠 Simili ai Tuoi Visti", "extra": [{"name": "skip"}]},
        {"type": "movie",  "id": "after-recommendations-home-cinema-movies", "name": "⭐ Home Cinema", "extra": [{"name": "skip"}]},
        {"type": "movie",  "id": "trending-movies", "name": "📈 Di Tendenza",        "extra": [{"name": "skip"}]},
        {"type": "movie",  "id": "toprated-movies", "name": "🏆 Più Votati",         "extra": [{"name": "skip"}]},
        {"type": "movie",  "id": "italian-movies",  "name": "🇮🇹 Film Italiani",      "extra": [{"name": "skip"}]},
        {"type": "movie",  "id": "genre-movies",    "name": "🎭 Generi Film",        "extra": MOVIE_GENRE_EXTRA},
        {"type": "movie",  "id": "similar-watchlist-movies", "name": "🎯 Simili alla Watchlist", "extra": [{"name": "skip"}]},
        {"type": "movie",  "id": "netflix-movies",  "name": "🔴 Netflix",            "extra": [{"name": "skip"}]},
        {"type": "movie",  "id": "disney-movies",   "name": "🔵 Disney+",            "extra": [{"name": "skip"}]},
        {"type": "movie",  "id": "prime-movies",    "name": "🟡 Amazon Prime",       "extra": [{"name": "skip"}]},
        {"type": "movie",  "id": "kids-movies",     "name": "🧒 Bambini",            "extra": [{"name": "skip"}]},
        {"type": "movie",  "id": "nuvio-saga",      "name": "Film Saga",              "extra": [{"name": "genre"}, {"name": "skip"}]},
        {"type": "series", "id": "personal-series", "name": "⭐ Consigliate per Te", "extra": [{"name": "skip"}]},
        {"type": "series", "id": "similar-history-series", "name": "🧠 Simili ai Tuoi Visti", "extra": [{"name": "skip"}]},
        {"type": "series", "id": "trending-series", "name": "📈 Di Tendenza",        "extra": [{"name": "skip"}]},
        {"type": "series", "id": "toprated-series", "name": "🏆 Più Votate",         "extra": [{"name": "skip"}]},
        {"type": "series", "id": "italian-series",  "name": "🇮🇹 Serie Italiane",     "extra": [{"name": "skip"}]},
        {"type": "series", "id": "genre-series",    "name": "🎭 Generi Serie",       "extra": SERIES_GENRE_EXTRA},
        {"type": "series", "id": "similar-watchlist-series", "name": "🎯 Simili alla Watchlist", "extra": [{"name": "skip"}]},
        {"type": "series", "id": "netflix-series",  "name": "🔴 Netflix",            "extra": [{"name": "skip"}]},
        {"type": "series", "id": "disney-series",   "name": "🔵 Disney+",            "extra": [{"name": "skip"}]},
        {"type": "series", "id": "prime-series",    "name": "🟡 Amazon Prime",       "extra": [{"name": "skip"}]},
        {"type": "series", "id": "kids-series",     "name": "🧒 Bambini",            "extra": [{"name": "skip"}]},
        {"type": "series", "id": "kitsu-trending",  "name": "🍥 Anime Trending",     "extra": [{"name": "skip"}]},
        {"type": "series", "id": "kitsu-popular",   "name": "🍥 Anime Popolari",     "extra": [{"name": "skip"}]},
        {"type": "series", "id": "kitsu-airing",    "name": "🍥 Anime in Corso",     "extra": [{"name": "skip"}]},
        {"type": "series", "id": "kitsu-series",    "name": "🍥 Anime Serie",        "extra": [{"name": "skip"}]},
        {"type": "series", "id": "kitsu-movies",    "name": "🍥 Film Anime",         "extra": [{"name": "skip"}]},
    ],
}

# ── YouTube trailer italiano ──────────────────────────────────────────────────
async def search_youtube_trailer(title, year=None):
    """Cerca il trailer italiano su YouTube."""
    if not YOUTUBE_API_KEY: return None
    query = f"{title} trailer italiano ufficiale"
    if year: query += f" {year}"
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "key": YOUTUBE_API_KEY,
                    "q": query,
                    "part": "snippet",
                    "type": "video",
                    "maxResults": 8,
                    "relevanceLanguage": "it",
                    "videoCategoryId": "1",  # Film & Animation
                },
            )
            if r.status_code == 200:
                items = r.json().get("items", [])
                title_l = title.lower()
                bad_words = ("reaction", "recensione", "review", "spiegazione", "analisi", "clip", "scene", "scena", "ending")
                for item in items:
                    snippet = item.get("snippet", {})
                    video_title = (snippet.get("title") or "").lower()
                    channel = (snippet.get("channelTitle") or "").lower()
                    if any(bad in video_title for bad in bad_words):
                        continue
                    if "trailer" not in video_title:
                        continue
                    if title_l not in video_title and not any(word in video_title for word in title_l.split()[:2]):
                        continue
                    if "ufficial" in video_title or "official" in video_title or "trailer" in channel:
                        return f"yt_id={item['id']['videoId']}"
    except Exception as e:
        print(f"[YouTube] Errore: {e}")
    return None

def pick_tmdb_italian_trailer(videos_data):
    candidates = []
    for video in (videos_data or {}).get("results", []):
        if video.get("site") != "YouTube" or not video.get("key"):
            continue
        if (video.get("iso_639_1") or "").lower() not in ("it", "ita"):
            continue
        name = (video.get("name") or "").lower()
        vtype = video.get("type") or ""
        official = bool(video.get("official"))
        score = 0
        if vtype == "Trailer": score += 50
        if official: score += 25
        if "ufficial" in name or "italiano" in name or "ita" in name: score += 15
        if "teaser" in name: score += 5
        if any(bad in name for bad in ("clip", "featurette", "behind", "intervista", "interview", "recensione", "reaction")):
            score -= 40
        candidates.append((score, video))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return f"yt_id={candidates[0][1]['key']}"

def youtube_id_from_trailer(trailer):
    if not trailer:
        return None
    if trailer.startswith("yt_id="):
        return trailer.replace("yt_id=", "", 1)
    if trailer.startswith("yt_id:"):
        return trailer.split(":")[-1]
    return trailer

async def tmdb_catalog_trailer_yt_id(tmdb_type, tmdb_id):
    if not tmdb_id or not TMDB_API_KEY:
        return None
    trailer_cache_key = f"trailer_it_only:{tmdb_type}:{tmdb_id}"
    cached = cache_get(trailer_cache_key)
    if cached:
        return youtube_id_from_trailer(cached)
    videos = await tmdb_get(f"/{tmdb_type}/{tmdb_id}/videos")
    trailer = pick_tmdb_italian_trailer(videos)
    if trailer:
        cache_set(trailer_cache_key, trailer, ttl=14 * 24 * 60 * 60)
    return youtube_id_from_trailer(trailer)

# ── AI search ──────────────────────────────────────────────────────────────────────
async def ai_expand_query(query):
    q = query.lower().strip()
    t = {
        "viaggi spaziali": "space travel", "spazio": "space", "astronauta": "astronaut",
        "alieni": "alien", "ufo": "ufo", "guerra": "war",
        "seconda guerra mondiale": "world war 2", "mafia": "mafia",
        "crimine": "crime", "polizia": "police", "detective": "detective",
        "supereroi": "superhero", "amore": "romance", "romantico": "romance",
        "horror": "horror", "zombie": "zombie", "fantasy": "fantasy",
        "draghi": "dragon", "magia": "magic", "robot": "robot",
        "dinosauri": "dinosaur", "pirati": "pirates", "sopravvivenza": "survival",
        "rapina": "heist", "spia": "spy", "vampiri": "vampire",
        "animazione": "animation", "documentario": "documentary",
        "sport": "sport", "calcio": "football", "carcere": "prison",
        "avventura": "adventure", "mistero": "mystery", "psicologico": "psychological",
        "famiglia": "family", "bambini": "children", "futuro": "future",
        "distopico": "dystopian", "apocalisse": "apocalypse", "viaggio nel tempo": "time travel",
    }
    keywords = []
    for it, en in t.items():
        if it in q:
            keywords.append(en)
            q = q.replace(it, "")
    if keywords:
        return " ".join(keywords[:3])
    return query

# ── Catalog helpers ────────────────────────────────────────────────────────────
def trakt_to_meta(obj, media_type):
    ids = obj.get("ids", {})
    imdb = ids.get("imdb", "")
    tmdb = ids.get("tmdb")
    sid = imdb if imdb else (f"tmdb:{tmdb}" if tmdb else f"trakt:{ids.get('slug','')}")
    return {
        "id": sid,
        "type": media_type,
        "name": obj.get("title", ""),
        "year": obj.get("year"),
        "poster": None,
        "background": None,
        # Niente description da Trakt - verrà presa da TMDB in italiano
        "_tmdb": tmdb,
    }

async def enrich_poster(meta):
    tmdb_id = meta.pop("_tmdb", None)
    if not tmdb_id or not TMDB_API_KEY: return meta
    tmdb_type = "movie" if meta["type"] == "movie" else "tv"
    meta_cache_key = f"enriched:{tmdb_type}:{tmdb_id}"
    cached = cache_get(meta_cache_key)
    if cached is not None:
        meta.update(cached)
        return meta
    d = await tmdb_get_with_fallback(f"/{tmdb_type}/{tmdb_id}")
    if d:
        enriched = {}
        if d.get("poster_path"): meta["poster"] = f"{TMDB_POSTER}{d['poster_path']}"
        if d.get("backdrop_path"): meta["background"] = f"{TMDB_ORIG}{d['backdrop_path']}"
        # Usa sempre titolo e trama da TMDB (in italiano)
        if d.get("overview"): meta["description"] = d["overview"]
        else: meta.pop("description", None)
        if d.get("title"): meta["name"] = d["title"]
        elif d.get("name"): meta["name"] = d["name"]
        trailer_yt_id = await tmdb_catalog_trailer_yt_id(tmdb_type, tmdb_id)
        if trailer_yt_id:
            meta["trailers"] = [{"source": trailer_yt_id, "type": "Trailer"}]
            meta["trailerStreams"] = [{"ytId": trailer_yt_id}]
            meta["trailer"] = trailer_yt_id
        for key in ("poster", "background", "description", "name", "trailers", "trailerStreams", "trailer"):
            if meta.get(key):
                enriched[key] = meta[key]
        if enriched:
            cache_set(meta_cache_key, enriched, ttl=CACHE_TTL_TMDB_DETAILS)
    return meta

async def build_catalog_from_trakt(items, media_type):
    async def process(item):
        obj = item.get("movie") or item.get("show") or item
        m = trakt_to_meta(obj, media_type)
        return await enrich_poster(m)
    # Processa in batch più ampi: TMDB è cacheato e le griglie si aprono prima.
    results = []
    for i in range(0, len(items), 20):
        batch = items[i:i+20]
        batch_results = await asyncio.gather(*[process(item) for item in batch], return_exceptions=True)
        results.extend([m for m in batch_results if isinstance(m, dict)])
    return dedupe_metas(results)

def slice_items(items, skip=0, limit=100):
    return items[skip:skip + limit]

def ids_from_trakt_item(item):
    obj = item.get("movie") or item.get("show") or item
    ids = obj.get("ids", {}) if isinstance(obj, dict) else {}
    values = set()
    if ids.get("imdb"):
        values.add(ids["imdb"])
    if ids.get("tmdb"):
        values.add(f"tmdb:{ids['tmdb']}")
    return values

def ids_from_simkl_item(item):
    obj = item.get("movie") or item.get("show") or item
    ids = obj.get("ids", {}) if isinstance(obj, dict) else {}
    values = set()
    if ids.get("imdb"):
        values.add(str(ids["imdb"]))
    if ids.get("tmdb"):
        values.add(f"tmdb:{ids['tmdb']}")
    return values

def simkl_to_meta(obj, media_type):
    ids = obj.get("ids", {})
    imdb = ids.get("imdb", "")
    tmdb = ids.get("tmdb")
    simkl_id = ids.get("simkl", "")
    sid = imdb if imdb else (f"tmdb:{tmdb}" if tmdb else f"simkl:{simkl_id}")
    return {"id": sid, "type": media_type, "name": obj.get("title", ""),
            "year": obj.get("year"), "poster": None, "background": None, "_tmdb": tmdb}

async def build_catalog_from_simkl(items, media_type):
    async def process(item):
        obj = item.get("movie") or item.get("show") or item
        return await enrich_poster(simkl_to_meta(obj, media_type))
    results = []
    for i in range(0, len(items), 20):
        batch_results = await asyncio.gather(*[process(x) for x in items[i:i+20]], return_exceptions=True)
        results.extend([m for m in batch_results if isinstance(m, dict)])
    return dedupe_metas(results)

async def simkl_items(media_type, status, token, force_refresh=False):
    simkl_type = "movies" if media_type == "movie" else "shows"
    cache_key = f"simkl:{simkl_type}:{status}"
    cached = None if force_refresh else cache_get(cache_key)
    if cached is not None:
        return cached
    # Simkl richiede di consultare prima le attivita' quando si sincronizzano le liste.
    await fetch_simkl("/sync/activities", token=token)
    data = await fetch_simkl(f"/sync/all-items/{simkl_type}/{status}", token=token)
    if isinstance(data, dict):
        items = data.get(simkl_type, []) or data.get("movies" if simkl_type == "movies" else "shows", [])
    else:
        items = data if isinstance(data, list) else []
    cache_set(cache_key, items, ttl=CACHE_TTL_WATCHED)
    return items

async def get_watched_ids(media_type, token, force_refresh=False):
    if not HIDE_WATCHED or not token:
        return set()
    tt = "movies" if media_type == "movie" else "shows"
    cache_key = f"watched_ids:{media_type}"
    cached = None if force_refresh else cache_get(cache_key)
    if cached is not None:
        return set(cached)
    watched = await simkl_items(media_type, "completed", token, force_refresh=force_refresh)
    ids = set()
    for item in watched:
        ids.update(ids_from_simkl_item(item))
    cache_set(cache_key, list(ids), ttl=CACHE_TTL_WATCHED)
    return ids

def hide_watched_metas(metas, watched_ids):
    if not watched_ids:
        return metas
    return [m for m in metas if m.get("id") not in watched_ids]

def dedupe_metas(metas):
    seen = set()
    unique = []
    for meta in metas or []:
        if not isinstance(meta, dict):
            continue
        key = meta.get("id") or "|".join([
            str(meta.get("type") or ""),
            str(meta.get("name") or "").strip().lower(),
            str(meta.get("poster") or ""),
        ])
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(meta)
    return unique

def catalog_ttl(catalog_id):
    if "trending" in catalog_id or "popular" in catalog_id:
        return CACHE_TTL_TRENDING
    if catalog_id in ("personal-movies", "personal-series"):
        return CACHE_TTL_PERSONAL
    return CACHE_TTL

def is_tmdb_result_valid(item, media_type, strict=True):
    if not item or not item.get("poster_path"):
        return False
    vote_count = item.get("vote_count") or 0
    vote_average = item.get("vote_average") or 0
    if strict and vote_count < MIN_VOTE_COUNT:
        return False
    if MIN_RATING and vote_average < MIN_RATING:
        return False
    if ONLY_RELEASED:
        release = item.get("release_date") or item.get("first_air_date") or ""
        if release and release > time.strftime("%Y-%m-%d"):
            return False
    if EXCLUDE_REALITY and media_type == "series":
        genres = set(item.get("genre_ids") or [])
        if 10764 in genres or 10767 in genres:
            return False
    return True

def filter_tmdb_results(items, media_type, strict=True, exclude_languages=False):
    seen = set()
    filtered = []
    for item in items:
        tmdb_id = item.get("id")
        if not tmdb_id or tmdb_id in seen:
            continue
        seen.add(tmdb_id)
        if exclude_languages and media_type == "movie" and (item.get("original_language") or "").lower() in EXCLUDED_GENRE_LANGUAGES:
            continue
        if is_tmdb_result_valid(item, media_type, strict=strict):
            filtered.append(item)
    return sort_tmdb_results(filtered, media_type)

def tmdb_year(item):
    date = item.get("release_date") or item.get("first_air_date") or ""
    try:
        return int(date[:4])
    except:
        return 0

def score_tmdb_item(item, media_type):
    popularity = float(item.get("popularity") or 0)
    rating = float(item.get("vote_average") or 0)
    votes = float(item.get("vote_count") or 0)
    year = tmdb_year(item)
    language = (item.get("original_language") or "").lower()
    current_year = int(time.strftime("%Y"))
    recency = max(0, min(10, current_year - year if year else 10))
    recency_score = 10 - recency
    italian_bonus = 1.0 if item.get("original_language") == "it" else 0
    language_bonus = 0.8 if language in PREFERRED_DISCOVERY_LANGUAGES else -1.5
    if media_type == "movie" and language in EXCLUDED_GENRE_LANGUAGES:
        language_bonus -= 4
    quality_bonus = 2.5 if votes >= 1000 and rating >= 7 else 0
    return (
        (rating * 2.2)
        + min(votes / 220, 10)
        + min(popularity / 35, 8)
        + (recency_score * 0.25)
        + italian_bonus
        + language_bonus
        + quality_bonus
    )

def sort_tmdb_results(items, media_type):
    return sorted(items, key=lambda item: score_tmdb_item(item, media_type), reverse=True)

def score_genre_item(item, media_type):
    popularity = float(item.get("popularity") or 0)
    rating = float(item.get("vote_average") or 0)
    votes = float(item.get("vote_count") or 0)
    year = tmdb_year(item)
    language = (item.get("original_language") or "").lower()
    current_year = int(time.strftime("%Y"))
    age = max(0, current_year - year) if year else 30
    classic_bonus = 2.0 if votes >= 1000 and rating >= 7 else 0
    language_bonus = 1.8 if language in ("en", "it") else 0.5 if language in ("fr", "es", "de", "ja", "ko") else -2.8
    if media_type == "movie" and language in EXCLUDED_GENRE_LANGUAGES:
        language_bonus -= 5
    recency_penalty = 1.5 if age <= 1 and votes < 180 else 0
    low_confidence_penalty = 2.0 if votes < 120 else 0
    return (
        rating * 2.6
        + min(votes / 180, 18)
        + min(popularity / 30, 10)
        + classic_bonus
        + language_bonus
        - recency_penalty
        - low_confidence_penalty
    )

def sort_genre_results(items, media_type):
    return sorted(items, key=lambda item: score_genre_item(item, media_type), reverse=True)

async def build_filtered_tmdb_catalog(results, media_type, watched_ids=None, strict=True):
    filtered = filter_tmdb_results(results, media_type, strict=strict)
    metas = await build_catalog_from_tmdb(filtered, media_type)
    return hide_watched_metas(metas, watched_ids or set())

async def build_home_cinema_catalog(skip=0, limit=20, watched_ids=None):
    ids = HOME_CINEMA_MOVIE_IDS[skip:skip + limit]
    if not ids:
        return []

    async def fetch_movie(tmdb_id):
        data = await tmdb_get_with_fallback(f"/movie/{tmdb_id}")
        if not data or not data.get("id"):
            return None
        return data

    results = await asyncio.gather(*[fetch_movie(tmdb_id) for tmdb_id in ids], return_exceptions=True)
    movies = [item for item in results if isinstance(item, dict)]
    metas = await build_catalog_from_tmdb(movies, "movie")
    return hide_watched_metas(metas, watched_ids or set())

def genre_key_from_catalog(catalog_id):
    for key in GENRE_CATALOGS:
        if catalog_id.startswith(f"genre-{key}-"):
            return key
    return None

def genre_key_from_extra(genre):
    if not genre:
        return None
    normalized = urllib.parse.unquote(str(genre)).strip().lower()
    for key, info in GENRE_CATALOGS.items():
        if normalized in (key.lower(), info["name"].lower()):
            return key
    return None

def filter_tmdb_results_by_genre(items, genre_id, media_type="movie"):
    required = str(genre_id or "").strip()
    if not required:
        return items
    filtered = []
    for item in items or []:
        if media_type == "movie" and (item.get("original_language") or "").lower() in EXCLUDED_GENRE_LANGUAGES:
            continue
        genres = {str(value) for value in (item.get("genre_ids") or [])}
        if required in genres:
            filtered.append(item)
    return filtered

async def tmdb_discover_genre_results(media_type, genre_id, skip, limit, watched_ids=None):
    tmdb_t = "movie" if media_type == "movie" else "tv"
    collected = []
    seen = set()
    watched_ids = watched_ids or set()
    target_count = max(limit, skip + limit)
    max_pages = min(120, max(8, (target_count // 8) + 8))
    for start_page in range(1, max_pages + 1, 4):
        page_numbers = list(range(start_page, min(start_page + 4, max_pages + 1)))
        page_results = await asyncio.gather(*[
            tmdb_get(f"/discover/{tmdb_t}", tmdb_discover_params(media_type, tmdb_page, {
                "with_genres": genre_id,
                "without_original_language": "|".join(sorted(EXCLUDED_GENRE_LANGUAGES)) if media_type == "movie" else "",
                "sort_by": "popularity.desc",
                "vote_count.gte": 80 if media_type == "movie" else MIN_VOTE_COUNT,
            }))
            for tmdb_page in page_numbers
        ], return_exceptions=True)
        had_raw = False
        for data in page_results:
            if not isinstance(data, dict):
                continue
            raw = data.get("results", [])
            had_raw = had_raw or bool(raw)
            results = filter_tmdb_results_by_genre(raw, genre_id, media_type)
            for item in results:
                tmdb_id = item.get("id")
                if not tmdb_id or tmdb_id in seen:
                    continue
                if not is_tmdb_result_valid(item, media_type, strict=True):
                    continue
                if f"tmdb:{tmdb_id}" in watched_ids:
                    continue
                seen.add(tmdb_id)
                collected.append(item)
        if len(collected) >= target_count or not had_raw:
            break
    ranked = sort_genre_results(collected, media_type)
    return ranked[skip:skip + limit]

async def tmdb_collect_filtered_results(media_type, skip, limit, fetch_page, strict=True, watched_ids=None, exclude_languages=False):
    collected = []
    seen = set()
    watched_ids = watched_ids or set()
    target_count = max(limit, skip + limit)
    max_pages = min(120, max(8, (target_count // 8) + 8))
    for start_page in range(1, max_pages + 1, 4):
        page_numbers = list(range(start_page, min(start_page + 4, max_pages + 1)))
        page_results = await asyncio.gather(
            *[fetch_page(tmdb_page) for tmdb_page in page_numbers],
            return_exceptions=True
        )
        had_raw = False
        for data in page_results:
            if not isinstance(data, dict):
                continue
            raw = data.get("results", [])
            had_raw = had_raw or bool(raw)
            results = filter_tmdb_results(raw, media_type, strict=strict, exclude_languages=exclude_languages)
            for item in results:
                tmdb_id = item.get("id")
                if not tmdb_id or tmdb_id in seen:
                    continue
                if f"tmdb:{tmdb_id}" in watched_ids:
                    continue
                seen.add(tmdb_id)
                collected.append(item)
        if len(collected) >= target_count or not had_raw:
            break
    ranked = sort_tmdb_results(collected, media_type)
    return ranked[skip:skip + limit]

def tmdb_discover_params(media_type, page, extra=None):
    params = {
        "sort_by": "popularity.desc",
        "page": page,
        "watch_region": "IT",
        "vote_count.gte": MIN_VOTE_COUNT,
    }
    if MIN_RATING:
        params["vote_average.gte"] = MIN_RATING
    if EXCLUDE_REALITY and media_type == "series":
        params["without_genres"] = EXCLUDED_SERIES_GENRES
    if ONLY_RELEASED:
        today = time.strftime("%Y-%m-%d")
        if media_type == "movie":
            params["release_date.lte"] = today
        else:
            params["first_air_date.lte"] = today
    if extra:
        params.update(extra)
    return params

def tmdb_type_for(media_type):
    return "movie" if media_type == "movie" else "tv"

async def tmdb_recommendations_for_trakt_items(items, media_type, watched_ids, page=1):
    tmdb_type = tmdb_type_for(media_type)
    collected = []
    seen = set()
    offset = max(0, (page - 1) * 2)
    seeds = items[offset:offset + 2]
    for item in seeds:
        for id_value in ids_from_trakt_item(item):
            if not id_value.startswith("tmdb:"):
                continue
            tmdb_id = id_value.split(":", 1)[1]
            data = await tmdb_get(f"/{tmdb_type}/{tmdb_id}/recommendations", {"page": 1})
            if not data.get("results"):
                data = await tmdb_get(f"/{tmdb_type}/{tmdb_id}/similar", {"page": 1})
            for result in data.get("results", [])[:8]:
                rid = result.get("id")
                if rid and rid not in seen:
                    seen.add(rid)
                    collected.append(result)
    return await build_filtered_tmdb_catalog(collected, media_type, watched_ids)

async def tmdb_recommendations_for_simkl_items(items, media_type, watched_ids, page=1):
    tmdb_type = tmdb_type_for(media_type)
    collected, seen = [], set()
    offset = max(0, (page - 1) * 2)
    for item in items[offset:offset + 2]:
        for id_value in ids_from_simkl_item(item):
            if not id_value.startswith("tmdb:"):
                continue
            tmdb_id = id_value.split(":", 1)[1]
            data = await tmdb_get(f"/{tmdb_type}/{tmdb_id}/recommendations", {"page": 1})
            if not data.get("results"):
                data = await tmdb_get(f"/{tmdb_type}/{tmdb_id}/similar", {"page": 1})
            for result in data.get("results", [])[:8]:
                rid = result.get("id")
                if rid and rid not in seen:
                    seen.add(rid)
                    collected.append(result)
    return await build_filtered_tmdb_catalog(collected, media_type, watched_ids)

async def personalized_similar_catalog(catalog_id, media_type, token, watched_ids, page, force_refresh=False):
    if not token:
        return []
    source = "watchlist" if "watchlist" in catalog_id else "watched"
    cache_key = f"source:{source}:{media_type}"
    items = None if force_refresh else cache_get(cache_key)
    if items is None:
        items = await simkl_items(media_type, "plantowatch" if source == "watchlist" else "completed", token, force_refresh)
        cache_set(cache_key, items, ttl=CACHE_TTL_PERSONAL_FAST if source == "watchlist" else CACHE_TTL_WATCHED)
    return await tmdb_recommendations_for_simkl_items(items or [], media_type, watched_ids, page=page)

async def get_imdb_id(tmdb_id, tmdb_type):
    cache_key = f"imdb:{tmdb_type}:{tmdb_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{TMDB_BASE}/{tmdb_type}/{tmdb_id}/external_ids",
                          params={"api_key": TMDB_API_KEY})
            if r.status_code == 200:
                imdb_id = r.json().get("imdb_id", "")
                cache_set(cache_key, imdb_id, ttl=CACHE_TTL_TMDB_DETAILS)
                return imdb_id
    except: pass
    return ""

async def build_sagas_catalog(skip=0, limit=40, watched_ids=None):
    """Crea un catalogo di film appartenenti a saghe usando TMDb Collections."""
    watched_ids = watched_ids or set()
    all_cache_key = f"{CACHE_VERSION}:sagas-movies:all"
    all_results = cache_get(all_cache_key)

    if all_results is None:
        async def find_collection(query):
            data = await tmdb_get("/search/collection", {"query": query, "page": 1}, lang="it-IT")
            results = data.get("results", [])
            if not results:
                data = await tmdb_get("/search/collection", {"query": query, "page": 1}, lang="en-US")
                results = data.get("results", [])
            return results[0].get("id") if results else None

        collection_ids = await asyncio.gather(
            *[find_collection(query) for query in SAGA_COLLECTION_QUERIES],
            return_exceptions=True,
        )
        valid_ids = []
        seen_collections = set()
        for collection_id in collection_ids:
            if isinstance(collection_id, int) and collection_id not in seen_collections:
                seen_collections.add(collection_id)
                valid_ids.append(collection_id)

        collection_data = await asyncio.gather(
            *[tmdb_get(f"/collection/{collection_id}", lang="it-IT") for collection_id in valid_ids],
            return_exceptions=True,
        )

        all_results = []
        seen_movies = set()
        for data in collection_data:
            if not isinstance(data, dict):
                continue
            parts = sorted(
                data.get("parts", []),
                key=lambda movie: (movie.get("release_date") or "9999-99-99", movie.get("id") or 0),
            )
            for movie in parts:
                tmdb_id = movie.get("id")
                if not tmdb_id or tmdb_id in seen_movies:
                    continue
                if not is_tmdb_result_valid(movie, "movie", strict=False):
                    continue
                seen_movies.add(tmdb_id)
                all_results.append(movie)

        cache_set(all_cache_key, all_results, ttl=24 * 60 * 60)

    page_results = slice_items(all_results, skip=skip, limit=limit)
    metas = await build_catalog_from_tmdb(page_results, "movie")
    return hide_watched_metas(metas, watched_ids)


def is_saga_part_valid(movie):
    if not movie or not movie.get("id") or not movie.get("poster_path"):
        return False
    title = (movie.get("title") or movie.get("name") or movie.get("original_title") or "").lower()
    bad_words = (
        "making of", "behind the scenes", "backstage", "reunion", "documentary",
        "documentario", "special", "speciale", "featurette", "retrospective",
        "interview", "intervista", "clip", "trailer"
    )
    if any(word in title for word in bad_words):
        return False
    return True

def load_nuvio_collection_files():
    collections = []
    for filename in ("nuvio-film-saga-collection.json", "nuvio-marvel-collection.json"):
        try:
            with open(os.path.join(os.path.dirname(__file__), filename), "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                collections.extend(data)
        except FileNotFoundError:
            continue
        except Exception as e:
            print(f"[NUVIO] {filename} non leggibile: {e}")
    return collections

def nuvio_saga_source_ids(catalog_id):
    try:
        collections = load_nuvio_collection_files()
    except Exception as e:
        print(f"[NUVIO SAGA] JSON non leggibili: {e}")
        return [], []
    if catalog_id == "nuvio-saga":
        collection_ids = []
        movie_ids = []
        seen_collections = set()
        seen_movies = set()
        for collection in collections:
            for folder in collection.get("folders", []):
                direct_ids = folder.get("tmdbCollectionIds")
                if isinstance(direct_ids, list):
                    for item in direct_ids:
                        if isinstance(item, int) and item not in seen_collections:
                            seen_collections.add(item)
                            collection_ids.append(item)
                direct_id = folder.get("tmdbCollectionId")
                if isinstance(direct_id, int) and direct_id not in seen_collections:
                    seen_collections.add(direct_id)
                    collection_ids.append(direct_id)
                movie_list = folder.get("tmdbMovieIds")
                if isinstance(movie_list, list):
                    for item in movie_list:
                        if isinstance(item, int) and item not in seen_movies:
                            seen_movies.add(item)
                            movie_ids.append(item)
                for source in folder.get("sources", []):
                    if str(source.get("provider", "")).lower() == "tmdb" and isinstance(source.get("tmdbId"), int):
                        tmdb_id = source.get("tmdbId")
                        if tmdb_id not in seen_collections:
                            seen_collections.add(tmdb_id)
                            collection_ids.append(tmdb_id)
        return collection_ids, movie_ids
    for collection in collections:
        for folder in collection.get("folders", []):
            expected_catalog_id = f"nuvio-{folder.get('id')}"
            if expected_catalog_id == catalog_id:
                movie_ids = folder.get("tmdbMovieIds")
                direct_ids = folder.get("tmdbCollectionIds")
                if isinstance(direct_ids, list):
                    return (
                        [item for item in direct_ids if isinstance(item, int)],
                        [item for item in movie_ids if isinstance(item, int)] if isinstance(movie_ids, list) else [],
                    )
                if isinstance(movie_ids, list):
                    return [], [item for item in movie_ids if isinstance(item, int)]
                direct_id = folder.get("tmdbCollectionId")
                if isinstance(direct_id, int):
                    return [direct_id], [item for item in movie_ids if isinstance(item, int)] if isinstance(movie_ids, list) else []
                for source in folder.get("sources", []):
                    if str(source.get("provider", "")).lower() == "tmdb" and source.get("tmdbId"):
                        return [source.get("tmdbId")], []
    return [], []

async def build_nuvio_saga_catalog(catalog_id, skip=0, limit=100):
    collection_ids, movie_ids = nuvio_saga_source_ids(catalog_id)
    if not collection_ids and not movie_ids:
        return []
    cache_key = f"{CACHE_VERSION}:{catalog_id}:release-asc"
    all_results = cache_get(cache_key)
    if all_results is None:
        collection_responses = await asyncio.gather(
            *[tmdb_get(f"/collection/{collection_id}", lang="it-IT") for collection_id in collection_ids],
            return_exceptions=True,
        ) if collection_ids else []
        movie_responses = await asyncio.gather(
            *[tmdb_get(f"/movie/{movie_id}", lang="it-IT") for movie_id in movie_ids],
            return_exceptions=True,
        ) if movie_ids else []
        parts = []
        for data in collection_responses:
            if isinstance(data, dict):
                parts.extend(data.get("parts", []))
        for data in movie_responses:
            if isinstance(data, dict) and data.get("id"):
                parts.append(data)
        seen = set()
        all_results = []
        for movie in sorted(parts, key=lambda item: (item.get("release_date") or "9999-99-99", item.get("id") or 0)):
            tmdb_id = movie.get("id")
            if not tmdb_id or tmdb_id in seen:
                continue
            seen.add(tmdb_id)
            if is_saga_part_valid(movie):
                all_results.append(movie)
        cache_set(cache_key, all_results, ttl=24 * 60 * 60)
    return await build_catalog_from_tmdb(slice_items(all_results, skip=skip, limit=limit), "movie")


async def build_catalog_from_tmdb(results, media_type, include_trailers=None):
    if include_trailers is None:
        include_trailers = CATALOG_TRAILERS
    tmdb_type = "movie" if media_type == "movie" else "tv"
    async def process(item):
        tmdb_id = item.get("id")
        imdb_id = "" if FAST_CATALOGS else await get_imdb_id(tmdb_id, tmdb_type)
        sid = imdb_id if imdb_id else f"tmdb:{tmdb_id}"
        release_date = (item.get("release_date") or item.get("first_air_date") or "").strip()
        release_year = release_date[:4] if len(release_date) >= 4 else ""
        meta = {
            "id": sid, "type": media_type,
            "name": item.get("title") or item.get("name", ""),
            "poster": f"{TMDB_POSTER}{item['poster_path']}" if item.get("poster_path") else None,
            "background": f"{TMDB_ORIG}{item['backdrop_path']}" if item.get("backdrop_path") else None,
        }
        if release_year:
            meta["year"] = int(release_year) if release_year.isdigit() else release_year
            meta["releaseInfo"] = release_year
        if release_date:
            meta["released"] = f"{release_date}T00:00:00.000Z"
        if include_trailers:
            trailer_yt_id = await tmdb_catalog_trailer_yt_id(tmdb_type, tmdb_id)
            if trailer_yt_id:
                meta["trailers"] = [{"source": trailer_yt_id, "type": "Trailer"}]
                meta["trailerStreams"] = [{"ytId": trailer_yt_id}]
                meta["trailer"] = trailer_yt_id
        return meta
    results2 = await asyncio.gather(*[process(i) for i in results], return_exceptions=True)
    return dedupe_metas([m for m in results2 if isinstance(m, dict)])


async def kitsu_get(path, params=None):
    """Fetch da API Kitsu per anime"""
    try:
        p = {"page[limit]": 20}
        if params: p.update(params)
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"https://kitsu.io/api/edge{path}",
                           params=p,
                           headers={"Accept": "application/vnd.api+json"})
            return r.json() if r.status_code == 200 else {}
    except: return {}

async def kitsu_to_meta(item):
    """Converte un item Kitsu in meta Stremio con poster TMDB"""
    attrs = item.get("attributes") or {}
    kitsu_id = item.get("id", "")
    if not attrs: return meta if 'meta' in dir() else {}
    titles = attrs.get("titles") or {}
    name = (titles.get("it") or titles.get("en") or titles.get("en_jp") or attrs.get("canonicalTitle", ""))
    poster_img = attrs.get("posterImage") or {}
    poster = poster_img.get("large") or poster_img.get("original")
    # Cerca poster migliore su TMDB
    if name and TMDB_API_KEY:
        tmdb = await tmdb_get("/search/tv", {"query": name})
        if tmdb.get("results"):
            r = tmdb["results"][0]
            if r.get("poster_path"): poster = f"{TMDB_POSTER}{r['poster_path']}"
    return {
        "id": f"kitsu:{kitsu_id}",
        "type": "series",
        "name": name,
        "poster": poster,
    }


async def anilist_search(query, page=1, per_page=20):
    """Cerca anime su AniList tramite GraphQL"""
    gql = """
    query ($search: String, $page: Int, $perPage: Int) {
        Page(page: $page, perPage: $perPage) {
            media(search: $search, type: ANIME, sort: [SEARCH_MATCH, POPULARITY_DESC]) {
                id
                idMal
                title { romaji english native }
                description(asHtml: false)
                coverImage { large extraLarge }
                bannerImage
                averageScore
                startDate { year }
                status
                genres
            }
        }
    }
    """
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post("https://graphql.anilist.co",
                json={"query": gql, "variables": {"search": query, "page": page, "perPage": per_page}},
                headers={"Content-Type": "application/json", "Accept": "application/json"})
            if r.status_code == 200:
                return r.json().get("data", {}).get("Page", {}).get("media", [])
    except: pass
    return []

async def anilist_to_meta(item):
    """Converte un item AniList in meta Stremio"""
    titles = item.get("title", {})
    name = titles.get("english") or titles.get("romaji") or titles.get("native") or ""
    mal_id = item.get("idMal")
    # Cerca su TMDB per trama italiana
    poster = item.get("coverImage", {}).get("extraLarge") or item.get("coverImage", {}).get("large")
    background = item.get("bannerImage")
    description = (item.get("description") or "").replace("<br>", " ").replace("<i>", "").replace("</i>", "")
    if name and TMDB_API_KEY:
        tmdb = await tmdb_get("/search/tv", {"query": name})
        if tmdb.get("results"):
            tmdb_d = await tmdb_get_with_fallback(
                f"/tv/{tmdb['results'][0]['id']}",
                {"append_to_response": "translations,alternative_titles"},
            )
            if tmdb_d:
                localized_name = pick_tmdb_italian_title(tmdb_d, name)
                if localized_name:
                    name = localized_name
                if tmdb_d.get("overview"):
                    description = tmdb_d["overview"]
                if tmdb_d.get("poster_path"):
                    poster = f"{TMDB_POSTER}{tmdb_d['poster_path']}"
                if tmdb_d.get("backdrop_path"):
                    background = f"{TMDB_ORIG}{tmdb_d['backdrop_path']}"
    description = await ensure_anime_description_italian(description, f"anilist:{item.get('id', '')}")
    year = item.get("startDate", {}).get("year") or ""
    rating = item.get("averageScore")
    # Usa kitsu: come ID (riconosciuto da Stremio)
    # Prima cerca su Kitsu tramite MAL id
    kitsu_id = None
    if mal_id:
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"https://kitsu.io/api/edge/anime?filter[malId]={mal_id}",
                               headers={"Accept": "application/vnd.api+json"})
                if r.status_code == 200:
                    kdata = r.json().get("data", [])
                    if kdata: kitsu_id = kdata[0].get("id")
        except: pass
    sid = f"kitsu:{kitsu_id}" if kitsu_id else f"kitsu:{item['id']}"
    return {
        "id": sid,
        "type": "series",
        "name": name,
        "description": description,
        "poster": poster,
        "background": background,
        "releaseInfo": str(year) if year else "",
        "imdbRating": str(round(rating/10, 1)) if rating else None,
        "genres": item.get("genres", []) + ["Anime"],
    }


def split_translation_chunks(text: str, max_len: int = 450):
    chunks = []
    remaining = text.strip()
    while len(remaining) > max_len:
        split_at = max(
            remaining.rfind(". ", 0, max_len),
            remaining.rfind("! ", 0, max_len),
            remaining.rfind("? ", 0, max_len),
            remaining.rfind(" ", 0, max_len),
        )
        if split_at < 80:
            split_at = max_len
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks

def looks_english(text: str) -> bool:
    if not text:
        return False
    lower = f" {text.lower()} "
    english_markers = (
        " the ", " and ", " with ", " from ", " into ", " after ", " before ",
        " when ", " while ", " their ", " his ", " her ", " she ", " he ",
        " they ", " them ", " must ", " will ", " has ", " have ", " is ",
        " are ", " becomes ", " discovers ", " fight ", " world ",
    )
    return sum(1 for marker in english_markers if marker in lower) >= 3

def translation_failed(original: str, translated: str) -> bool:
    if not translated:
        return True
    original_clean = " ".join((original or "").split()).lower()
    translated_clean = " ".join(translated.split()).lower()
    if original_clean == translated_clean:
        return True
    return looks_english(translated) and not looks_italian(translated)

async def translate_with_google_free(text: str) -> str:
    if not text or len(text) < 10:
        return text
    translated_parts = []
    async with httpx.AsyncClient(timeout=8) as c:
        for chunk in split_translation_chunks(text):
            params = {"client": "gtx", "sl": "en", "tl": "it", "dt": "t", "q": chunk}
            r = await c.get("https://translate.googleapis.com/translate_a/single", params=params)
            if r.status_code != 200:
                translated_parts.append(chunk)
                continue
            data = r.json()
            translated = "".join(part[0] for part in data[0] if part and part[0])
            translated_parts.append(translated or chunk)
    return " ".join(translated_parts)

async def translate_to_italian(text: str) -> str:
    """Traduce il testo in italiano con fallback se il primo provider lascia inglese."""
    if not text or len(text) < 10:
        return text
    mymemory_text = text
    try:
        translated_parts = []
        async with httpx.AsyncClient(timeout=10) as c:
            for chunk in split_translation_chunks(text, max_len=500):
                params = {"q": chunk, "langpair": "en|it"}
                r = await c.get("https://api.mymemory.translated.net/get", params=params)
                if r.status_code == 200:
                    data = r.json()
                    t = data.get("responseData", {}).get("translatedText", "")
                    if t and t != chunk:
                        translated_parts.append(t)
                    else:
                        translated_parts.append(chunk)
                else:
                    translated_parts.append(chunk)
        mymemory_text = " ".join(translated_parts)
    except: pass
    if not translation_failed(text, mymemory_text):
        return mymemory_text
    try:
        google_text = await translate_with_google_free(text)
        if not translation_failed(text, google_text):
            return google_text
    except: pass
    return mymemory_text

def looks_italian(text: str) -> bool:
    if not text:
        return True
    lower = f" {text.lower()} "
    italian_markers = (" il ", " lo ", " la ", " gli ", " le ", " un ", " una ", " che ", " per ", " con ", " non ", " dal ", " della ", " degli ")
    if any(ch in text for ch in "àèéìòùÀÈÉÌÒÙ"):
        return True
    return sum(1 for marker in italian_markers if marker in lower) >= 3

async def translate_anime_description(text: str, cache_key: str = None) -> str:
    if not text or looks_italian(text):
        return text
    if cache_key:
        cached = cache_get(f"{ANIME_DESC_CACHE_PREFIX}:{cache_key}")
        if cached and not looks_english(cached):
            return cached
    translated = await translate_to_italian(text)
    if cache_key and translated:
        cache_set(f"{ANIME_DESC_CACHE_PREFIX}:{cache_key}", translated, ttl=30 * 24 * 60 * 60)
    return translated

async def anime_description_cached_or_blank(text: str, cache_key: str = None) -> str:
    if not text or looks_italian(text):
        return text
    if cache_key:
        cached = cache_get(f"{ANIME_DESC_CACHE_PREFIX}:{cache_key}")
        if cached and not looks_english(cached):
            return cached
    return ""

async def ensure_anime_description_italian(text: str, cache_key: str = None) -> str:
    if not text:
        return ""
    if looks_italian(text) and not looks_english(text):
        return text
    translated = await translate_anime_description(text, cache_key)
    if translated and looks_english(translated) and not looks_italian(translated):
        return ""
    return translated or ""

def is_generic_episode_title(title: str) -> bool:
    if not title:
        return True
    lower = title.strip().lower()
    return lower.startswith("episodio ") or lower.startswith("episode ")

async def translate_anime_episode_title(title: str, cache_key: str = None) -> str:
    if not title or looks_italian(title) or is_generic_episode_title(title):
        return title
    if cache_key:
        cached = cache_get(f"anime_ep_title_it_v1:{cache_key}")
        if cached and not looks_english(cached):
            return cached
    translated = await translate_to_italian(title)
    if translation_failed(title, translated):
        return title
    if cache_key:
        cache_set(f"anime_ep_title_it_v1:{cache_key}", translated, ttl=30 * 24 * 60 * 60)
    return translated

async def anime_episode_title_cached_or_generic(title: str, episode_num: int, cache_key: str = None) -> str:
    if not title or looks_italian(title):
        return title or f"Episodio {episode_num}"
    if cache_key:
        cached = cache_get(f"anime_ep_title_it_v1:{cache_key}")
        if cached and not looks_english(cached):
            return cached
    return f"Episodio {episode_num}"

def pick_tmdb_italian_title(details: dict, fallback: str = "") -> str:
    if not details:
        return fallback
    translations = (details.get("translations") or {}).get("translations", [])
    for translation in translations:
        if (translation.get("iso_639_1") or "").lower() != "it":
            continue
        data = translation.get("data") or {}
        title = data.get("name") or data.get("title")
        if title:
            return title
    alt_titles = (details.get("alternative_titles") or {}).get("results", [])
    for alt in alt_titles:
        if (alt.get("iso_3166_1") or "").upper() == "IT" and alt.get("title"):
            return alt["title"]
    return details.get("name") or fallback

async def find_tmdb_anime_it(name: str, year: str = "", cache_key: str = None) -> dict:
    if not name or not TMDB_API_KEY:
        return {}
    key = f"anime_tmdb_it_v3:{cache_key or name}:{year}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    try:
        search = await tmdb_get("/search/tv", {"query": name, "page": 1}, lang="it-IT")
        results = search.get("results", [])
        if not results:
            cache_set(key, {}, ttl=7 * 24 * 60 * 60)
            return {}
        best = None
        best_score = -1
        needle = name.lower()
        for result in results[:8]:
            title = (result.get("name") or result.get("original_name") or "").lower()
            score = 0
            if title == needle:
                score += 80
            elif needle in title or title in needle:
                score += 40
            if year and (result.get("first_air_date") or "")[:4] == str(year):
                score += 30
            if result.get("original_language") == "ja" or "JP" in result.get("origin_country", []):
                score += 20
            if 16 in result.get("genre_ids", []):
                score += 10
            score += min(float(result.get("popularity") or 0), 50) / 10
            if score > best_score:
                best_score = score
                best = result
        if not best:
            cache_set(key, {}, ttl=7 * 24 * 60 * 60)
            return {}
        details = await tmdb_get_with_fallback(
            f"/tv/{best['id']}",
            {"append_to_response": "translations,alternative_titles"},
        )
        if not details:
            cache_set(key, {}, ttl=7 * 24 * 60 * 60)
            return {}
        info = {
            "id": details.get("id") or best.get("id"),
            "name": pick_tmdb_italian_title(details, best.get("name") or name),
            "overview": details.get("overview") or "",
            "poster": f"{TMDB_POSTER}{details['poster_path']}" if details.get("poster_path") else None,
            "background": f"{TMDB_ORIG}{details['backdrop_path']}" if details.get("backdrop_path") else None,
        }
        if info["overview"] and looks_english(info["overview"]):
            info["overview"] = await translate_anime_description(info["overview"], f"tmdb:{info['id']}")
        cache_set(key, info, ttl=7 * 24 * 60 * 60)
        return info
    except:
        return {}

async def fetch_tmdb_italian_episodes(tmdb_tv_id: str, poster: str = None) -> dict:
    if not tmdb_tv_id:
        return {}
    details = await tmdb_get(f"/tv/{tmdb_tv_id}")
    seasons = [s for s in details.get("seasons", []) if s.get("season_number", 0) > 0]
    seasons = seasons[:15]
    if not seasons:
        return {}

    async def fetch_season(season_number):
        data = await tmdb_get(f"/tv/{tmdb_tv_id}/season/{season_number}")
        return season_number, data

    try:
        seasons_data = await asyncio.gather(*[fetch_season(s["season_number"]) for s in seasons])
    except:
        return {}

    episode_map = {}
    absolute_num = 1
    for season_number, season in sorted(seasons_data):
        if not season:
            continue
        for ep in season.get("episodes", []):
            ep_num = ep.get("episode_number", 0)
            if not ep_num:
                continue
            title = ep.get("name") or ""
            overview = ep.get("overview") or ""
            still = f"{TMDB_ORIG}{ep['still_path']}" if ep.get("still_path") else poster
            episode_map[absolute_num] = {
                "title": title,
                "overview": overview,
                "thumbnail": still,
                "air_date": ep.get("air_date", ""),
                "season": season_number,
                "episode": ep_num,
            }
            absolute_num += 1
    return episode_map

async def kitsu_api(endpoint, params=None):
    """Chiama le API REST di Kitsu"""
    base = "https://kitsu.io/api/edge"
    headers = {"Accept": "application/vnd.api+json"}
    p = {"page[limit]": 20, "include": "genres"}
    if params: p.update(params)
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{base}/{endpoint}", params=p, headers=headers)
            return r.json() if r.status_code == 200 else {}
    except: return {}

async def kitsu_item_to_meta(item):
    """Converte un item Kitsu in meta per il CATALOG con trama italiana cachata"""
    attrs = item.get("attributes") or {}
    kitsu_id = item.get("id", "")
    if not attrs: return None

    titles = attrs.get("titles") or {}
    name = (titles.get("it") or titles.get("en") or titles.get("en_jp") or attrs.get("canonicalTitle", ""))
    if not name: return None

    poster_img = attrs.get("posterImage") or {}
    poster = poster_img.get("large") or poster_img.get("original")
    cover_img = attrs.get("coverImage") or {}
    background = cover_img.get("large") or cover_img.get("original")
    year = (attrs.get("startDate") or "")[:4]
    rating = attrs.get("averageRating")
    description = attrs.get("synopsis", "") or ""
    tmdb_anime = await find_tmdb_anime_it(name, year, f"kitsu:{kitsu_id}") if TMDB_API_KEY else {}
    if tmdb_anime:
        if tmdb_anime.get("name"):
            name = tmdb_anime["name"]
        if tmdb_anime.get("overview"):
            description = tmdb_anime["overview"]
        if tmdb_anime.get("poster"):
            poster = tmdb_anime["poster"]
        if tmdb_anime.get("background"):
            background = tmdb_anime["background"]

    if FAST_CATALOGS:
        description = await ensure_anime_description_italian(description, f"kitsu_fast:{kitsu_id}")
        return {
            "id": f"kitsu:{kitsu_id}",
            "type": "series",
            "name": name,
            "description": description,
            "poster": poster,
            "background": background,
            "releaseInfo": f"{year}–" if attrs.get("status") == "current" else year,
            "imdbRating": str(round(float(rating)/10, 1)) if rating else None,
            "genres": ["Anime"],
        }

    # Controlla cache Redis per la trama
    desc_cache_key = f"desc:kitsu:{kitsu_id}"
    cached_desc = cache_get(desc_cache_key)
    if cached_desc is not None:
        description = await translate_anime_description(cached_desc, f"kitsu_cached:{kitsu_id}")
    elif name and TMDB_API_KEY:
        # Cerca trama italiana su TMDB
        try:
            tmdb = await tmdb_get("/search/tv", {"query": name})
            results = tmdb.get("results", [])
            if results:
                tmdb_d = await tmdb_get_with_fallback(f"/tv/{results[0]['id']}")
                if tmdb_d and tmdb_d.get("overview"):
                    description = tmdb_d["overview"]
                    if tmdb_d.get("poster_path"): poster = f"{TMDB_POSTER}{tmdb_d['poster_path']}"
                    if tmdb_d.get("backdrop_path"): background = f"{TMDB_ORIG}{tmdb_d['backdrop_path']}"
            description = await ensure_anime_description_italian(description, f"kitsu:{kitsu_id}")
            # Salva in cache per 7 giorni
            cache_set(desc_cache_key, description, ttl=7*24*60*60)
        except: pass
    else:
        description = await ensure_anime_description_italian(description, f"kitsu:{kitsu_id}")

    return {
        "id": f"kitsu:{kitsu_id}",
        "type": "series",
        "name": name,
        "description": description,
        "poster": poster,
        "background": background,
        "releaseInfo": f"{year}–" if attrs.get("status") == "current" else year,
        "imdbRating": str(round(float(rating)/10, 1)) if rating else None,
        "genres": ["Anime"],
    }

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": MANIFEST.get("version"),
        "cache_version": CACHE_VERSION,
        "catalog_limit": CATALOG_LIMIT,
    }

@app.get("/status")
async def status():
    valid_token = get_valid_token()
    s = token_status()
    expires = "N/D"
    if s["expires_at"]:
        expires = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(s["expires_at"]))
    rows = {
        "Simkl valido ora": "✅ Sì" if valid_token else "❌ No",
        "Redis configurato": "✅ Sì" if s["redis_enabled"] else "❌ No",
        "Token salvato su Redis": "✅ Sì" if s["redis_has_tokens"] else "❌ No",
        "Token salvato su file": "✅ Sì" if s["file_has_tokens"] else "❌ No",
        "Token Simkl permanente": "✅ Sì" if valid_token else "❌ No",
    }
    body = "".join(f"<div class='row'><b>{k}</b><span>{v}</span></div>" for k, v in rows.items())
    return HTMLResponse(f"""<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8"><title>Status Addon</title>
    <style>body{{font-family:sans-serif;max-width:720px;margin:50px auto;background:#1a1a2e;color:#eee;padding:20px;}}
    h1{{color:#ed1c24;}}.row{{display:flex;justify-content:space-between;gap:18px;padding:12px 0;border-bottom:1px solid #333;}}
    a{{color:#ed1c24;}}span{{text-align:right;}}</style></head>
    <body><h1>Stato addon</h1>{body}<p><a href="/">← Home</a></p></body></html>""")

@app.get("/problems")
async def problems():
    token = get_valid_token()
    s = token_status()
    checks = [
        ("TMDB API key", bool(TMDB_API_KEY), "Senza TMDB mancano poster, meta ricchi, provider e cataloghi per genere."),
        ("Simkl login", bool(token), "Senza Simkl restano vuoti consigli personali e cataloghi simili ai tuoi gusti."),
        ("Simkl Client ID", bool(SIMKL_CLIENT_ID), "Crea gratuitamente un'app Simkl e salva il Client ID nei secret Hugging Face."),
        ("Redis", s["redis_enabled"], "Senza Redis il login Simkl può perdersi dopo rebuild/restart."),
        ("Token su Redis", s["redis_has_tokens"], "Se è No, rifai login Simkl per salvare il token persistente."),
        ("Filtro voto minimo", MIN_VOTE_COUNT <= 50, "Se troppo alto, alcuni cataloghi possono sembrare vuoti."),
        ("Solo usciti", ONLY_RELEASED, "Se attivo, i cataloghi pubblici escludono titoli non ancora usciti."),
        ("Escludi reality/talk", EXCLUDE_REALITY, "Se attivo, i cataloghi serie eliminano reality e talk show."),
    ]
    rows = "".join(
        f"<div class='row'><b>{name}</b><span>{'✅ OK' if ok else '⚠️ Attenzione'}</span><small>{hint}</small></div>"
        for name, ok, hint in checks
    )
    return HTMLResponse(f"""<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8"><title>Problemi Addon</title>
    <style>body{{font-family:sans-serif;max-width:820px;margin:50px auto;background:#1a1a2e;color:#eee;padding:20px;}}
    h1{{color:#ed1c24;}}.row{{padding:14px 0;border-bottom:1px solid #333;display:grid;grid-template-columns:1fr auto;gap:8px 18px;}}
    small{{grid-column:1 / -1;color:#bbb;}}a{{color:#ed1c24;}}</style></head>
    <body><h1>Diagnostica problemi</h1>{rows}<p><a href="/">← Home</a> · <a href="/status">Status</a></p></body></html>""")

def active_config_rows():
    values = {
        "Versione addon": MANIFEST.get("version"),
        "Base URL": BASE_URL,
        "TMDB key": "presente" if TMDB_API_KEY else "mancante",
        "Simkl Client ID": "presente" if SIMKL_CLIENT_ID else "mancante",
        "YouTube key": "presente" if YOUTUBE_API_KEY else "mancante",
        "Trailer": "solo italiano",
        "Redis": "configurato" if REDIS_URL and REDIS_TOKEN else "mancante",
        "Nascondi già visti": str(HIDE_WATCHED),
        "Cataloghi veloci": str(FAST_CATALOGS),
        "Trailer nei cataloghi": str(CATALOG_TRAILERS),
        "Elementi per pagina": str(CATALOG_LIMIT),
        "Preload avvio": str(PRELOAD_CATALOGS),
        "Refresh background": str(BACKGROUND_REFRESH),
        "Voti minimi": str(MIN_VOTE_COUNT),
        "Rating minimo": str(MIN_RATING),
        "Escludi reality/talk": str(EXCLUDE_REALITY),
        "Solo contenuti usciti": str(ONLY_RELEASED),
        "Cataloghi manifest": str(len(MANIFEST.get("catalogs", []))),
    }
    return "".join(f"<div class='row'><b>{k}</b><span>{v}</span></div>" for k, v in values.items())

def clear_local_token_file():
    try:
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
            return True
    except Exception as e:
        print(f"[ADMIN] Errore rimozione token file: {e}")
    return False

@app.get("/admin")
async def admin(message: str = ""):
    token = get_valid_token()
    s = token_status()
    simkl = "✅ Loggato" if token else "❌ Non loggato"
    redis = "✅ Attivo" if s["redis_enabled"] else "❌ Non configurato"
    msg = f"<div class='msg'>{message}</div>" if message else ""
    return HTMLResponse(f"""<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8"><title>Admin Addon</title>
    <style>body{{font-family:sans-serif;max-width:920px;margin:44px auto;background:#1a1a2e;color:#eee;padding:20px;}}
    h1{{color:#ed1c24;}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:18px 0;}}
    a.btn{{display:block;background:#ed1c24;color:#fff;text-decoration:none;text-align:center;padding:12px 14px;border-radius:8px;font-weight:bold;}}
    a.secondary{{background:#333;}}.row{{display:flex;justify-content:space-between;gap:18px;padding:10px 0;border-bottom:1px solid #333;}}
    .panel{{background:#222;padding:14px;border-radius:10px;margin:14px 0;}}.msg{{background:#143d22;color:#c9ffd9;padding:12px;border-radius:8px;margin:12px 0;}}
    code{{background:#111;padding:2px 6px;border-radius:4px;}}span{{text-align:right;}}</style></head>
    <body><h1>Admin addon</h1>{msg}
    <div class="panel"><div class="row"><b>Simkl</b><span>{simkl}</span></div><div class="row"><b>Redis</b><span>{redis}</span></div></div>
    <div class="grid">
      <a class="btn" href="/admin/refresh">Refresh cataloghi</a>
      <a class="btn" href="/admin/clear-cache">Svuota cache</a>
      <a class="btn secondary" href="/admin/logout">Logout Simkl</a>
      <a class="btn secondary" href="/login">Login Simkl</a>
      <a class="btn secondary" href="/status">Status</a>
      <a class="btn secondary" href="/problems">Problemi</a>
      <a class="btn secondary" href="/manifest.json">Manifest</a>
      <a class="btn secondary" href="/nuvio/film-saga-collection.json">Nuvio Film Saga</a>
    </div>
    <div class="panel"><h2>Configurazione attiva</h2>{active_config_rows()}</div>
    <p><a style="color:#ed1c24" href="/">← Home</a></p></body></html>""")

@app.get("/admin/clear-cache")
async def admin_clear_cache():
    _cache.clear()
    deleted = redis_scan_delete_prefix("cat:")
    return RedirectResponse(f"/admin?message={urllib.parse.quote(f'Cache svuotata. Chiavi Redis eliminate: {deleted}')}")

@app.get("/admin/logout")
async def admin_logout():
    _cache.clear()
    redis_delete_sync("simkl_tokens")
    clear_local_token_file()
    return RedirectResponse("/admin?message=Logout Simkl completato. Token rimossi da Redis e file locale.")

@app.get("/admin/refresh")
async def admin_refresh():
    _cache.clear()
    redis_scan_delete_prefix("cat:v", limit=500)
    targets = [
        ("movie", "trending-movies"),
        ("series", "trending-series"),
        ("series", "kitsu-trending"), ("series", "kitsu-airing"),
    ]
    warmed = 0
    async with httpx.AsyncClient(timeout=12) as c:
        for media_type, catalog_id in targets:
            try:
                await c.get(f"{BASE_URL}/catalog/{media_type}/{catalog_id}.json")
                warmed += 1
            except Exception as e:
                print(f"[ADMIN REFRESH] {catalog_id}: {e}")
    return RedirectResponse(f"/admin?message={urllib.parse.quote(f'Refresh avviato. Cataloghi riscaldati: {warmed}/{len(targets)}')}")

@app.get("/")
async def root():
    # Prima prova a caricare il token da Redis se non è già in memoria
    token = get_valid_token()
    if not token:
        load_tokens()
        token = get_valid_token()
    status = "✅ Autenticato con Simkl" if token else "❌ Non autenticato"
    return HTMLResponse(f"""<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8"><title>Il Mio Addon</title>
    <style>body{{font-family:sans-serif;max-width:600px;margin:60px auto;background:#1a1a2e;color:#eee;padding:20px;border-radius:12px;}}
    h1{{color:#ed1c24;}}.s{{padding:10px 16px;border-radius:8px;background:#222;margin:12px 0;}}
    a.b{{display:inline-block;padding:12px 24px;background:#ed1c24;color:white;border-radius:8px;text-decoration:none;margin:8px 4px;font-weight:bold;}}
    a.g{{background:#333;}}code{{background:#111;padding:6px 10px;border-radius:4px;display:block;word-break:break-all;margin:8px 0;}}</style></head>
    <body><h1>🎬 Il Mio Addon</h1><div class="s">{status}</div>
    <a class="b" href="{BASE_URL}/login">🔗 Connetti Simkl</a>
    <a class="b g" href="{BASE_URL}/manifest.json">📋 Manifest</a>
    <a class="b g" href="{BASE_URL}/status">🩺 Status</a>
    <a class="b g" href="{BASE_URL}/problems">🧯 Problemi</a>
    <a class="b g" href="{BASE_URL}/admin">⚙️ Admin</a>
    <a class="b g" href="{BASE_URL}/nuvio/film-saga-collection.json">Film Saga Nuvio</a>
    <h3>Installa in Stremio:</h3><code>{BASE_URL}/manifest.json</code></body></html>""")

@app.get("/login")
async def login():
    if not SIMKL_CLIENT_ID:
        return HTMLResponse("<h2>Simkl non configurato</h2><p>Manca il secret SIMKL_CLIENT_ID.</p>", status_code=503)
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{SIMKL_BASE}/oauth/pin", params={"client_id": SIMKL_CLIENT_ID})
    if r.status_code != 200:
        return HTMLResponse(f"<h2>Errore Simkl</h2><pre>{html.escape(r.text)}</pre>", status_code=502)
    d = r.json()
    code = d.get("user_code", "")
    verify = d.get("verification_url", "https://simkl.com/pin/")
    interval = max(5, int(d.get("interval", 5)))
    return HTMLResponse(f"""<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8"><title>Connetti Simkl</title>
    <style>body{{font-family:sans-serif;max-width:560px;margin:70px auto;background:#1a1a2e;color:#eee;text-align:center;padding:28px;border-radius:12px}}
    h1{{color:#49a8ff}}code{{display:block;font-size:34px;letter-spacing:5px;background:#111;padding:16px;margin:18px}}a{{color:white;background:#1677c8;padding:12px 20px;border-radius:8px;text-decoration:none}}</style></head>
    <body><h1>Connetti Simkl</h1><p>Apri Simkl e inserisci questo codice:</p><code>{html.escape(code)}</code>
    <p><a target="_blank" href="{html.escape(verify)}">Apri Simkl</a></p><p id="s">In attesa dell'autorizzazione...</p>
    <script>setInterval(async()=>{{let r=await fetch('/simkl-poll?code={urllib.parse.quote(code)}');let d=await r.json();
    if(d.authorized){{location.href='/';}}else if(d.error){{document.getElementById('s').textContent=d.error;}}}}, {interval * 1000});</script></body></html>""")

@app.get("/simkl-poll")
async def simkl_poll(code: str = ""):
    if not code or not SIMKL_CLIENT_ID:
        return JSONResponse({"authorized": False, "error": "Configurazione incompleta"}, status_code=400)
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{SIMKL_BASE}/oauth/pin/{urllib.parse.quote(code)}", params={"client_id": SIMKL_CLIENT_ID})
    if r.status_code != 200:
        return JSONResponse({"authorized": False, "error": "Simkl non raggiungibile"})
    d = r.json()
    if d.get("access_token"):
        save_tokens({"access_token": d["access_token"], "token_type": d.get("token_type", "bearer")})
        _cache.clear()
        return JSONResponse({"authorized": True})
    return JSONResponse({"authorized": False})

@app.get("/callback")
async def callback():
    return RedirectResponse("/")

@app.get("/manifest.json")
async def manifest(): return JSONResponse(MANIFEST)

@app.get("/nuvio/film-saga-collection.json")
@app.get("/nuvio-film-saga-collection.json")
async def nuvio_film_saga_collection():
    return FileResponse(
        os.path.join(os.path.dirname(__file__), "nuvio-film-saga-collection.json"),
        media_type="application/json",
        filename="nuvio-film-saga-collection.json",
    )

@app.get("/nuvio/film-saga-collection.raw.json")
async def nuvio_film_saga_collection_raw():
    with open(os.path.join(os.path.dirname(__file__), "nuvio-film-saga-collection.json"), "r", encoding="utf-8") as f:
        return JSONResponse(json.load(f))

@app.get("/nuvio/marvel-collection.json")
@app.get("/nuvio-marvel-collection.json")
async def nuvio_marvel_collection():
    return FileResponse(
        os.path.join(os.path.dirname(__file__), "nuvio-marvel-collection.json"),
        media_type="application/json",
        filename="nuvio-marvel-collection.json",
    )

@app.get("/nuvio/marvel-collection.raw.json")
async def nuvio_marvel_collection_raw():
    with open(os.path.join(os.path.dirname(__file__), "nuvio-marvel-collection.json"), "r", encoding="utf-8") as f:
        return JSONResponse(json.load(f))

@app.get("/catalog/{media_type}/{catalog_id}.json")
@app.get("/catalog/{media_type}/{catalog_id}/skip={skip}.json")
@app.get("/catalog/{media_type}/{catalog_id}/search={query}.json")
@app.get("/catalog/{media_type}/{catalog_id}/genre={genre}.json")
@app.get("/catalog/{media_type}/{catalog_id}/genre={genre}/skip={skip}.json")
@app.get("/catalog/{media_type}/{catalog_id}/skip={skip}/genre={genre}.json")
async def catalog(media_type: str, catalog_id: str, skip: int = 0, query: str = None, genre: str = None):
    # ── Ricerca ──
    if query:
        tmdb_type = "movie" if media_type == "movie" else "tv"
        try:
            search_results = []
            d_it, d_en = await asyncio.gather(
                tmdb_get(f"/search/{tmdb_type}", {"query": query, "page": 1}, lang="it-IT"),
                tmdb_get(f"/search/{tmdb_type}", {"query": query, "page": 1}, lang="en-US"),
            )
            search_results.extend(d_it.get("results", []))
            search_results.extend(d_en.get("results", []))

            expanded = await ai_expand_query(query)
            if expanded != query:
                d2 = await tmdb_get(f"/search/{tmdb_type}", {"query": expanded, "page": 1}, lang="en-US")
                search_results.extend(d2.get("results", []))

            def is_valid(r):
                name = r.get("name") or r.get("title") or ""
                orig_title = r.get("original_title") or r.get("original_name") or ""
                for check in [name, orig_title]:
                    if any('　' <= c <= '鿿' or '゠' <= c <= 'ヿ' or '぀' <= c <= 'ゟ' for c in check):
                        return False
                return is_tmdb_result_valid(r, media_type, strict=False)

            results = []
            seen_tmdb = set()
            for r in search_results:
                tmdb_id = r.get("id")
                if not tmdb_id or tmdb_id in seen_tmdb:
                    continue
                seen_tmdb.add(tmdb_id)
                if is_valid(r):
                    results.append(r)
            # Nella ricerca serie, escludi anime (Animation + origine Giappone)
            if catalog_id == "search-series":
                results = [r for r in results if not (
                    16 in r.get("genre_ids", []) and
                    "JP" in r.get("origin_country", [])
                )]
            return JSONResponse({"metas": await build_catalog_from_tmdb(results[:20], media_type)})
        except Exception as e:
            return JSONResponse({"metas": [], "error": str(e)})

    # ── Catalog ──
    limit = max(20, min(CATALOG_LIMIT, 60))
    page = (skip // limit) + 1
    token = get_valid_token()
    tt = "movies" if media_type == "movie" else "shows"
    personal = (
        "personal-movies", "personal-series",
    )
    refresh_on_watch_change = catalog_id in (
        "personal-movies", "personal-series",
        "similar-history-movies", "similar-history-series",
    )
    genre_key = genre_key_from_extra(genre)
    if not genre_key:
        genre_key = genre_key_from_catalog(catalog_id)
    raw_genre_key = urllib.parse.unquote(str(genre or "")).strip()
    cache_key = f"{CACHE_VERSION}:{catalog_id}:{media_type}:{page}:genre={genre_key or ''}:raw={raw_genre_key}:hide={int(HIDE_WATCHED and bool(token))}:q={MIN_VOTE_COUNT}:{MIN_RATING}:{int(EXCLUDE_REALITY)}:{int(ONLY_RELEASED)}"

    # Cache per tutti i catalog inclusi personal (TTL più breve per personal)
    cached = None if (refresh_on_watch_change and token) else cache_get(cache_key)
    if cached is not None: return JSONResponse({"metas": cached})
    watched_ids = await get_watched_ids(media_type, token, force_refresh=refresh_on_watch_change) if media_type in ("movie", "series") else set()

    if media_type == "movie" and catalog_id.startswith("nuvio-"):
        nuvio_catalog_id = catalog_id
        if catalog_id == "nuvio-saga" and genre:
            nuvio_catalog_id = urllib.parse.unquote(str(genre))
        metas = await build_nuvio_saga_catalog(nuvio_catalog_id, skip=skip, limit=100)
        cache_set(cache_key, metas, ttl=24 * 60 * 60)
        return JSONResponse({"metas": metas})


    # ── Catalog Anime (AniList) ──
    if media_type == "anime" or catalog_id in ("anime-trending", "anime-popular", "search-anime"):
        try:
            if query:
                items = await anilist_search(query, page=page)
                # Filtra solo anime giapponesi (countryOfOrigin = JP)
                items = [i for i in items if i.get("countryOfOrigin", "JP") == "JP"]
            elif catalog_id == "anime-trending":
                gql = """
                query ($page: Int, $perPage: Int) {
                    Page(page: $page, perPage: $perPage) {
                        media(type: ANIME, sort: TRENDING_DESC) {
                            id idMal
                            title { romaji english native }
                            countryOfOrigin
                            coverImage { large extraLarge }
                            bannerImage averageScore
                            startDate { year } status genres
                        }
                    }
                }
                """
                async with httpx.AsyncClient(timeout=8) as c:
                    r = await c.post("https://graphql.anilist.co",
                        json={"query": gql, "variables": {"page": page, "perPage": 20}},
                        headers={"Content-Type": "application/json"})
                    items = r.json().get("data", {}).get("Page", {}).get("media", []) if r.status_code == 200 else []
            else:
                items = await anilist_search("anime", page=page)
            metas = []
            for item in items:
                m = await anilist_to_meta(item)
                if m["name"]: metas.append(m)
            return JSONResponse({"metas": metas})
        except Exception as e:
            return JSONResponse({"metas": [], "error": str(e)})

    # ── Catalog Anime (Kitsu) ──
    if catalog_id in ("kitsu-trending", "kitsu-popular", "kitsu-airing", "kitsu-series", "kitsu-movies", "kitsu-search"):
        try:
            offset = skip
            if catalog_id == "kitsu-trending":
                data = await kitsu_api("trending/anime", {"page[limit]": 20, "page[offset]": offset})
            elif catalog_id == "kitsu-popular":
                data = await kitsu_api("anime", {"sort": "-userCount", "page[limit]": 20, "page[offset]": offset, "filter[subtype]": "TV,OVA,ONA,movie", "filter[status]": "finished,current"})
            elif catalog_id == "kitsu-airing":
                data = await kitsu_api("anime", {"sort": "-userCount", "page[limit]": 20, "page[offset]": offset, "filter[subtype]": "TV,ONA", "filter[status]": "current"})
            elif catalog_id == "kitsu-series":
                data = await kitsu_api("anime", {"sort": "-userCount", "page[limit]": 20, "page[offset]": offset, "filter[subtype]": "TV,OVA,ONA", "filter[status]": "finished,current"})
            elif catalog_id == "kitsu-movies":
                data = await kitsu_api("anime", {"sort": "-userCount", "page[limit]": 20, "page[offset]": offset, "filter[subtype]": "movie"})
            elif catalog_id == "kitsu-search" and query:
                # Kitsu con include=mediaRelationships mostra anche sequel/prequel
                data = await kitsu_api("anime", {
                    "filter[text]": query,
                    "page[limit]": 20,
                    "page[offset]": skip,
                    "filter[subtype]": "TV,OVA,ONA,movie,special",
                    "include": "mediaRelationships.destination",
                })
                # Aggiungi anche i sequel/prequel trovati
                extra_ids = set()
                for item in data.get("included", []):
                    if item.get("type") == "anime":
                        extra_ids.add(item.get("id"))
                if extra_ids:
                    extra_data = await kitsu_api("anime", {
                        "filter[id]": ",".join(list(extra_ids)[:10]),
                        "filter[subtype]": "TV,ONA",
                    })
                    existing_ids = {i.get("id") for i in data.get("data", [])}
                    for item in extra_data.get("data", []):
                        if item.get("id") not in existing_ids:
                            data["data"].append(item)
            else:
                return JSONResponse({"metas": []})

            items = data.get("data", [])
            metas = []
            seen = set()
            for item in items:
                if item.get("id") in seen:
                    continue
                seen.add(item.get("id"))
                m = await kitsu_item_to_meta(item)
                if m: metas.append(m)
            return JSONResponse({"metas": metas})
        except Exception as e:
            return JSONResponse({"metas": [], "error": str(e)})

    try:
        params = {"page": page, "limit": limit, "extended": "full"}
        raw = []

        if genre_key and (
            catalog_id in ("genre-movies", "genre-series", "popular-movies", "popular-series")
            or genre_key_from_catalog(catalog_id)
        ):
            genre_id = GENRE_CATALOGS[genre_key].get(media_type)
            if not genre_id:
                return JSONResponse({"metas": []})
            results = await tmdb_discover_genre_results(media_type, genre_id, skip, limit, watched_ids)
            metas = await build_catalog_from_tmdb(results, media_type)
            metas = hide_watched_metas(metas, watched_ids)
            cache_set(cache_key, metas, ttl=catalog_ttl(catalog_id))
            return JSONResponse({"metas": metas})
        elif catalog_id in ("personal-movies", "personal-series"):
            if token:
                # Consigli gratuiti TMDB basati sui titoli completati su Simkl.
                personal_cache_key = f"{catalog_id}:{media_type}:all"
                raw = None if refresh_on_watch_change else cache_get(personal_cache_key)
                if raw is None:
                    raw = await simkl_items(media_type, "completed", token, force_refresh=refresh_on_watch_change)
                    if raw and not refresh_on_watch_change: cache_set(personal_cache_key, raw, ttl=CACHE_TTL_PERSONAL)
                    print(f"[SIMKL] completed/{media_type} → {len(raw)} risultati, token=OK")
                else:
                    print(f"[SIMKL] completed/{media_type} → {len(raw)} risultati, da cache")
                metas = await tmdb_recommendations_for_simkl_items(raw or [], media_type, watched_ids, page=page)
                return JSONResponse({"metas": slice_items(metas, skip=0, limit=limit)})
            else:
                print(f"[SIMKL] Token mancante per {catalog_id}")
        elif catalog_id in ("popular-movies", "popular-series"):
            tmdb_t = "movie" if media_type == "movie" else "tv"
            results = await tmdb_collect_filtered_results(
                media_type, skip, limit,
                lambda tmdb_page: tmdb_get(f"/{tmdb_t}/popular", {"page": tmdb_page}),
                watched_ids=watched_ids,
                exclude_languages=True
            )
            metas = await build_catalog_from_tmdb(results, media_type)
            metas = hide_watched_metas(metas, watched_ids)
            cache_set(cache_key, metas, ttl=catalog_ttl(catalog_id))
            return JSONResponse({"metas": metas})
        elif catalog_id in ("after-recommendations-home-cinema-movies", "top-home-cinema-movies", "featured-home-cinema-movies", "home-cinema-movies") and media_type == "movie":
            metas = await build_home_cinema_catalog(skip=skip, limit=limit, watched_ids=watched_ids)
            cache_set(cache_key, metas, ttl=catalog_ttl(catalog_id))
            return JSONResponse({"metas": metas})
        elif catalog_id == "sagas-movies" and media_type == "movie":
            metas = await build_sagas_catalog(skip=skip, limit=limit, watched_ids=watched_ids)
            cache_set(cache_key, metas, ttl=24 * 60 * 60)
            return JSONResponse({"metas": metas})
        elif catalog_id in ("trending-movies", "trending-series"):
            # Usa TMDB trending
            tmdb_t = "movie" if media_type == "movie" else "tv"
            results = await tmdb_collect_filtered_results(
                media_type, skip, limit,
                lambda tmdb_page: tmdb_get(f"/trending/{tmdb_t}/week", {"page": tmdb_page}),
                watched_ids=watched_ids,
                exclude_languages=True
            )
            metas = await build_catalog_from_tmdb(results, media_type)
            metas = hide_watched_metas(metas, watched_ids)
            cache_set(cache_key, metas, ttl=catalog_ttl(catalog_id))
            return JSONResponse({"metas": metas})
        elif catalog_id in ("toprated-movies", "toprated-series"):
            tmdb_t = "movie" if media_type == "movie" else "tv"
            results = await tmdb_collect_filtered_results(
                media_type, skip, limit,
                lambda tmdb_page: tmdb_get(f"/{tmdb_t}/top_rated", {"page": tmdb_page}),
                watched_ids=watched_ids,
                exclude_languages=True
            )
            metas = await build_catalog_from_tmdb(results, media_type)
            metas = hide_watched_metas(metas, watched_ids)
            cache_set(cache_key, metas, ttl=catalog_ttl(catalog_id))
            return JSONResponse({"metas": metas})
        elif catalog_id in ("new-movies", "new-series"):
            tmdb_t = tmdb_type_for(media_type)
            today = time.strftime("%Y-%m-%d")
            since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 75 * 24 * 60 * 60))
            date_params = {
                "primary_release_date.gte" if media_type == "movie" else "first_air_date.gte": since,
                "primary_release_date.lte" if media_type == "movie" else "first_air_date.lte": today,
                "sort_by": "primary_release_date.desc" if media_type == "movie" else "first_air_date.desc",
            }
            results = await tmdb_collect_filtered_results(
                media_type, skip, limit,
                lambda tmdb_page: tmdb_get(f"/discover/{tmdb_t}", tmdb_discover_params(media_type, tmdb_page, date_params)),
                watched_ids=watched_ids,
                exclude_languages=True
            )
            metas = await build_catalog_from_tmdb(results, media_type)
            metas = hide_watched_metas(metas, watched_ids)
            cache_set(cache_key, metas, ttl=catalog_ttl(catalog_id))
            return JSONResponse({"metas": metas})
        elif catalog_id in ("italian-movies", "italian-series"):
            tmdb_t = "movie" if media_type == "movie" else "tv"
            results = await tmdb_collect_filtered_results(
                media_type, skip, limit,
                lambda tmdb_page: tmdb_get(f"/discover/{tmdb_t}", tmdb_discover_params(media_type, tmdb_page, {
                    "with_original_language": "it",
                    "region": "IT",
                })),
                watched_ids=watched_ids
            )
            metas = await build_catalog_from_tmdb(results, media_type)
            metas = hide_watched_metas(metas, watched_ids)
            cache_set(cache_key, metas, ttl=catalog_ttl(catalog_id))
            return JSONResponse({"metas": metas})
        elif catalog_id in ("genre-movies", "genre-series"):
            return JSONResponse({"metas": []})
        elif catalog_id in ("similar-watchlist-movies", "similar-watchlist-series", "similar-history-movies", "similar-history-series"):
            metas = await personalized_similar_catalog(catalog_id, media_type, token, watched_ids, page, force_refresh=refresh_on_watch_change)
            if not refresh_on_watch_change:
                cache_set(cache_key, metas, ttl=catalog_ttl(catalog_id))
            return JSONResponse({"metas": metas})
        elif catalog_id in ("netflix-movies", "netflix-series"):
            # Usa TMDB discover con provider Netflix (ID=8)
            tmdb_t = "movie" if media_type == "movie" else "tv"
            results = await tmdb_collect_filtered_results(
                media_type, skip, limit,
                lambda tmdb_page: tmdb_get(f"/discover/{tmdb_t}", tmdb_discover_params(media_type, tmdb_page, {
                    "with_watch_providers": 8, "watch_region": "IT",
                    "with_original_language": "en|it|fr|es|de"
                })),
                watched_ids=watched_ids,
                exclude_languages=True
            )
            metas = await build_catalog_from_tmdb(results, media_type)
            metas = hide_watched_metas(metas, watched_ids)
            cache_set(cache_key, metas, ttl=catalog_ttl(catalog_id))
            return JSONResponse({"metas": metas})
        elif catalog_id in ("disney-movies", "disney-series"):
            # Usa TMDB discover con provider Disney+ (ID=337)
            tmdb_t = "movie" if media_type == "movie" else "tv"
            results = await tmdb_collect_filtered_results(
                media_type, skip, limit,
                lambda tmdb_page: tmdb_get(f"/discover/{tmdb_t}", tmdb_discover_params(media_type, tmdb_page, {
                    "with_watch_providers": 337, "watch_region": "IT",
                })),
                watched_ids=watched_ids,
                exclude_languages=True
            )
            metas = await build_catalog_from_tmdb(results, media_type)
            metas = hide_watched_metas(metas, watched_ids)
            cache_set(cache_key, metas, ttl=catalog_ttl(catalog_id))
            return JSONResponse({"metas": metas})
        elif catalog_id in ("prime-movies", "prime-series"):
            # Usa TMDB discover con provider Prime (ID=119)
            tmdb_t = "movie" if media_type == "movie" else "tv"
            results = await tmdb_collect_filtered_results(
                media_type, skip, limit,
                lambda tmdb_page: tmdb_get(f"/discover/{tmdb_t}", tmdb_discover_params(media_type, tmdb_page, {
                    "with_watch_providers": 119, "watch_region": "IT",
                    "with_original_language": "en|it|fr|es|de"
                })),
                watched_ids=watched_ids,
                exclude_languages=True
            )
            metas = await build_catalog_from_tmdb(results, media_type)
            metas = hide_watched_metas(metas, watched_ids)
            cache_set(cache_key, metas, ttl=catalog_ttl(catalog_id))
            return JSONResponse({"metas": metas})
        elif catalog_id in ("kids-movies", "kids-series"):
            tmdb_type = "movie" if media_type == "movie" else "tv"
            results = await tmdb_collect_filtered_results(
                media_type, skip, limit,
                lambda tmdb_page: tmdb_get(f"/discover/{tmdb_type}", tmdb_discover_params(media_type, tmdb_page, {
                    "with_genres": "10751",  # Solo Family (non Animation che include adulti)
                    "certification_country": "US",
                    "certification.lte": "PG",  # Solo G e PG
                })),
                watched_ids=watched_ids,
                exclude_languages=True
            )
            metas = await build_catalog_from_tmdb(results, media_type)
            metas = hide_watched_metas(metas, watched_ids)
            cache_set(cache_key, metas, ttl=catalog_ttl(catalog_id))
            return JSONResponse({"metas": metas})

        metas = await build_catalog_from_simkl(raw, media_type)
        if catalog_id not in personal:
            metas = hide_watched_metas(metas, watched_ids)
        if catalog_id in personal:
            if metas: cache_set(cache_key, metas, ttl=catalog_ttl(catalog_id))
        else:
            cache_set(cache_key, metas, ttl=catalog_ttl(catalog_id))
        return JSONResponse({"metas": metas})
    except Exception as e:
        return JSONResponse({"metas": [], "error": str(e)})

@app.get("/meta/{media_type}/{item_id}.json")
async def meta(media_type: str, item_id: str):
    # Tratta anime come series per il meta handler TMDB
    if media_type == "anime":
        media_type = "series"

    # Converti mal: e anilist: in kitsu: tramite yuna.moe
    if item_id.startswith("mal:") or item_id.startswith("anilist:") or item_id.startswith("anidb:"):
        id_type = item_id.split(":")[0]
        id_val = item_id.split(":")[1]
        yuna_type = "myanimelist" if id_type == "mal" else id_type
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"https://relations.yuna.moe/api/v2/ids?source={yuna_type}&id={id_val}&include=kitsu")
                if r.status_code == 200:
                    kitsu_id = r.json().get("kitsu")
                    if kitsu_id:
                        item_id = f"kitsu:{kitsu_id}"
        except: pass

    # Gestione ID Kitsu (anime)
    if item_id.startswith("kitsu:"):
        parts = item_id.split(":")
        kitsu_id = parts[1]
        # kitsu:ID:episodio — prendi solo la serie, non l'episodio specifico
        # Cerca l'anime su TMDB tramite nome dal database Kitsu
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(f"https://kitsu.io/api/edge/anime/{kitsu_id}",
                               headers={"Accept": "application/vnd.api+json"})
                if r.status_code == 200:
                    kdata = r.json()
                    kdata_item = kdata.get("data")
                    if not kdata_item or not isinstance(kdata_item, dict):
                        return JSONResponse({"meta": {}})
                    attrs = kdata_item.get("attributes") or {}
                    if not attrs or not isinstance(attrs, dict):
                        return JSONResponse({"meta": {}})
                    # Titolo: preferisci italiano, poi inglese, poi giapponese
                    anime_name = (attrs.get("titles", {}).get("it") or
                                  attrs.get("titles", {}).get("en") or
                                  attrs.get("titles", {}).get("en_jp") or
                                  attrs.get("canonicalTitle", ""))
                    anime_desc = attrs.get("synopsis", "")
                    anime_poster = attrs.get("posterImage", {}).get("large") or attrs.get("posterImage", {}).get("original")
                    anime_cover = attrs.get("coverImage", {}).get("large") or attrs.get("coverImage", {}).get("original")
                    anime_rating = attrs.get("averageRating")
                    anime_year = (attrs.get("startDate") or "")[:4]
                    anime_status = attrs.get("status", "")

                    # Cerca su TMDB per avere trama in italiano
                    tmdb_anime = await find_tmdb_anime_it(anime_name, anime_year, f"meta:kitsu:{kitsu_id}")
                    tmdb_search = {} if tmdb_anime else await tmdb_get("/search/tv", {"query": anime_name, "page": 1})
                    tmdb_results = tmdb_search.get("results", [])
                    tmdb_data = None
                    tmdb_result = None
                    if tmdb_anime:
                        tmdb_data = {"id": tmdb_anime.get("id"), "name": tmdb_anime.get("name"), "overview": tmdb_anime.get("overview")}
                        if tmdb_anime.get("name"):
                            anime_name = tmdb_anime["name"]
                        if tmdb_anime.get("overview"):
                            anime_desc = tmdb_anime["overview"]
                        if tmdb_anime.get("poster"):
                            anime_poster = tmdb_anime["poster"]
                        if tmdb_anime.get("background"):
                            anime_cover = tmdb_anime["background"]
                    elif tmdb_results:
                        # Trova il risultato migliore usando anno e nome
                        best = None
                        best_score = -1
                        for r in tmdb_results[:5]:
                            score = 0
                            r_name = (r.get("name") or r.get("title") or "").lower()
                            a_name = anime_name.lower()
                            # Match esatto nome
                            if r_name == a_name: score += 100
                            # Match parziale
                            elif a_name in r_name or r_name in a_name: score += 50
                            # Match anno
                            r_year = (r.get("first_air_date") or "")[:4]
                            if anime_year and r_year == anime_year: score += 30
                            if score > best_score:
                                best_score = score
                                best = r
                        if best:
                            tmdb_result = [best]
                            tmdb_data = await tmdb_get_with_fallback(f"/tv/{best['id']}")

                    # Usa trama italiana da TMDB se disponibile
                    if tmdb_data and tmdb_data.get("overview"):
                        anime_desc = tmdb_data["overview"]
                    if tmdb_data and tmdb_data.get("name"):
                        anime_name = tmdb_data["name"]
                    anime_desc = await ensure_anime_description_italian(anime_desc, f"meta:kitsu:{kitsu_id}")
                    if tmdb_data and tmdb_data.get("poster_path"):
                        anime_poster = f"{TMDB_POSTER}{tmdb_data['poster_path']}"
                    if tmdb_data and tmdb_data.get("backdrop_path"):
                        anime_cover = f"{TMDB_ORIG}{tmdb_data['backdrop_path']}"

                    # Episodi
                    ep_count = attrs.get("episodeCount") or 0
                    release_info = anime_year
                    if anime_status == "finished":
                        end_year = (attrs.get("endDate") or "")[:4]
                        if end_year and end_year != anime_year:
                            release_info = f"{anime_year}–{end_year}"
                    elif anime_year:
                        release_info = f"{anime_year}–"

                    # Genera episodi direttamente da Kitsu (stagioni già separate)
                    videos = []
                    try:
                        tmdb_episode_info = {}
                        if tmdb_data and tmdb_data.get("id"):
                            tmdb_episode_info = await fetch_tmdb_italian_episodes(str(tmdb_data["id"]), anime_poster)
                        ep_data = await kitsu_api(
                            f"anime/{kitsu_id}/episodes",
                            {"page[limit]": 500, "sort": "number"}
                        )
                        eps = ep_data.get("data", [])
                        for ep in eps:
                            ep_attrs = ep.get("attributes", {}) or {}
                            ep_num = ep_attrs.get("number") or 0
                            if not ep_num: continue
                            ep_titles = ep_attrs.get("titles", {}) or {}
                            title = (ep_titles.get("it") or ep_titles.get("en_us") or
                                    ep_titles.get("en") or ep_attrs.get("canonicalTitle") or
                                    f"Episodio {ep_num}")
                            air_date = ep_attrs.get("airdate", "")
                            thumb = ep_attrs.get("thumbnail", {})
                            thumbnail = thumb.get("original") if thumb else anime_poster
                            ep_synopsis = ep_attrs.get("synopsis", "")
                            tmdb_ep = tmdb_episode_info.get(ep_num, {})
                            if tmdb_ep:
                                if tmdb_ep.get("title") and not looks_english(tmdb_ep["title"]):
                                    title = tmdb_ep["title"]
                                if tmdb_ep.get("overview") and not looks_english(tmdb_ep["overview"]):
                                    ep_synopsis = tmdb_ep["overview"]
                                if tmdb_ep.get("thumbnail"):
                                    thumbnail = tmdb_ep["thumbnail"]
                                if tmdb_ep.get("air_date"):
                                    air_date = tmdb_ep["air_date"]
                            if ep_num <= MAX_TRANSLATED_EPISODES:
                                if looks_english(title):
                                    title = await translate_anime_episode_title(title, f"kitsu:{kitsu_id}:{ep_num}")
                                synopsis = await ensure_anime_description_italian(ep_synopsis, f"episode:kitsu:{kitsu_id}:{ep_num}")
                            else:
                                title = await anime_episode_title_cached_or_generic(title, ep_num, f"kitsu:{kitsu_id}:{ep_num}")
                                synopsis = await anime_description_cached_or_blank(ep_synopsis, f"episode:kitsu:{kitsu_id}:{ep_num}")
                            videos.append({
                                "id": f"{item_id}:{ep_num}",
                                "title": title,
                                "season": tmdb_ep.get("season", 1),
                                "episode": tmdb_ep.get("episode", ep_num),
                                "overview": synopsis,
                                "thumbnail": thumbnail or anime_poster,
                                "released": f"{air_date}T00:00:00.000Z" if air_date else "",
                                "type": "episode",
                            })
                    except:
                        # Fallback: genera episodi semplici
                        if ep_count:
                            for i in range(1, min(ep_count + 1, 200)):
                                videos.append({
                                    "id": f"{item_id}:{i}",
                                    "title": f"Episodio {i}",
                                    "season": 1, "episode": i,
                                    "type": "episode",
                                })

                    meta_result = {
                        "id": item_id,
                        "type": media_type or "series",
                        "name": anime_name,
                        "description": anime_desc,
                        "poster": anime_poster,
                        "background": anime_cover,
                        "releaseInfo": release_info,
                        "imdbRating": str(round(float(anime_rating)/10, 1)) if anime_rating else None,
                        "genres": ["Anime"],
                    }
                    if videos: meta_result["videos"] = videos
                    return JSONResponse({"meta": meta_result})
        except Exception as e:
            print(f"[META] Kitsu error: {e}")
        return JSONResponse({"meta": {}})

    tmdb_type = "movie" if media_type == "movie" else "tv"
    tmdb_id = None
    imdb_id = None

    # Ricava TMDB id
    if item_id.startswith("tt"):
        imdb_id = item_id
        find = await tmdb_get(f"/find/{imdb_id}", {"external_source": "imdb_id"})
        res = find.get("movie_results") or find.get("tv_results") or []
        if res: tmdb_id = res[0].get("id")
    elif item_id.startswith("tmdb:"):
        tmdb_id = item_id.split(":")[1]
        imdb_id = item_id

    if not tmdb_id:
        print(f"[META] tmdb_id non trovato per {item_id}")
        return JSONResponse({"meta": {}})

    # Fetch parallelo: info + credits + videos
    d, credits, videos = await asyncio.gather(
        tmdb_get_with_fallback(f"/{tmdb_type}/{tmdb_id}"),
        tmdb_get(f"/{tmdb_type}/{tmdb_id}/credits"),
        tmdb_get(f"/{tmdb_type}/{tmdb_id}/videos"),
    )

    if not d:
        print(f"[META] TMDB non ha risposto per {tmdb_id}")
        return JSONResponse({"meta": {}})

    name = d.get("title") or d.get("name", "")
    poster = f"{TMDB_POSTER}{d['poster_path']}" if d.get("poster_path") else None
    background = f"{TMDB_ORIG}{d['backdrop_path']}" if d.get("backdrop_path") else None
    description = d.get("overview", "")
    genres = [g["name"] for g in d.get("genres", [])]
    rating = str(round(d.get("vote_average", 0), 1)) if d.get("vote_average") else None

    # Release info
    release = d.get("release_date") or d.get("first_air_date", "")
    release_info = release[:4] if release else ""
    if media_type == "series":
        end = (d.get("last_air_date") or "")[:4]
        status = d.get("status", "")
        if status in ("Ended", "Canceled") and end:
            release_info = f"{release_info}–{end}"
        elif release_info:
            release_info = f"{release_info}–"

    # Cast e registi
    cast = [p["name"] for p in credits.get("cast", [])[:10]]
    directors = [p["name"] for p in credits.get("crew", []) if p.get("job") in ("Director", "Series Director")]

    trailer_cache_key = f"trailer_it_only:{tmdb_type}:{tmdb_id}"
    trailer = cache_get(trailer_cache_key)
    if not trailer:
        # Solo trailer italiani: prima TMDB in italiano, poi YouTube con query italiana.
        trailer = pick_tmdb_italian_trailer(videos)
        if not trailer:
            trailer = await search_youtube_trailer(name, release[:4] if release else None)
        if trailer:
            cache_set(trailer_cache_key, trailer, ttl=14 * 24 * 60 * 60)

    trailer_yt_id = youtube_id_from_trailer(trailer)

    meta_obj = {
        "id": imdb_id or item_id,
        "type": media_type,
        "name": name,
        "description": description,
        "poster": poster,
        "background": background,
        "genres": genres,
        "releaseInfo": release_info,
        "imdbRating": rating,
        "cast": cast,
        "director": directors,
        "trailers": [{"source": trailer_yt_id, "type": "Trailer"}] if trailer_yt_id else [],
        "trailerStreams": [{"ytId": trailer_yt_id}] if trailer_yt_id else [],
        "trailer": trailer_yt_id,
    }

    # Episodi per le serie
    if media_type == "series":
        seasons_list = [s for s in d.get("seasons", []) if s.get("season_number", 0) > 0]

        async def fetch_season(s_num):
            return s_num, await tmdb_get(f"/{tmdb_type}/{tmdb_id}/season/{s_num}")

        seasons_data = await asyncio.gather(*[fetch_season(s["season_number"]) for s in seasons_list[:15]])

        ep_list = []
        for s_num, season in sorted(seasons_data):
            if not season: continue
            for ep in season.get("episodes", []):
                ep_num = ep.get("episode_number", 0)
                air_date = ep.get("air_date", "")
                still = f"{TMDB_ORIG}{ep['still_path']}" if ep.get("still_path") else poster
                ep_list.append({
                    "id": f"{imdb_id or item_id}:{s_num}:{ep_num}",
                    "title": ep.get("name") or f"Episodio {ep_num}",
                    "season": s_num,
                    "episode": ep_num,
                    "overview": ep.get("overview", ""),
                    "thumbnail": still,
                    "released": f"{air_date}T00:00:00.000Z" if air_date else "",
                    "type": "episode",
                })
        if ep_list: meta_obj["videos"] = ep_list

    yt_key = bool(os.environ.get("YOUTUBE_API_KEY", ""))
    print(f"[META] OK: {name} | poster={bool(poster)} | episodes={len(meta_obj.get('videos', []))} | trailer={bool(trailer)} | yt_key={yt_key} | overview_len={len(description)}")
    return JSONResponse({"meta": meta_obj})
