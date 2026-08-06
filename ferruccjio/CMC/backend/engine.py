"""
CMC Terminal Pro — Backend Engine (Identical Mechanism to Python CLI Edition v8)
Real-Time WebSocket Streaming (1000+ coins), HTTPS Connection Pool, 3-Tier Caching,
OHLCV Aggregator, Persistent Alert Engine, Italian Translator & Snapshot Exporters.
"""

import os
import sys
import time
import json
import gzip
import zlib
import queue
import threading
import urllib.request
import urllib.parse
import http.client as _http
import csv
import io
import re
import gc
import hashlib
from datetime import datetime
from collections import defaultdict, deque, OrderedDict
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, List, Any, Tuple, Set

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION & CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

WS_URL = "wss://push.coinmarketcap.com/ws"
CHAN_5S = "main-site@crypto_price_5s@{}@normal"
CHAN_15S = "main-site@crypto_price_15s@{}@normal"
_USD_CONVERT_ID = 2781

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/150.0.0.0 Safari/537.36"),
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://coinmarketcap.com/",
    "Origin": "https://coinmarketcap.com",
    "Connection": "keep-alive",
    "Platform": "web",
}

WS_HEADERS = [
    "Origin: https://coinmarketcap.com",
    "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
]

DEFAULT_IDS = [
    1, 1027, 825, 1839, 5426, 52, 3408, 74, 2010, 5805,
    5994, 1958, 11419, 6636, 5176, 20396, 24478, 21794, 30171,
    1975, 3794, 1831, 2, 328, 4030, 1697, 3717, 4642, 1518, 3635,
]

COIN_META: Dict[int, Tuple[str, str]] = {
    1:("BTC","Bitcoin"), 1027:("ETH","Ethereum"), 825:("USDT","Tether"),
    1839:("BNB","BNB"), 5426:("SOL","Solana"), 52:("XRP","XRP"),
    3408:("USDC","USD Coin"), 74:("DOGE","Dogecoin"), 2010:("ADA","Cardano"),
    5805:("AVAX","Avalanche"), 5994:("SHIB","Shiba Inu"), 1958:("TRX","TRON"),
    11419:("TON","Toncoin"), 6636:("DOT","Polkadot"), 5176:("APT","Aptos"),
    20396:("SUI","Sui"), 24478:("PEPE","Pepe"), 21794:("WLD","Worldcoin"),
    30171:("ONDO","Ondo"), 1975:("LINK","Chainlink"), 3794:("ATOM","Cosmos"),
    1831:("BCH","Bitcoin Cash"), 2:("LTC","Litecoin"), 328:("XMR","Monero"),
    4030:("ALGO","Algorand"), 1697:("BAT","Basic Attention"),
    3717:("WBTC","Wrapped BTC"), 4642:("HBAR","Hedera"),
    1518:("MKR","Maker"), 3635:("CRO","Cronos"), 28301:("INJ","Injective")
}

SYMBOL_TO_ID: Dict[str, int] = {sym.upper(): cid for cid, (sym, _) in COIN_META.items()}

# Cache file paths
_CACHE_DIR = Path.home() / ".cmc_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_UNIVERSE_CACHE_FILE = _CACHE_DIR / "universe_cache.json"
_ALERTS_FILE = _CACHE_DIR / "alerts_v2.json"
_TRANSLATION_CACHE_FILE = _CACHE_DIR / "translations.json"
_CANDLE_CACHE_DIR = _CACHE_DIR / "candles"
_CANDLE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Centralized thread pool for async fetching
FETCH_EXECUTOR = ThreadPoolExecutor(max_workers=10, thread_name_prefix="cmc-fetch")
_UNIVERSE_LOADED = threading.Event()
_UNIVERSE_LOCK = threading.RLock()

# ══════════════════════════════════════════════════════════════════════════════
# HTTPS CONNECTION POOL (KEEP-ALIVE + REUSE)
# ══════════════════════════════════════════════════════════════════════════════

class _ConnectionPool:
    """Pool di connessioni HTTPS keep-alive verso api.coinmarketcap.com con controllo scadenza socket."""
    def __init__(self, host: str = "api.coinmarketcap.com", size: int = 10, timeout: float = 10.0):
        self.host = host
        self.size = size
        self.timeout = timeout
        self._pool = queue.LifoQueue(maxsize=size)
        self._lock = threading.Lock()
        self._created = 0

    def _new_conn(self):
        return _http.HTTPSConnection(self.host, timeout=self.timeout)

    def acquire(self):
        while True:
            try:
                conn, ts = self._pool.get_nowait()
                if time.time() - ts > 12.0:
                    try: conn.close()
                    except Exception: pass
                    with self._lock:
                        self._created = max(0, self._created - 1)
                    continue
                return conn
            except queue.Empty:
                break

        with self._lock:
            if self._created < self.size:
                self._created += 1
                return self._new_conn()
        try:
            conn, ts = self._pool.get(timeout=self.timeout)
            if time.time() - ts > 12.0:
                try: conn.close()
                except Exception: pass
                with self._lock:
                    self._created = max(0, self._created - 1)
                return self._new_conn()
            return conn
        except queue.Empty:
            return self._new_conn()

    def release(self, conn, broken=False):
        if broken or not conn:
            try: conn.close()
            except Exception: pass
            with self._lock:
                self._created = max(0, self._created - 1)
            return
        try:
            self._pool.put_nowait((conn, time.time()))
        except queue.Full:
            try: conn.close()
            except Exception: pass

CMC_POOL = _ConnectionPool("api.coinmarketcap.com", size=10)

def _http_get_json(path: str, timeout: float = 10.0) -> dict:
    """GET verso api.coinmarketcap.com con connection reuse, controllo scadenza, gzip/deflate e fallback urllib."""
    for attempt in range(3):
        conn = CMC_POOL.acquire()
        try:
            conn.request("GET", path, headers=HEADERS)
            resp = conn.getresponse()
            raw = resp.read()
            if resp.getheader("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            elif resp.getheader("Content-Encoding") == "deflate":
                raw = zlib.decompress(raw)

            if resp.status != 200:
                CMC_POOL.release(conn, broken=True)
                continue

            data = json.loads(raw.decode("utf-8"))
            CMC_POOL.release(conn, broken=False)
            return data
        except Exception:
            CMC_POOL.release(conn, broken=True)
            continue

    try:
        url = f"https://api.coinmarketcap.com{path}"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            elif resp.getheader("Content-Encoding") == "deflate":
                raw = zlib.decompress(raw)
            return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    return {}

# ══════════════════════════════════════════════════════════════════════════════
# LRU CACHE & DISK CACHE
# ══════════════════════════════════════════════════════════════════════════════

class _LRUDict:
    """Dict con limite massimo (LRU: evict del meno usato)."""
    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self._data = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key, default=None):
        with self._lock:
            if key not in self._data: return default
            self._data.move_to_end(key)
            return self._data[key]

    def put(self, key, value):
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self._data[key] = value
            else:
                self._data[key] = value
                if len(self._data) > self.maxsize:
                    self._data.popitem(last=False)

    def pop(self, key, default=None):
        with self._lock: return self._data.pop(key, default)
    def __contains__(self, key):
        with self._lock: return key in self._data
    def __len__(self):
        with self._lock: return len(self._data)
    def keys(self):
        with self._lock: return list(self._data.keys())
    def items(self):
        with self._lock: return list(self._data.items())
    def clear(self):
        with self._lock: self._data.clear()

class _DiskCache:
    """Cache persistente su disco per candele e dati pesanti."""
    def __init__(self):
        self._lock = threading.Lock()

    def get(self, key: str, max_age_sec: int) -> Tuple[Optional[Any], float]:
        path = _CANDLE_CACHE_DIR / f"{key}.json"
        if not path.exists(): return None, 0.0
        try:
            with self._lock:
                stat = path.stat()
                age = time.time() - stat.st_mtime
                if age > max_age_sec: return None, 0.0
                data = json.loads(path.read_text(encoding="utf-8"))
                return data, stat.st_mtime
        except Exception: return None, 0.0

    def put(self, key: str, data: Any, ttl_sec: int = 3600):
        path = _CANDLE_CACHE_DIR / f"{key}.json"
        try:
            with self._lock:
                path.write_text(json.dumps(data), encoding="utf-8")
        except Exception: pass

    def cleanup(self, max_age_sec: int = 86400 * 3):
        try:
            now = time.time()
            for p in _CANDLE_CACHE_DIR.glob("*.json"):
                if now - p.stat().st_mtime > max_age_sec:
                    try: p.unlink()
                    except Exception: pass
        except Exception: pass

DISK_CACHE = _DiskCache()

# ══════════════════════════════════════════════════════════════════════════════
# SNAPSHOT MANAGER & QUOTE STORE
# ══════════════════════════════════════════════════════════════════════════════

class _SnapshotManager:
    """Ottimizza refresh_snapshot via dirty flag."""
    def __init__(self):
        self._dirty = threading.Event()
        self._dirty.set()
        self._last_refresh = 0.0

    def mark_dirty(self):
        self._dirty.set()

    def refresh_if_needed(self, store, min_interval=0.05):
        now = time.time()
        if not self._dirty.is_set(): return False
        if now - self._last_refresh < min_interval: return False
        store.refresh_snapshot()
        self._last_refresh = now
        self._dirty.clear()
        return True

SNAP_MGR = _SnapshotManager()

class QuoteStore:
    """Store ad alte prestazioni: writes locked, reads su snapshot immutabile con flash detection."""
    def __init__(self):
        self._data: Dict[int, dict] = {}
        self._snapshot: Dict[int, dict] = {}
        self._lock = threading.RLock()
        self._updates = 0
        self._last_update = 0.0
        self._msg_history = deque(maxlen=120)
        self._change_flags: Dict[int, Tuple[float, int]] = {}
        self.start_time = time.time()
        self.connected = False
        self.reconnects = 0

    def upsert(self, quote: dict):
        cid = quote.get("id")
        if cid is None: return

        # Inject symbol and name if missing
        if not quote.get("symbol") or not quote.get("name"):
            meta_sym, meta_name = COIN_META.get(cid, (f"#{cid}", f"Asset #{cid}"))
            if not quote.get("symbol"): quote["symbol"] = meta_sym
            if not quote.get("name"): quote["name"] = meta_name

        with self._lock:
            existing = self._data.get(cid)
            new_ts = quote.get("t", int(time.time() * 1000))
            quote["t"] = new_ts

            if existing:
                old_p = existing.get("p")
                merged = {**existing, **quote}
                self._data[cid] = merged
                new_p = merged.get("p")
                if old_p is not None and new_p is not None and abs(old_p - new_p) > 1e-10:
                    self._change_flags[cid] = (time.time(), 1 if new_p > old_p else -1)
            else:
                self._data[cid] = quote

            self._updates += 1
            self._last_update = time.time()
            self._msg_history.append(self._last_update)

            # Cap max items
            if len(self._data) > 2500:
                sorted_items = sorted(self._data.items(), key=lambda kv: kv[1].get("t", 0))
                for del_cid, _ in sorted_items[:500]:
                    self._data.pop(del_cid, None)
                    self._change_flags.pop(del_cid, None)

        SNAP_MGR.mark_dirty()
        # Feed candle engines
        _feed_candles(quote)
        # Check unknown IDs
        if cid not in COIN_META:
            _register_unknown_id(cid)

    def refresh_snapshot(self):
        with self._lock:
            self._snapshot = {k: dict(v) for k, v in self._data.items()}

    def snapshot(self) -> Dict[int, dict]:
        with self._lock: return dict(self._data)

    def get_coin(self, cid: int) -> Optional[dict]:
        with self._lock:
            return dict(self._data[cid]) if cid in self._data else None

    def flash_direction(self, cid: int) -> Optional[int]:
        flag = self._change_flags.get(cid)
        if not flag: return None
        ts, direction = flag
        if time.time() - ts < 1.5:
            return direction
        return None

    @property
    def msg_per_sec(self) -> float:
        now = time.time()
        recent = [t for t in self._msg_history if now - t < 5.0]
        return len(recent) / 5.0 if recent else 0.0

    @property
    def uptime(self) -> float:
        return time.time() - self.start_time

STORE = QuoteStore()

# ══════════════════════════════════════════════════════════════════════════════
# UNIVERSE LOADER & UNKNOWN ID RESOLVER
# ══════════════════════════════════════════════════════════════════════════════

_UNKNOWN_IDS_SEEN = set()
_UNKNOWN_LOCK = threading.Lock()

def _register_unknown_id(cid: int):
    """Se arriva un ID via WS che non conosciamo, prova a risolverlo al volo."""
    if cid in COIN_META: return
    with _UNKNOWN_LOCK:
        if cid in _UNKNOWN_IDS_SEEN: return
        _UNKNOWN_IDS_SEEN.add(cid)

    def _resolve():
        try:
            path = f"/data-api/v3/cryptocurrency/detail/lite?id={cid}"
            payload = _http_get_json(path, timeout=5.0)
            data = payload.get("data") or {}
            sym = data.get("symbol")
            nm = data.get("name")
            if sym:
                with _UNIVERSE_LOCK:
                    COIN_META[cid] = (sym, nm or "")
                    SYMBOL_TO_ID[sym.upper()] = cid
        except Exception: pass
    FETCH_EXECUTOR.submit(_resolve)

def _load_universe_from_disk() -> dict:
    try:
        if _UNIVERSE_CACHE_FILE.exists():
            data = json.loads(_UNIVERSE_CACHE_FILE.read_text(encoding="utf-8"))
            if time.time() - data.get("saved_at", 0) < 86400 * 3:
                return {int(k): tuple(v) for k, v in data.get("coins", {}).items()}
    except Exception: pass
    return {}

def _save_universe_to_disk(coins: dict):
    try:
        _UNIVERSE_CACHE_FILE.write_text(json.dumps({
            "saved_at": int(time.time()),
            "coins": {str(k): list(v) for k, v in coins.items()},
        }), encoding="utf-8")
    except Exception: pass

def load_full_coin_universe(async_refresh: bool = True):
    """Carica il coin universe: dal disco istantaneamente, poi in background dalla rete (1500+ coin)."""
    global COIN_META, SYMBOL_TO_ID

    disk = _load_universe_from_disk()
    if disk:
        with _UNIVERSE_LOCK:
            for cid, meta in disk.items():
                if cid not in COIN_META:
                    COIN_META[cid] = meta
            SYMBOL_TO_ID.clear()
            SYMBOL_TO_ID.update({sym.upper(): cid for cid, (sym, _) in COIN_META.items()})
        _UNIVERSE_LOADED.set()

    def _refresh_worker():
        try:
            fresh = {}
            for offset in [1, 501, 1001]:
                path = ("/data-api/v3/cryptocurrency/listing?" +
                        urllib.parse.urlencode({
                            "start": offset, "limit": 500,
                            "sortBy": "market_cap", "sortType": "desc",
                            "convert": "USD", "cryptoType": "all", "tagType": "all",
                        }))
                payload = _http_get_json(path, timeout=15.0)
                if not payload: break
                
                now_ms = int(time.time() * 1000)
                for c in payload.get("data", {}).get("cryptoCurrencyList", []):
                    cid = c.get("id")
                    sym = c.get("symbol")
                    nm = c.get("name")
                    if not cid or not sym: continue
                    fresh[int(cid)] = (sym, nm or "")
                    
                    quotes = c.get("quotes", [])
                    q = quotes[0] if quotes else {}
                    STORE.upsert({
                        "id": int(cid), "symbol": sym, "name": nm or "",
                        "slug": c.get("slug", ""),
                        "rank": c.get("cmcRank") or c.get("rank"),
                        "p": q.get("price"),
                        "p1h": q.get("percentChange1h"),
                        "p24h": q.get("percentChange24h"),
                        "p7d": q.get("percentChange7d"),
                        "p30d": q.get("percentChange30d"),
                        "v24h": q.get("volume24h"),
                        "mc": q.get("marketCap"),
                        "fdv": q.get("fullyDilluttedMarketCap") or q.get("fullyDilutedMarketCap"),
                        "circ_supply": c.get("circulatingSupply"),
                        "total_supply": c.get("totalSupply"),
                        "max_supply": c.get("maxSupply"),
                        "dominance": q.get("marketCapDominance"),
                        "tags": c.get("tags", []),
                        "t": now_ms
                    })
            if fresh:
                with _UNIVERSE_LOCK:
                    COIN_META.update(fresh)
                    SYMBOL_TO_ID.clear()
                    SYMBOL_TO_ID.update({sym.upper(): cid for cid, (sym, _) in COIN_META.items()})
                _save_universe_to_disk(COIN_META)
        except Exception as e:
            print(f"[Universe Loader] Error: {e}", file=sys.stderr)
        finally:
            _UNIVERSE_LOADED.set()

    if async_refresh:
        FETCH_EXECUTOR.submit(_refresh_worker)
    else:
        _refresh_worker()

# ══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET STREAMING ENGINE & REST POLLING BACKUP
# ══════════════════════════════════════════════════════════════════════════════

try:
    import websocket
except ImportError:
    websocket = None

class ConnState:
    def __init__(self):
        self.connected = False
        self.reconnects = 0
        self.connected_at = 0.0
        self.subscribed = 0
        self.error = ""

STATE = ConnState()

class Socket:
    def __init__(self, url, sub, unsub, ping=None, cb=None):
        self.url, self.sub, self.unsub, self.ping, self.cb = url, sub, unsub, ping, cb
        self._ws = None
        self._alive = True
        self._conn = False

    def _keepalive(self):
        while self._alive and self._conn:
            time.sleep(20)
            try:
                if self.ping and self._ws: self._ws.send(json.dumps(self.ping))
            except Exception: break

    def _on_open(self, ws):
        self._conn = True
        STATE.connected = True
        STORE.connected = True
        STATE.connected_at = time.time()
        try: ws.send(json.dumps(self.sub))
        except Exception: pass
        if self.ping:
            threading.Thread(target=self._keepalive, daemon=True).start()

    def _on_msg(self, ws, raw):
        try:
            msg = json.loads(raw)
            d, t = msg.get("d"), msg.get("t")
            if d and t and self.cb:
                self.cb({**d, "t": int(t)})
        except Exception: pass

    def _on_close(self, ws, code, msg):
        self._conn = False
        STATE.connected = False
        STORE.connected = False

    def _on_err(self, ws, err):
        STATE.error = str(err)[:60]

    def start(self):
        if not websocket: return
        def loop():
            while self._alive:
                try:
                    self._ws = websocket.WebSocketApp(
                        self.url, header=WS_HEADERS,
                        on_open=self._on_open, on_message=self._on_msg,
                        on_error=self._on_err, on_close=self._on_close,
                    )
                    self._ws.run_forever(ping_interval=25, ping_timeout=10, skip_utf8_validation=True)
                except Exception: pass
                if self._alive:
                    STATE.reconnects += 1
                    STORE.reconnects += 1
                    time.sleep(3)
        threading.Thread(target=loop, daemon=True).start()

    def stop(self):
        self._alive = False
        try:
            if self._ws:
                self._ws.send(json.dumps(self.unsub))
                self._ws.close()
        except Exception: pass

def chunk_ids(ids, size=200):
    for i in range(0, len(ids), size):
        yield ids[i:i+size]

def start_streaming_max(ids=None, subscribe_top_n: int = 1000):
    """Sottoscrive TUTTE le coin possibili via WebSocket (fino a 1000) per tempo reale."""
    ids = list(ids or [])
    _UNIVERSE_LOADED.wait(timeout=3.0)

    with _UNIVERSE_LOCK:
        all_ids = list(COIN_META.keys())

    seen = set()
    ordered = []
    for i in ids:
        if i not in seen: ordered.append(i); seen.add(i)
    for i in DEFAULT_IDS:
        if i not in seen: ordered.append(i); seen.add(i)
    for i in all_ids[:subscribe_top_n]:
        if i not in seen: ordered.append(i); seen.add(i)

    ordered = ordered[:subscribe_top_n]
    url = f"{WS_URL}?device=web&client_source=home_page"
    sockets = []

    if websocket:
        for chunk in chunk_ids(ordered):
            params = [CHAN_5S, ",".join(str(i) for i in chunk)]
            s = Socket(
                url,
                sub={"method": "RSUBSCRIPTION", "params": params},
                unsub={"method": "R_UNSUBSCRIPTION", "params": params},
                ping={"method": "PING", "id": "0"},
                cb=STORE.upsert,
            )
            s.start()
            sockets.append(s)

            params2 = [CHAN_15S, ",".join(str(i) for i in chunk)]
            s2 = Socket(
                url,
                sub={"method": "RSUBSCRIPTION", "params": params2},
                unsub={"method": "R_UNSUBSCRIPTION", "params": params2},
                cb=STORE.upsert,
            )
            s2.start()
            sockets.append(s2)
        STATE.subscribed = len(ordered)

    # Avvia anche un polling REST di backup ogni 10 secondi
    def _rest_backup_loop():
        while True:
            try:
                path = ("/data-api/v3/cryptocurrency/listing?" +
                        urllib.parse.urlencode({"start": 1, "limit": 250, "sortBy": "market_cap", "sortType": "desc", "convert": "USD"}))
                payload = _http_get_json(path, timeout=10.0)
                now_ms = int(time.time() * 1000)
                if payload:
                    for c in payload.get("data", {}).get("cryptoCurrencyList", []):
                        cid = c.get("id")
                        if not cid: continue
                        quotes = c.get("quotes", [])
                        q = quotes[0] if quotes else {}
                        STORE.upsert({
                            "id": int(cid), "symbol": c.get("symbol", ""), "name": c.get("name", ""),
                            "slug": c.get("slug", ""), "rank": c.get("cmcRank") or c.get("rank"),
                            "p": q.get("price"), "p1h": q.get("percentChange1h"), "p24h": q.get("percentChange24h"),
                            "p7d": q.get("percentChange7d"), "p30d": q.get("percentChange30d"),
                            "v24h": q.get("volume24h"), "mc": q.get("marketCap"),
                            "circ_supply": c.get("circulatingSupply"), "total_supply": c.get("totalSupply"),
                            "max_supply": c.get("maxSupply"), "dominance": q.get("marketCapDominance"),
                            "tags": c.get("tags", []), "t": now_ms
                        })
                    STORE.connected = True
            except Exception: pass
            time.sleep(10.0)

    threading.Thread(target=_rest_backup_loop, daemon=True).start()
    return sockets

# ══════════════════════════════════════════════════════════════════════════════
# CANDLE ENGINE & HISTORICAL FETCHER WITH 3-TIER CACHING
# ══════════════════════════════════════════════════════════════════════════════

TF_CONFIG = {
    "1m":  {"range": "1D",  "interval": "1m",  "label": "1 Minuto",   "days": 1,   "sec": 60},
    "5m":  {"range": "7D",  "interval": "5m",  "label": "5 Minuti",   "days": 7,   "sec": 300},
    "15m": {"range": "1M",  "interval": "15m", "label": "15 Minuti",  "days": 30,  "sec": 900},
    "1h":  {"range": "3M",  "interval": "1h",  "label": "1 Ora",      "days": 90,  "sec": 3600},
    "4h":  {"range": "1Y",  "interval": "4h",  "label": "4 Ore",      "days": 365, "sec": 14400},
    "1d":  {"range": "ALL", "interval": "1d",  "label": "1 Giorno",   "days": 3650,"sec": 86400},
}
TF_ORDER = ["1m", "5m", "15m", "1h", "4h", "1d"]

class CandleEngine:
    """Aggrega tick live in candele OHLCV e geocodifica i bucket."""
    def __init__(self, timeframe_sec=60, max_history=300):
        self.timeframe = timeframe_sec
        self.max_history = max_history
        self.candles = defaultdict(lambda: deque(maxlen=max_history))
        self.current = {}
        self._lock = threading.RLock()

    def tick(self, cid, price, ts_ms, volume=0):
        if price is None: return
        bucket = (ts_ms // 1000 // self.timeframe) * self.timeframe
        with self._lock:
            cur = self.current.get(cid)
            if cur is None or cur["bucket"] != bucket:
                if cur is not None:
                    self.candles[cid].append(cur)
                self.current[cid] = {
                    "bucket": bucket, "t": bucket * 1000,
                    "o": price, "h": price, "l": price, "c": price,
                    "v": volume or 0, "n": 1,
                }
            else:
                cur["h"] = max(cur["h"], price)
                cur["l"] = min(cur["l"], price)
                cur["c"] = price
                cur["v"] = max(cur["v"], volume or 0)
                cur["n"] += 1

    def get(self, cid, limit=100):
        with self._lock:
            hist = list(self.candles.get(cid, []))
            cur = self.current.get(cid)
            if cur is not None:
                hist = hist + [dict(cur)]
        return hist[-limit:]

    def all_current(self):
        with self._lock: return dict(self.current)

CANDLES_1M  = CandleEngine(timeframe_sec=60, max_history=400)
CANDLES_5M  = CandleEngine(timeframe_sec=300, max_history=400)
CANDLES_15M = CandleEngine(timeframe_sec=900, max_history=400)
CANDLES_1H  = CandleEngine(timeframe_sec=3600, max_history=400)
CANDLES_4H  = CandleEngine(timeframe_sec=14400, max_history=400)
CANDLES_1D  = CandleEngine(timeframe_sec=86400, max_history=400)

def _feed_candles(quote):
    cid = quote.get("id")
    p = quote.get("p")
    v = quote.get("v24h")
    t = quote.get("t")
    if cid and p and t:
        CANDLES_1M.tick(cid, p, t, v)
        CANDLES_5M.tick(cid, p, t, v)
        CANDLES_15M.tick(cid, p, t, v)
        CANDLES_1H.tick(cid, p, t, v)
        CANDLES_4H.tick(cid, p, t, v)
        CANDLES_1D.tick(cid, p, t, v)

_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT = {}
_HIST_CACHE = _LRUDict(200)
_HIST_LOCK = threading.RLock()
_HIST_LOADING = set()

_TTL_BY_TF = {"1m": 30, "5m": 120, "15m": 300, "1h": 900, "4h": 3600, "1d": 14400}

def _cache_key(cid: int, tf: str) -> str: return f"c{cid}_{tf}"

def _fetch_and_parse(cid: int, tf: str) -> list:
    cfg = TF_CONFIG.get(tf)
    if not cfg: return []
    now_s = int(time.time())
    start_s = now_s - cfg["days"] * 86400

    path = ("/data-api/v3.1/cryptocurrency/historical?" +
            urllib.parse.urlencode({
                "id": cid, "convertId": _USD_CONVERT_ID,
                "timeStart": start_s, "timeEnd": now_s, "interval": cfg["interval"],
            }))
    payload = _http_get_json(path)
    quotes = payload.get("data", {}).get("quotes", []) if payload else []
    candles = []

    if not quotes and tf in ("1m", "5m", "15m", "1h"):
        rng = "1D" if tf in ("1m", "5m") else ("7D" if tf == "15m" else "1M")
        chart_path = f"/data-api/v3/cryptocurrency/detail/chart?id={cid}&range={rng}"
        chart_payload = _http_get_json(chart_path)
        points = chart_payload.get("data", {}).get("points", {}) if chart_payload else {}
        if points:
            sorted_keys = sorted([int(k) for k in points.keys()])
            prev_p = None
            for k in sorted_keys:
                pt = points[str(k)]
                v_arr = pt.get("v", [])
                if not v_arr: continue
                p = float(v_arr[0])
                vol = float(v_arr[1]) if len(v_arr) > 1 else 0.0
                o = prev_p if prev_p is not None else p
                h = max(o, p) * 1.0005
                l = min(o, p) * 0.9995
                candles.append({"t": k * 1000, "o": o, "h": h, "l": l, "c": p, "v": vol, "n": 1})
                prev_p = p
            if candles:
                return candles

    for q in quotes:
        quote = q.get("quote") or {}
        t_open = q.get("timeOpen") or quote.get("timestamp")
        if not t_open: continue
        try:
            if isinstance(t_open, str):
                dt = datetime.fromisoformat(t_open.replace("Z", "+00:00"))
                ts_ms = int(dt.timestamp() * 1000)
            else:
                ts_ms = int(t_open)
        except Exception: continue

        o = quote.get("open"); h = quote.get("high")
        lo = quote.get("low"); cl = quote.get("close")
        if None in (o, h, lo, cl): continue
        candles.append({"t": ts_ms, "o": o, "h": h, "l": lo, "c": cl, "v": quote.get("volume") or 0, "n": 0})

    candles.sort(key=lambda c: c["t"])
    return candles

def get_historical_candles_fast(cid: int, tf: str, max_age_sec: int = None):
    key = _cache_key(cid, tf)
    ttl = max_age_sec if max_age_sec is not None else _TTL_BY_TF.get(tf, 300)
    now = time.time()

    with _HIST_LOCK:
        cached = _HIST_CACHE.get(key)
        if cached and (now - cached[1]) < ttl:
            return cached[0]

    disk_data, disk_stored = DISK_CACHE.get(key, ttl)
    if disk_data:
        with _HIST_LOCK:
            _HIST_CACHE.put(key, (disk_data, now))
        if time.time() - disk_stored > ttl // 2:
            _schedule_fetch(cid, tf, priority=False)
        return disk_data

    _schedule_fetch(cid, tf, priority=True)
    return None

def _schedule_fetch(cid: int, tf: str, priority: bool = True):
    key = _cache_key(cid, tf)
    with _INFLIGHT_LOCK:
        if key in _INFLIGHT and not _INFLIGHT[key].done():
            return _INFLIGHT[key]
        _HIST_LOADING.add((cid, tf))

    def _worker():
        try:
            candles = _fetch_and_parse(cid, tf)
            now = time.time()
            with _HIST_LOCK:
                _HIST_CACHE.put(key, (candles, now))
            if candles:
                DISK_CACHE.put(key, candles, ttl_sec=_TTL_BY_TF.get(tf, 300) * 4)
        except Exception: pass
        finally:
            with _HIST_LOCK: _HIST_LOADING.discard((cid, tf))
            with _INFLIGHT_LOCK: _INFLIGHT.pop(key, None)

    future = FETCH_EXECUTOR.submit(_worker)
    with _INFLIGHT_LOCK: _INFLIGHT[key] = future
    return future

def is_loading_history_fast(cid: int, tf: str) -> bool:
    with _HIST_LOCK: return (cid, tf) in _HIST_LOADING

def merge_live_with_history(cid: int, historical: list, tf: str) -> list:
    if not historical: return historical or []
    engines = {
        "1m": CANDLES_1M, "5m": CANDLES_5M, "15m": CANDLES_15M,
        "1h": CANDLES_1H, "4h": CANDLES_4H, "1d": CANDLES_1D
    }
    live_engine = engines.get(tf)
    current = live_engine.all_current().get(cid) if live_engine else None

    if not current:
        q = STORE.get_coin(cid)
        if q and q.get("p"):
            cfg = TF_CONFIG.get(tf)
            if cfg:
                sec = cfg["sec"]
                now_ms = int(time.time() * 1000)
                bucket_ts = (now_ms // 1000 // sec) * sec * 1000
                p = q.get("p")
                current = {"t": bucket_ts, "o": p, "h": p, "l": p, "c": p, "v": q.get("v24h") or 0, "n": 1}

    if not current: return historical

    last_hist = historical[-1]
    if current["t"] > last_hist["t"]:
        return historical + [dict(current)]
    elif current["t"] == last_hist["t"]:
        merged = list(historical[:-1])
        merged.append({
            "t": last_hist["t"], "o": last_hist["o"],
            "h": max(last_hist["h"], current["h"]), "l": min(last_hist["l"], current["l"]),
            "c": current["c"], "v": max(last_hist["v"], current["v"]), "n": current["n"],
        })
        return merged
    return historical

class _CandleFacade:
    def get_candles(self, cid: int, tf: str, limit: int = 150) -> list:
        cloud_key = f"c{cid}_{tf}_db"
        hist = get_historical_candles_fast(cid, tf)
        if not hist:
            key = _cache_key(cid, tf)
            for _ in range(45):
                time.sleep(0.1)
                with _HIST_LOCK:
                    cached = _HIST_CACHE.get(key)
                    if cached:
                        hist = cached[0]
                        break
            if not hist:
                disk_data, _ = DISK_CACHE.get(key, 86400 * 30)
                if disk_data:
                    hist = disk_data
                    with _HIST_LOCK:
                        _HIST_CACHE.put(key, (hist, time.time()))
        if not hist:
            try:
                cloud_data = CLOUD_DB.download_dataset(cloud_key)
                if cloud_data and isinstance(cloud_data, dict):
                    hist = cloud_data.get("candles", [])
                    if hist:
                        with _HIST_LOCK:
                            _HIST_CACHE.put(_cache_key(cid, tf), (hist, time.time()))
            except Exception: pass

        if not hist:
            hist = []
        merged = merge_live_with_history(cid, hist, tf)
        seen = set()
        clean = []
        for c in sorted(merged, key=lambda x: x["t"]):
            if c["t"] not in seen:
                seen.add(c["t"])
                clean.append(c)
        if len(clean) >= 100:
            try: CLOUD_DB.auto_archive_async(cid, tf, clean)
            except Exception: pass
        return clean[-limit:]

CANDLES = _CandleFacade()

class _Prefetcher:
    def __init__(self):
        self._last_prefetch = {}
        self._debounce_sec = 2.0
    def _should_run(self, key):
        now = time.time()
        if now - self._last_prefetch.get(key, 0) < self._debounce_sec: return False
        self._last_prefetch[key] = now
        return True
    def prefetch_coin_all_tf(self, cid: int, exclude_tf: str = None):
        if not self._should_run(f"coin_{cid}"): return
        for tf in TF_ORDER:
            if tf != exclude_tf: _schedule_fetch(cid, tf, priority=False)
    def prefetch_top_list(self, coins, tf: str = "1h", n: int = 20):
        if not self._should_run(f"top_{tf}_{n}"): return
        for q in coins[:n]:
            if q.get("id"): _schedule_fetch(q["id"], tf, priority=False)
PREFETCHER = _Prefetcher()

# ══════════════════════════════════════════════════════════════════════════════
# DETAIL FETCHER & TRANSLATION ENGINE
# ══════════════════════════════════════════════════════════════════════════════

_DETAIL_CACHE = _LRUDict(150)
_DETAIL_LOCK = threading.RLock()
_DETAIL_LOADING = set()

TAG_TRANSLATIONS = {
    "marketplace": "marketplace", "centralized exchange": "exchange centralizzato",
    "centralized exchange (cex) token": "token exchange (CEX)", "payments": "pagamenti",
    "smart contracts": "smart contract", "layer 1": "layer 1", "layer 2": "layer 2",
    "defi": "DeFi", "meme": "meme coin", "gaming": "gaming", "nft": "NFT",
    "privacy": "privacy", "stablecoin": "stablecoin", "wallet": "wallet",
    "storage": "storage", "oracle": "oracolo", "governance": "governance",
    "yield farming": "yield farming", "cross-chain": "cross-chain",
    "web3": "Web3", "metaverse": "metaverso", "ai & big data": "IA e big data",
    "artificial intelligence": "intelligenza artificiale", "identity": "identità",
    "real world assets": "asset reali (RWA)", "sports": "sport", "social": "social",
    "collectibles-nfts": "collezionabili/NFT", "lending & borrowing": "prestiti",
    "derivatives": "derivati", "liquid staking": "liquid staking"
}

def translate_tag(tag_name: str) -> str:
    if not tag_name: return ""
    key = tag_name.lower().strip()
    if key in TAG_TRANSLATIONS: return TAG_TRANSLATIONS[key]
    for suffix in [" portfolio", " ecosystem"]:
        if key.endswith(suffix):
            base = key.replace(suffix, "")
            if base in TAG_TRANSLATIONS:
                return TAG_TRANSLATIONS[base] + (" portfolio" if suffix == " portfolio" else " ecosistema")
    return tag_name

_TRANSLATION_CACHE = _LRUDict(500)
_TRANSLATION_LOCK = threading.Lock()
_TRANSLATION_INFLIGHT = set()

def _load_translation_cache():
    try:
        if _TRANSLATION_CACHE_FILE.exists():
            data = json.loads(_TRANSLATION_CACHE_FILE.read_text(encoding="utf-8"))
            for k, v in data.get("t", {}).items(): _TRANSLATION_CACHE.put(k, v)
    except Exception: pass

def _save_translation_cache():
    try:
        data = {"saved": int(time.time()), "t": dict(_TRANSLATION_CACHE.items())}
        _TRANSLATION_CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception: pass
_load_translation_cache()

def _clean_markdown_html(text: str) -> str:
    if not text: return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"[ \t]+", " ", text).strip()

def _translate_google_free(text: str, target: str = "it") -> str:
    if not text or len(text.strip()) < 3: return text
    chunk = text[:4900]
    path = ("/translate_a/single?" + urllib.parse.urlencode({"client": "gtx", "sl": "en", "tl": target, "dt": "t", "q": chunk}))
    try:
        conn = _http.HTTPSConnection("translate.googleapis.com", timeout=8.0)
        conn.request("GET", path, headers={"User-Agent": "Mozilla/5.0 Chrome/150.0", "Accept-Encoding": "gzip"})
        resp = conn.getresponse()
        raw = gzip.decompress(resp.read()) if resp.getheader("Content-Encoding") == "gzip" else resp.read()
        conn.close()
        if resp.status != 200: return ""
        data = json.loads(raw.decode("utf-8"))
        if not data or not isinstance(data, list): return ""
        return "".join([c[0] for c in data[0] if c and c[0]])
    except Exception: return ""

def _translate_mymemory(text: str, target: str = "it") -> str:
    if not text or len(text.strip()) < 3: return text
    chunk = text[:4900]
    path = ("/get?" + urllib.parse.urlencode({
        "q": chunk, "langpair": f"en|{target}", "de": "cmc-terminal@local"
    }))
    try:
        conn = _http.HTTPSConnection("api.mymemory.translated.net", timeout=8.0)
        conn.request("GET", path, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"})
        resp = conn.getresponse()
        raw = gzip.decompress(resp.read()) if resp.getheader("Content-Encoding") == "gzip" else resp.read()
        conn.close()
        if resp.status != 200: return ""
        data = json.loads(raw.decode("utf-8"))
        translated = data.get("responseData", {}).get("translatedText", "")
        matches = data.get("matches", [])
        if matches:
            best = max(matches, key=lambda m: m.get("quality", 0) or 0)
            if isinstance(best.get("quality"), int) and best["quality"] >= 50:
                translated = best.get("translation", translated)
        return translated
    except Exception: return ""

def translate_to_italian(text: str) -> str:
    if not text: return ""
    cleaned = _clean_markdown_html(text)
    if len(cleaned) < 10: return cleaned
    key = hashlib.md5(cleaned.encode("utf-8")).hexdigest()[:16]
    
    cached = _TRANSLATION_CACHE.get(key)
    if cached: return cached

    # Prova traduzione immediata sincrona prima del worker
    try:
        res = _translate_google_free(cleaned)
        if not res or res == cleaned:
            res = _translate_mymemory(cleaned)
        if res and res != cleaned:
            _TRANSLATION_CACHE.put(key, res)
            if len(_TRANSLATION_CACHE) % 5 == 0: _save_translation_cache()
            return res
    except Exception: pass

    with _TRANSLATION_LOCK:
        if key in _TRANSLATION_INFLIGHT: return cleaned + "\n\n[traduzione in corso...]"
        _TRANSLATION_INFLIGHT.add(key)

    def _worker():
        try:
            res = _translate_google_free(cleaned)
            if not res or res == cleaned: res = _translate_mymemory(cleaned)
            if res and res != cleaned:
                _TRANSLATION_CACHE.put(key, res)
                if len(_TRANSLATION_CACHE) % 5 == 0: _save_translation_cache()
        except Exception: pass
        finally:
            with _TRANSLATION_LOCK: _TRANSLATION_INFLIGHT.discard(key)
    FETCH_EXECUTOR.submit(_worker)
    return cleaned + "\n\n[traduzione in corso...]"

def _fetch_coin_detail(cid: int) -> dict:
    path = f"/data-api/v3/cryptocurrency/detail?id={cid}"
    payload = _http_get_json(path, timeout=8.0)
    if not payload: return {}
    data = payload.get("data") or {}
    stats = data.get("statistics") or {}
    urls = data.get("urls") or {}
    return {
        "id": data.get("id"), "name": data.get("name"), "symbol": data.get("symbol"),
        "slug": data.get("slug"), "category": data.get("category"),
        "description": translate_to_italian(data.get("description", "")[:600]), "launch_date": data.get("launchDate") or data.get("dateAdded"),
        "tags": [translate_tag(t if isinstance(t, str) else t.get("name", "")) for t in data.get("tags", [])],
        "categories": [translate_tag(c if isinstance(c, str) else c.get("name", "")) for c in data.get("categories", [])],
        "urls": {
            "website": urls.get("website", []), "whitepaper": urls.get("technical_doc", []),
            "explorer": urls.get("explorer", []), "github": urls.get("source_code", []),
            "twitter": urls.get("twitter", []), "reddit": urls.get("reddit", [])
        },
        "stats": {
            "rank": stats.get("rank"),
            "ath": stats.get("highAllTime"),
            "ath_date": stats.get("highAllTimeTimestamp"),
            "ath_change_pct": stats.get("highAllTimeChangePercentage"),
            "atl": stats.get("lowAllTime"),
            "atl_date": stats.get("lowAllTimeTimestamp"),
            "atl_change_pct": stats.get("lowAllTimeChangePercentage"),
            "high24h": stats.get("high24h"),
            "low24h": stats.get("low24h"),
            "roi1y": stats.get("priceChangePercentage1y") or stats.get("roi"),
            "circulating": stats.get("circulatingSupply"),
            "total": stats.get("totalSupply"),
            "max": stats.get("maxSupply"),
            "fdv": stats.get("fullyDilutedMarketCap"),
            "dominance": stats.get("marketCapDominance")
        }
    }

_DETAIL_INFLIGHT = {}

def get_coin_detail(cid: int, max_age_sec: int = 300) -> dict:
    now = time.time()
    with _DETAIL_LOCK:
        cached = _DETAIL_CACHE.get(cid)
        if cached and (now - cached[1]) < max_age_sec: return cached[0]

        fut = _DETAIL_INFLIGHT.get(cid)
        if not fut or fut.done():
            def _worker():
                try:
                    data = _fetch_coin_detail(cid)
                    if data:
                        with _DETAIL_LOCK: _DETAIL_CACHE.put(cid, (data, time.time()))
                    return data
                except Exception: return {}
                finally:
                    with _DETAIL_LOCK: _DETAIL_INFLIGHT.pop(cid, None)
            fut = FETCH_EXECUTOR.submit(_worker)
            _DETAIL_INFLIGHT[cid] = fut

    try:
        data = fut.result(timeout=3.5)
        if data: return data
    except Exception: pass

    with _DETAIL_LOCK:
        cached = _DETAIL_CACHE.get(cid)
        return cached[0] if cached else {}

def is_loading_detail(cid: int) -> bool:
    with _DETAIL_LOCK: return cid in _DETAIL_LOADING

# ══════════════════════════════════════════════════════════════════════════════
# PERSISTENT ALERT ENGINE v2
# ══════════════════════════════════════════════════════════════════════════════

class _AlertEngineV2:
    def __init__(self):
        self.rules: List[dict] = []
        self.triggered: List[dict] = []
        self._lock = threading.RLock()
        self._last_prices = {}
        self.load_from_disk()

    def add(self, cid: int, op: str, value: float, field: str = "p", note: str = "") -> dict:
        rule = {
            "id": int(time.time() * 1000) + len(self.rules), "cid": cid,
            "symbol": COIN_META.get(cid, (f"#{cid}", ""))[0], "name": COIN_META.get(cid, ("", f"Asset #{cid}"))[1],
            "op": op, "value": float(value), "field": field, "note": note,
            "created": int(time.time()), "fired": False, "fire_time": None
        }
        with self._lock: self.rules.append(rule)
        self.save_to_disk()
        return rule

    def remove(self, rule_id: int) -> bool:
        with self._lock:
            initial = len(self.rules)
            self.rules = [r for r in self.rules if r["id"] != rule_id]
            res = len(self.rules) < initial
        if res: self.save_to_disk()
        return res

    def clear_fired(self):
        with self._lock: self.rules = [r for r in self.rules if not r["fired"]]
        self.save_to_disk()

    def all_rules(self) -> List[dict]:
        with self._lock: return list(self.rules)

    def check(self, store: QuoteStore) -> List[dict]:
        snap = store.snapshot()
        triggered = []
        with self._lock:
            for rule in self.rules:
                if rule["fired"]: continue
                q = snap.get(rule["cid"])
                if not q: continue
                v = q.get(rule["field"])
                if v is None: continue
                op = rule["op"]; target = rule["value"]
                last_v = self._last_prices.get((rule["cid"], rule["field"]))
                hit = False
                if op == ">": hit = v > target
                elif op == "<": hit = v < target
                elif op == ">=": hit = v >= target
                elif op == "<=": hit = v <= target
                elif op == "cross_up" and last_v is not None: hit = last_v < target and v >= target
                elif op == "cross_down" and last_v is not None: hit = last_v > target and v <= target
                self._last_prices[(rule["cid"], rule["field"])] = v
                if hit:
                    rule["fired"] = True; rule["fire_time"] = int(time.time()); rule["fire_val"] = v
                    triggered.append(dict(rule)); self.triggered.append(dict(rule))
            if triggered: self.save_to_disk()
        return triggered

    def save_to_disk(self):
        try: _ALERTS_FILE.write_text(json.dumps({"rules": self.rules}, indent=2), encoding="utf-8")
        except Exception: pass

    def load_from_disk(self):
        try:
            if _ALERTS_FILE.exists():
                data = json.loads(_ALERTS_FILE.read_text(encoding="utf-8"))
                self.rules = data.get("rules", [])
        except Exception: self.rules = []

    def get_all(self, active_only: bool = False) -> List[dict]:
        with self._lock:
            if active_only:
                return [r for r in self.rules if not r.get("fired")]
            return list(self.rules)

    add_rule = add
    remove_rule = remove
    check_alerts = check
    @property
    def triggered_logs(self) -> List[dict]:
        return self.triggered

ALERTS_V2 = _AlertEngineV2()

# ══════════════════════════════════════════════════════════════════════════════
# MEMORY MANAGER & EXPORTER
# ══════════════════════════════════════════════════════════════════════════════

class _MemoryManager:
    def __init__(self):
        self._alive = True
        self._last_snapshot_archive = 0.0
    def start(self):
        def _loop():
            while self._alive:
                time.sleep(60)
                try:
                    DISK_CACHE.cleanup()
                    now = time.time()
                    with STORE._lock:
                        to_del = [c for c, (ts, _) in list(STORE._change_flags.items()) if now - ts > 60]
                        for c in to_del: STORE._change_flags.pop(c, None)
                    gc.collect()
                    if now - self._last_snapshot_archive > 1800:
                        self._last_snapshot_archive = now
                        def _bg_snap():
                            try:
                                snap_rows = Exporter.get_rows(STORE)
                                CLOUD_DB.upload_dataset("market_snapshot_latest", {
                                    "type": "global_market_snapshot", "count": len(snap_rows),
                                    "assets": snap_rows, "archived_iso": datetime.now().isoformat()
                                }, description=f"Auto Market Snapshot ({len(snap_rows)} assets)")
                            except Exception: pass
                        FETCH_EXECUTOR.submit(_bg_snap)
                except Exception: pass
        threading.Thread(target=_loop, daemon=True).start()
    def stop(self): self._alive = False
MEM_MGR = _MemoryManager()

# ══════════════════════════════════════════════════════════════════════════════
# CLOUD HISTORICAL DATABASE ENGINE (808files Unlimited Storage)
# ══════════════════════════════════════════════════════════════════════════════

_CLOUD_DB_INDEX_FILE = _CACHE_DIR / "cloud_db_index.json"
_CLOUD_API_BASE = "https://808files.elmarciun.workers.dev"

class CloudStorageDB:
    """Motore database cloud illimitato basato sull'API 808files con offuscamento Base64+gzip."""
    def __init__(self):
        self._lock = threading.RLock()
        self.index: Dict[str, dict] = {}
        self.load_index()

    def load_index(self):
        try:
            if _CLOUD_DB_INDEX_FILE.exists():
                self.index = json.loads(_CLOUD_DB_INDEX_FILE.read_text(encoding="utf-8"))
        except Exception: self.index = {}

    def save_index(self):
        try:
            _CLOUD_DB_INDEX_FILE.write_text(json.dumps(self.index, indent=2), encoding="utf-8")
        except Exception: pass

    def upload_dataset(self, key: str, payload_obj: Any, description: str = "") -> dict:
        """Offusca il dataset JSON (gzip -> base64) e carica sul server cloud illimitato 808files."""
        import base64
        import urllib.request as _ur
        
        raw_bytes = json.dumps(payload_obj).encode("utf-8")
        size_uncompressed = len(raw_bytes)
        obfuscated = base64.b64encode(gzip.compress(raw_bytes))
        
        token_req = _ur.Request(f"{_CLOUD_API_BASE}/api/token", data=b"", method="POST")
        token_req.add_header("User-Agent", "Mozilla/5.0")
        with _ur.urlopen(token_req, timeout=15) as r:
            token_res = json.loads(r.read().decode("utf-8"))
            token = token_res.get("token")
            if not token: raise Exception("Impossibile ottenere token da 808files.")

        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        body_parts = []
        body_parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"token\"\r\n\r\n{token}\r\n".encode("utf-8"))
        body_parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{key}.b64\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode("utf-8"))
        body_parts.append(obfuscated)
        body_parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(body_parts)

        up_req = _ur.Request("https://upload.gofile.io/uploadfile", data=body, method="POST")
        up_req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        up_req.add_header("User-Agent", "Mozilla/5.0")
        with _ur.urlopen(up_req, timeout=30) as r:
            up_res = json.loads(r.read().decode("utf-8"))
            d = up_res.get("data", {})
            file_id = d.get("id")
            if not file_id: raise Exception("Upload su gofile fallito.")

        reg_payload = json.dumps({
            "token": token, "id": file_id,
            "server": d.get("servers", ["store1"])[0],
            "filename": d.get("name", f"{key}.b64"),
            "folder_id": d.get("parentFolder"),
            "folder_code": d.get("parentFolderCode"),
            "download_page": d.get("downloadPage"),
            "size": d.get("size", len(obfuscated)),
            "mimetype": "application/octet-stream"
        }).encode("utf-8")
        
        reg_req = _ur.Request(f"{_CLOUD_API_BASE}/api/register", data=reg_payload, method="POST")
        reg_req.add_header("Content-Type", "application/json")
        reg_req.add_header("User-Agent", "Mozilla/5.0")
        with _ur.urlopen(reg_req, timeout=15) as r:
            reg_res = json.loads(r.read().decode("utf-8"))
            if not reg_res.get("ok"): raise Exception("Registrazione fallita su 808files.")

        entry = {
            "key": key,
            "code": reg_res.get("code"),
            "link": reg_res.get("link"),
            "stream": reg_res.get("stream"),
            "description": description,
            "size_obfuscated": len(obfuscated),
            "size_uncompressed": size_uncompressed,
            "created_at": int(time.time()),
            "created_iso": datetime.now().isoformat()
        }
        with self._lock:
            self.index[key] = entry
            self.save_index()
        return entry

    def download_dataset(self, key: str) -> Optional[Any]:
        """Scarica e de-offusca (base64 -> gzip -> json) un dataset da 808files."""
        import base64
        import urllib.request as _ur
        with self._lock:
            entry = self.index.get(key)
        if not entry or not entry.get("stream"): return None
        
        try:
            req = _ur.Request(entry["stream"], headers={"User-Agent": "Mozilla/5.0"})
            with _ur.urlopen(req, timeout=30) as r:
                content = r.read()
            raw_json = gzip.decompress(base64.b64decode(content)).decode("utf-8")
            return json.loads(raw_json)
        except Exception as e:
            print(f"[CloudStorageDB] Download error for {key}: {e}", file=sys.stderr)
            return None

    def auto_archive_async(self, cid: int, tf: str, candles: list):
        """Esegue l'upload automatico in background su 808files senza mai pesare sulle risorse del client o bloccare le chiamate API."""
        key = f"c{cid}_{tf}_db"
        now = time.time()
        with self._lock:
            entry = self.index.get(key)
            if entry and (now - entry.get("created_at", 0)) < 43200:
                return

        def _bg_worker():
            try:
                sym = COIN_META.get(cid, (f"#{cid}", ""))[0]
                self.upload_dataset(key, {
                    "coin_id": cid, "symbol": sym, "timeframe": tf,
                    "count": len(candles), "candles": candles, "auto_archived": True,
                    "updated_iso": datetime.now().isoformat()
                }, description=f"Auto Cloud DB: {sym} {tf} ({len(candles)} candele)")
            except Exception: pass

        FETCH_EXECUTOR.submit(_bg_worker)

    def list_datasets(self) -> List[dict]:
        with self._lock:
            return list(self.index.values())

    def delete_dataset(self, key: str) -> bool:
        with self._lock:
            if key in self.index:
                del self.index[key]
                self.save_index()
                return True
            return False

CLOUD_DB = CloudStorageDB()

class Exporter:
    @staticmethod
    def get_rows(store: QuoteStore) -> List[dict]:
        snap = store.snapshot()
        rows = []
        for cid, q in sorted(snap.items(), key=lambda x: -(x[1].get("mc") or 0)):
            rows.append({
                "rank": q.get("rank", 0), "id": cid, "symbol": q.get("symbol", ""),
                "name": q.get("name", ""), "price_usd": q.get("p"),
                "percent_change_1h": q.get("p1h"), "percent_change_24h": q.get("p24h"),
                "percent_change_7d": q.get("p7d"), "percent_change_30d": q.get("p30d"),
                "volume_24h_usd": q.get("v24h"), "market_cap_usd": q.get("mc"),
                "circulating_supply": q.get("circ_supply"),
                "updated_iso": datetime.fromtimestamp(q.get("t", 0)/1000).isoformat() if q.get("t") else ""
            })
        return rows

    @staticmethod
    def to_json(store: QuoteStore) -> str:
        return json.dumps({"title": "CMC Terminal Pro — Snapshot", "generated_at": datetime.now().isoformat(), "count": len(store.snapshot()), "assets": Exporter.get_rows(store)}, indent=2)

    @staticmethod
    def to_csv(store: QuoteStore) -> str:
        rows = Exporter.get_rows(store)
        if not rows: return ""
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
        return out.getvalue()

    @staticmethod
    def to_markdown(store: QuoteStore) -> str:
        rows = Exporter.get_rows(store)
        lines = ["# 💎 CMC Terminal Pro — Snapshot Report", f"*Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}* · **{len(rows)} Assets**\n",
                 "| # | Symbol | Name | Price (USD) | 1H | 24H | 7D | 24H Volume | Market Cap |", "|---:|:---|:---|---:|---:|---:|---:|---:|---:|"]
        for r in rows:
            p = f"${r['price_usd']:,.4f}" if r['price_usd'] and r['price_usd'] >= 1 else (f"${r['price_usd']:,.6f}" if r['price_usd'] else "—")
            lines.append(f"| {r['rank'] or '—'} | **{r['symbol']}** | {r['name']} | {p} | {r['percent_change_1h'] or '—'}% | {r['percent_change_24h'] or '—'}% | {r['percent_change_7d'] or '—'}% | ${r['volume_24h_usd']:,.0f} | ${r['market_cap_usd']:,.0f} |" if r['volume_24h_usd'] and r['market_cap_usd'] else f"| {r['rank'] or '—'} | **{r['symbol']}** | {r['name']} | {p} | — | — | — | — | — |")
        return "\n".join(lines)

    @staticmethod
    def to_html(store: QuoteStore) -> str:
        rows = Exporter.get_rows(store)
        gen_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        table_rows = []
        for r in rows:
            p = r["price_usd"]
            p_str = f"${p:,.4f}" if p and p >= 1 else (f"${p:,.6f}" if p else "—")
            def badge(val):
                if val is None: return '<span style="color:#6b7280">—</span>'
                col = "#10b981" if val >= 0 else "#ef4444"
                return f'<span style="color:{col};font-weight:600;">{"▲" if val >= 0 else "▼"} {abs(val):.2f}%</span>'
            table_rows.append(f'<tr style="border-bottom:1px solid #1f2937;"><td style="padding:12px;color:#6b7280;">{r["rank"] or "—"}</td><td style="padding:12px;"><b style="color:#e5e7eb;">{r["symbol"]}</b> <span style="color:#9ca3af;">{r["name"]}</span></td><td style="padding:12px;text-align:right;font-weight:600;color:#e5e7eb;">{p_str}</td><td style="padding:12px;text-align:right;">{badge(r["percent_change_1h"])}</td><td style="padding:12px;text-align:right;">{badge(r["percent_change_24h"])}</td><td style="padding:12px;text-align:right;">{badge(r["percent_change_7d"])}</td><td style="padding:12px;text-align:right;color:#9ca3af;">${r["volume_24h_usd"]:,.0f}' if r["volume_24h_usd"] else '—' + f'</td><td style="padding:12px;text-align:right;color:#9ca3af;">${r["market_cap_usd"]:,.0f}' if r["market_cap_usd"] else '—' + '</td></tr>')
        return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>CMC Terminal Pro — Snapshot {gen_time}</title><style>body{{background:#0a0e1a;color:#e5e7eb;font-family:-apple-system,sans-serif;padding:40px;margin:0;}}.card{{background:#111827;border:1px solid #374151;border-radius:12px;overflow:hidden;box-shadow:0 10px 25px rgba(0,0,0,0.5);}}header{{background:linear-gradient(135deg,#1f2937 0%,rgba(139,92,246,0.15) 100%);padding:24px;border-bottom:1px solid #374151;display:flex;justify-content:space-between;align-items:center;}}h1{{margin:0;font-size:24px;background:linear-gradient(90deg,#8b5cf6,#3b82f6,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}}table{{width:100%;border-collapse:collapse;}}th{{background:rgba(0,0,0,0.3);padding:12px;text-align:left;font-size:11px;text-transform:uppercase;color:#9ca3af;border-bottom:1px solid #374151;}}th.right,td.right{{text-align:right;}}tr:hover{{background:rgba(139,92,246,0.08);}}</style></head><body><div class="card"><header><div><h1>◆ CMC TERMINAL PRO — MARKET SNAPSHOT</h1><div style="font-size:12px;color:#9ca3af;margin-top:4px;">Real-time CoinMarketCap WebSocket & REST API Data</div></div><div style="text-align:right;font-size:13px;"><div style="color:#10b981;font-weight:bold;">● LIVE DATA SNAPSHOT</div><div style="color:#6b7280;font-size:11px;margin-top:2px;">Generated: {gen_time}</div></div></header><table><thead><tr><th>#</th><th>Asset</th><th class="right">Price</th><th class="right">1H</th><th class="right">24H</th><th class="right">7D</th><th class="right">Volume 24H</th><th class="right">Market Cap</th></tr></thead><tbody>{"".join(table_rows)}</tbody></table></div></body></html>"""
