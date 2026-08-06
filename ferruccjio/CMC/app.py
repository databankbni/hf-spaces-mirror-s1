"""
FastAPI Server — CMC Terminal Professional
Replaces CLI commands with rich REST API GET & POST endpoints + SSE streaming.
Designed for deployment on Hugging Face Spaces (Docker SDK, Port 7860).
"""

import os
import time
import json
import asyncio
from datetime import datetime
from collections import defaultdict
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Query, Path, Body, HTTPException, status, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Import backend engine
from backend.engine import STORE, CANDLES, ALERTS_V2 as ALERTS, Exporter, COIN_META, translate_tag, load_full_coin_universe, start_streaming_max, MEM_MGR, get_coin_detail as fetch_detail, CLOUD_DB
import threading

# ══════════════════════════════════════════════════════════════════════════════
# FASTAPI APP INITIALIZATION & MIDDLEWARE
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="◆ CMC TERMINAL PRO — REST API & WEB DASHBOARD",
    description="""
### Real-Time Cryptocurrency Tracking Engine & Cyberpunk Terminal UI
Rebuilt from CLI edition to provide full-featured **GET & POST REST API** endpoints, **Server-Sent Events (SSE)** live streaming, and a high-performance **Bloomberg / Cyberpunk Dark Web Dashboard** for Hugging Face Spaces.

---
### 🛠️ Key Features:
* 📡 **Live WebSocket & REST Polling Hybrid**: Tracks 250+ cryptocurrencies with sub-second price updates.
* 📊 **OHLCV Candle Engine**: Real-time candle aggregation + historical data integration.
* 🔔 **Persistent Alert Engine**: Create custom price threshold alerts (`>`, `<`, `cross_up`, `cross_down`) with audio/visual web notifications.
* 📥 **One-Click Exporters**: Generate market snapshot reports in JSON, CSV, Markdown, and modern HTML.
* 🌐 **Italian Language Support**: Automatic translation of category tags and asset descriptions.
    """,
    version="2.0.0",
    contact={
        "name": "CMC Terminal Pro — Arena Agent",
        "url": "https://github.com/coinmarketcap"
    }
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup Templates & Static files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

@app.on_event("startup")
async def startup_engine():
    """Avvia l'esatto meccanismo del terminale Python: Universe Loader + WebSocket Streamer + Memory Manager."""
    load_full_coin_universe(async_refresh=True)
    start_streaming_max(subscribe_top_n=1000)
    MEM_MGR.start()

# ══════════════════════════════════════════════════════════════════════════════
# PYDANTIC SCHEMAS (API REQUEST & RESPONSE MODELS)
# ══════════════════════════════════════════════════════════════════════════════

class AlertCreateRequest(BaseModel):
    coin_id: int = Field(..., example=1, description="CoinMarketCap Asset ID (e.g. 1 for Bitcoin, 1027 for Ethereum)")
    field: str = Field("p", example="p", description="Metric to monitor: 'p' (price), 'p24h' (24h change %), 'mc' (market cap), 'v24h' (24h volume)")
    operator: str = Field(">", example=">", description="Comparison operator: '>', '<', '>=', '<=', 'cross_up', 'cross_down'")
    value: float = Field(..., example=100000.0, description="Threshold value that triggers the alert")
    note: Optional[str] = Field("", example="BTC 100k milestone target", description="Custom note for notification")

class AlertTestRequest(BaseModel):
    symbol: str = Field("BTC", example="BTC")
    value: float = Field(100000.0, example=100000.0)
    note: str = Field("Test sound & toast notification", example="Test alert notification")

class CloudUploadRequest(BaseModel):
    coin_id: int = Field(..., example=1, description="CoinMarketCap Asset ID")
    timeframe: str = Field("1d", example="1d", description="Timeframe to archive (e.g. '1d' for up to 10 years)")
    limit: int = Field(3650, ge=10, le=10000, description="Number of candles to archive")
    description: str = Field("Multi-Year Historical Archive", example="Bitcoin 10-Year Daily History")

class StatusResponse(BaseModel):
    status: str
    uptime_seconds: float
    throughput_msg_per_sec: float
    tracked_assets: int
    bullish_percentage: float
    avg_change_1h: float
    avg_change_24h: float
    avg_change_7d: float

# ══════════════════════════════════════════════════════════════════════════════
# WEB UI ROUTE
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse, tags=["🖥️ Web Dashboard"], summary="Render Main Cyberpunk Web UI")
async def render_dashboard(request: Request):
    """
    Renders the stunning **Bloomberg Terminal / Cyberpunk Crypto Dashboard** UI.
    Includes real-time ticker tape, interactive filtering table, TradingView charts, and built-in REST API testing console.
    """
    return templates.TemplateResponse(request=request, name="index.html")

# ══════════════════════════════════════════════════════════════════════════════
# REST API GET ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/status", response_model=StatusResponse, tags=["📊 Market Overview"], summary="Get System Status & Market Sentiment KPIs")
@app.get("/status", response_model=StatusResponse, tags=["📊 Market Overview"], include_in_schema=False)
async def get_market_status():
    """
    Returns real-time system metrics (uptime, message throughput) and global market sentiment (bullish vs bearish assets, average 1h/24h/7d percentage changes).
    """
    snap = STORE.snapshot()
    total = len(snap)
    if total == 0:
        return {
            "status": "CONNECTING", "uptime_seconds": STORE.uptime,
            "throughput_msg_per_sec": STORE.msg_per_sec, "tracked_assets": 0,
            "bullish_percentage": 50.0, "avg_change_1h": 0.0, "avg_change_24h": 0.0, "avg_change_7d": 0.0
        }

    p1h = [q.get("p1h", 0) for q in snap.values() if q.get("p1h") is not None]
    p24h = [q.get("p24h", 0) for q in snap.values() if q.get("p24h") is not None]
    p7d = [q.get("p7d", 0) for q in snap.values() if q.get("p7d") is not None]

    bulls = sum(1 for x in p24h if x >= 0)
    bull_pct = (bulls / len(p24h) * 100.0) if p24h else 50.0

    def avg(lst): return sum(lst) / len(lst) if lst else 0.0

    return {
        "status": "LIVE" if STORE.connected else "POLLING",
        "uptime_seconds": round(STORE.uptime, 1),
        "throughput_msg_per_sec": round(STORE.msg_per_sec, 2),
        "tracked_assets": total,
        "bullish_percentage": round(bull_pct, 1),
        "avg_change_1h": round(avg(p1h), 2),
        "avg_change_24h": round(avg(p24h), 2),
        "avg_change_7d": round(avg(p7d), 2)
    }

@app.get("/api/coins", tags=["💰 Cryptocurrencies"], summary="List & Filter Cryptocurrencies")
@app.get("/coins", tags=["💰 Cryptocurrencies"], include_in_schema=False)
async def list_coins(
    sort_by: str = Query("mc", description="Sort field: 'mc' (Market Cap), 'p24h' (24h Change), 'p' (Price), 'v24h' (Volume), 'rank', 'p1h', 'p7d'"),
    order: str = Query("desc", description="Sort order: 'desc' (Descending) or 'asc' (Ascending)"),
    search: Optional[str] = Query(None, description="Search term to filter by symbol or asset name (e.g., 'BTC', 'Solana')"),
    category: Optional[str] = Query(None, description="Filter by category or tag (e.g., 'DeFi', 'Layer 1', 'Meme', 'AI & Big Data')"),
    limit: int = Query(50, ge=1, le=250, description="Number of assets to return"),
    offset: int = Query(0, ge=0, description="Pagination offset")
):
    """
    Returns a paginated, sorted, and filtered list of cryptocurrencies with real-time prices, 24h/7d changes, volume, market cap, circulating supply, and inline sparkline chart data.
    """
    snap = STORE.snapshot()
    coins = list(snap.values())

    # Apply search filter
    if search:
        s_term = search.lower().strip()
        coins = [c for c in coins if s_term in c.get("symbol", "").lower() or s_term in c.get("name", "").lower()]

    # Apply category/tag filter
    if category and category.lower() != "all":
        cat_term = category.lower().strip()
        filtered = []
        for c in coins:
            tags = [t.lower() for t in c.get("tags", [])]
            if cat_term in tags or any(cat_term in translate_tag(t).lower() for t in tags):
                filtered.append(c)
        coins = filtered

    # Sorting
    reverse = (order.lower() == "desc")
    def sort_key(q):
        val = q.get(sort_by)
        if sort_by == "rank":
            return (val or 999999) if not reverse else -(val or 999999)
        return val if val is not None else (-1e15 if reverse else 1e15)

    coins.sort(key=sort_key, reverse=reverse)

    # Paginate and format
    paginated = coins[offset : offset + limit]
    results = []
    for c in paginated:
        cid = c.get("id")
        flash = STORE.flash_direction(cid)
        results.append({
            "id": cid,
            "rank": c.get("rank"),
            "symbol": c.get("symbol"),
            "name": c.get("name"),
            "price": c.get("p"),
            "change_1h": c.get("p1h"),
            "change_24h": c.get("p24h"),
            "change_7d": c.get("p7d"),
            "change_30d": c.get("p30d"),
            "volume_24h": c.get("v24h"),
            "market_cap": c.get("mc"),
            "circulating_supply": c.get("circ_supply"),
            "total_supply": c.get("total_supply"),
            "max_supply": c.get("max_supply"),
            "flash_direction": flash, # 1 for up, -1 for down, None for stable
            "updated_ms": c.get("t")
        })

    return {
        "total_matches": len(coins),
        "limit": limit,
        "offset": offset,
        "data": results
    }

@app.get("/api/coins/{coin_id}", tags=["💰 Cryptocurrencies"], summary="Get Detailed Coin Quote & Metadata")
@app.get("/coins/{coin_id}", tags=["💰 Cryptocurrencies"], include_in_schema=False)
async def get_coin_detail(coin_id: int = Path(..., description="CoinMarketCap Asset ID (e.g. 1 for BTC, 1027 for ETH)")):
    """
    Returns real-time price quote combined with extended metadata from CoinMarketCap:
    All-Time High (ATH), All-Time Low (ATL), circulating vs max supply distribution, official website/whitepaper/explorer links, tags, and Italian-translated description.
    """
    quote = STORE.get_coin(coin_id)
    if not quote:
        raise HTTPException(status_code=404, detail=f"Asset ID #{coin_id} not found in tracked universe.")

    # Fetch extended metadata
    detail = fetch_detail(coin_id)

    return {
        "id": coin_id,
        "rank": quote.get("rank"),
        "symbol": quote.get("symbol"),
        "name": quote.get("name"),
        "price": quote.get("p"),
        "change_1h": quote.get("p1h"),
        "change_24h": quote.get("p24h"),
        "change_7d": quote.get("p7d"),
        "change_30d": quote.get("p30d"),
        "volume_24h": quote.get("v24h"),
        "market_cap": quote.get("mc"),
        "fdv": quote.get("fdv"),
        "supply": {
            "circulating": quote.get("circ_supply"),
            "total": quote.get("total_supply"),
            "max": quote.get("max_supply")
        },
        "metadata": detail
    }

@app.get("/api/coins/{coin_id}/ticker", tags=["💰 Cryptocurrencies"], summary="Instant Real-Time Lightweight Ticker for Bots")
@app.get("/coins/{coin_id}/ticker", tags=["💰 Cryptocurrencies"], include_in_schema=False)
async def get_coin_ticker(coin_id: int = Path(..., description="CoinMarketCap Asset ID")):
    """Ultra-fast (<1ms) lightweight endpoint returning current price, 24h volume, and percentage change. Ideal for automated trading bots."""
    quote = STORE.get_coin(coin_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Asset ID not found.")
    return {
        "id": coin_id, "symbol": quote.get("symbol"), "price": quote.get("p"),
        "change_24h": quote.get("p24h"), "volume_24h": quote.get("v24h"),
        "timestamp": quote.get("t")
    }

@app.get("/api/market/top-gainers", tags=["📊 Market Overview"], summary="Get Top 10 Gainers in Last 24 Hours")
@app.get("/market/top-gainers", tags=["📊 Market Overview"], include_in_schema=False)
async def get_top_gainers():
    """Returns top 10 cryptocurrencies with highest 24h percentage gain."""
    snap = STORE.snapshot()
    gainers = sorted([q for q in snap.values() if q.get("p24h") is not None], key=lambda x: -x["p24h"])[:10]
    return {"count": len(gainers), "data": [{"id": g["id"], "symbol": g.get("symbol"), "name": g.get("name"), "price": g.get("p"), "change_24h": g.get("p24h")} for g in gainers]}

@app.get("/api/market/top-losers", tags=["📊 Market Overview"], summary="Get Top 10 Losers in Last 24 Hours")
@app.get("/market/top-losers", tags=["📊 Market Overview"], include_in_schema=False)
async def get_top_losers():
    """Returns top 10 cryptocurrencies with lowest 24h percentage drop."""
    snap = STORE.snapshot()
    losers = sorted([q for q in snap.values() if q.get("p24h") is not None], key=lambda x: x["p24h"])[:10]
    return {"count": len(losers), "data": [{"id": l["id"], "symbol": l.get("symbol"), "name": l.get("name"), "price": l.get("p"), "change_24h": l.get("p24h")} for l in losers]}

@app.get("/api/coins/{coin_id}/candles", tags=["📈 OHLCV Charts"], summary="Get Historical & Real-Time OHLCV Candles")
@app.get("/coins/{coin_id}/candles", tags=["📈 OHLCV Charts"], include_in_schema=False)
async def get_coin_candles(
    coin_id: int = Path(..., description="CoinMarketCap Asset ID"),
    timeframe: str = Query("1h", description="Candle interval: '1m', '5m', '15m', '1h', '4h', '1d'"),
    limit: int = Query(150, ge=1, le=10000, description="Number of candles to return (up to 10,000 for multi-year analysis)")
):
    """
    Returns a list of OHLCV (Open, High, Low, Close, Volume) candlestick buckets for chart rendering.
    Combines historical data from public REST APIs with sub-second real-time tick aggregation!
    """
    if timeframe not in ("1m", "5m", "15m", "1h", "4h", "1d"):
        raise HTTPException(status_code=400, detail="Invalid timeframe. Use 1m, 5m, 15m, 1h, 4h, or 1d.")
    
    candles = CANDLES.get_candles(coin_id, timeframe, limit=limit)
    if len(candles) >= 300:
        key = f"c{coin_id}_{timeframe}_archive"
        if not any(d["key"] == key for d in CLOUD_DB.list_datasets()):
            def _bg_upload():
                try:
                    sym = COIN_META.get(coin_id, (f"#{coin_id}", ""))[0]
                    CLOUD_DB.upload_dataset(key, {
                        "coin_id": coin_id, "symbol": sym, "timeframe": timeframe,
                        "count": len(candles), "candles": candles, "archived_iso": datetime.now().isoformat()
                    }, description=f"{sym} {timeframe} Multi-Year Archive ({len(candles)} candles)")
                except Exception: pass
            threading.Thread(target=_bg_upload, daemon=True).start()

    return {
        "coin_id": coin_id,
        "symbol": COIN_META.get(coin_id, (f"#{coin_id}", ""))[0],
        "timeframe": timeframe,
        "count": len(candles),
        "candles": candles
    }

@app.get("/api/categories", tags=["📊 Market Overview"], summary="List Available Asset Categories & Tags")
@app.get("/categories", tags=["📊 Market Overview"], include_in_schema=False)
async def list_categories():
    """
    Returns a breakdown of all available category tags across tracked cryptocurrencies with asset counts.
    """
    snap = STORE.snapshot()
    tag_counts = defaultdict(int)
    for c in snap.values():
        for t in c.get("tags", []):
            tag_counts[t] += 1

    sorted_tags = sorted(tag_counts.items(), key=lambda x: -x[1])
    results = [
        {"tag": tag, "translated": translate_tag(tag), "count": count}
        for tag, count in sorted_tags[:30]
    ]
    return {"total_categories": len(results), "categories": results}

@app.get("/api/alerts", tags=["🔔 Alert Engine"], summary="List Active & Triggered Alerts")
@app.get("/alerts", tags=["🔔 Alert Engine"], include_in_schema=False)
async def get_alerts(active_only: bool = Query(False, description="If true, returns only pending (untriggered) rules")):
    """
    Returns all custom price threshold alert rules currently configured in the system, along with notification logs for alerts that have fired.
    """
    rules = ALERTS.get_all(active_only=active_only)
    return {
        "total_rules": len(rules),
        "active_rules": len([r for r in rules if not r["fired"]]),
        "triggered_rules": len([r for r in rules if r["fired"]]),
        "rules": rules
    }

@app.get("/api/export", tags=["📥 Export & Reports"], summary="Download Market Snapshot File")
@app.get("/export", tags=["📥 Export & Reports"], include_in_schema=False)
async def export_snapshot(format: str = Query("json", description="Export format: 'json', 'csv', 'md' (Markdown), or 'html' (Stylized HTML Report)")):
    """
    Generates and returns an instant downloadable file or raw payload containing the complete real-time market snapshot of all tracked assets.
    """
    fmt = format.lower().strip()
    if fmt == "json":
        content = Exporter.to_json(STORE)
        return PlainTextResponse(content, media_type="application/json", headers={"Content-Disposition": "attachment; filename=cmc_snapshot.json"})
    elif fmt == "csv":
        content = Exporter.to_csv(STORE)
        return PlainTextResponse(content, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=cmc_snapshot.csv"})
    elif fmt == "md" or fmt == "markdown":
        content = Exporter.to_markdown(STORE)
        return PlainTextResponse(content, media_type="text/markdown", headers={"Content-Disposition": "attachment; filename=cmc_snapshot.md"})
    elif fmt == "html":
        content = Exporter.to_html(STORE)
        return HTMLResponse(content, headers={"Content-Disposition": "attachment; filename=cmc_snapshot.html"})
    else:
        raise HTTPException(status_code=400, detail="Unsupported format. Use 'json', 'csv', 'md', or 'html'.")

# ══════════════════════════════════════════════════════════════════════════════
# REST API POST & DELETE ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/alerts", status_code=status.HTTP_201_CREATED, tags=["🔔 Alert Engine"], summary="Create a New Price Alert Rule")
@app.post("/alerts", status_code=status.HTTP_201_CREATED, tags=["🔔 Alert Engine"], include_in_schema=False)
async def create_alert(request: AlertCreateRequest):
    """
    Creates a new real-time alert rule.
    When the asset crosses the threshold, the server logs the trigger and broadcasts a notification event via SSE!
    """
    if request.coin_id not in COIN_META and not STORE.get_coin(request.coin_id):
        raise HTTPException(status_code=400, detail=f"Coin ID #{request.coin_id} is not valid.")
    
    if request.operator not in (">", "<", ">=", "<=", "cross_up", "cross_down"):
        raise HTTPException(status_code=400, detail="Invalid operator.")

    rule = ALERTS.add_rule(
        cid=request.coin_id,
        op=request.operator,
        value=request.value,
        field=request.field,
        note=request.note or ""
    )
    return {"message": "Alert rule successfully armed!", "rule": rule}

@app.delete("/api/alerts/{alert_id}", tags=["🔔 Alert Engine"], summary="Delete an Alert Rule")
@app.delete("/alerts/{alert_id}", tags=["🔔 Alert Engine"], include_in_schema=False)
async def delete_alert(alert_id: int = Path(..., description="Unique ID of the alert rule")):
    """
    Deletes an alert rule by its unique ID.
    """
    success = ALERTS.remove_rule(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert rule ID not found.")
    return {"message": f"Alert rule #{alert_id} deleted."}

@app.post("/api/alerts/clear-triggered", tags=["🔔 Alert Engine"], summary="Clear All Triggered Alert Logs")
@app.post("/alerts/clear-triggered", tags=["🔔 Alert Engine"], include_in_schema=False)
async def clear_triggered_alerts():
    """
    Clears all triggered alerts from the history while keeping active pending rules intact.
    """
    ALERTS.clear_triggered()
    return {"message": "All triggered alert logs cleared."}

@app.post("/api/alerts/test", tags=["🔔 Alert Engine"], summary="Trigger Simulated Alert Notification")
@app.post("/alerts/test", tags=["🔔 Alert Engine"], include_in_schema=False)
async def trigger_test_alert(request: AlertTestRequest):
    """
    Simulates an instant alert notification fire event. Useful for testing UI toast banners and cyberpunk sound effects!
    """
    test_rule = {
        "id": int(time.time() * 1000),
        "cid": 1 if request.symbol.upper() == "BTC" else 1027,
        "symbol": request.symbol.upper(),
        "name": "Test Asset",
        "op": ">",
        "value": request.value,
        "field": "p",
        "note": request.note,
        "created_at": int(time.time()),
        "fired": True,
        "fire_time": int(time.time()),
        "fire_value": request.value * 1.01
    }
    ALERTS.triggered_logs.append(test_rule)
    return {"message": "Test notification triggered!", "alert": test_rule}

@app.get("/api/cloud-db", tags=["☁️ Cloud DB (808files)"], summary="List Archived Obfuscated Datasets on 808files")
@app.get("/cloud-db", tags=["☁️ Cloud DB (808files)"], include_in_schema=False)
async def list_cloud_datasets():
    """Returns all multi-year historical datasets stored on the 808files unlimited cloud database in Base64 obfuscated JSON."""
    datasets = CLOUD_DB.list_datasets()
    return {"total_archives": len(datasets), "provider": "808files.elmarciun.workers.dev", "data": datasets}

@app.post("/api/cloud-db/upload", status_code=status.HTTP_201_CREATED, tags=["☁️ Cloud DB (808files)"], summary="Archive Multi-Year Dataset to 808files Cloud DB")
@app.post("/cloud-db/upload", status_code=status.HTTP_201_CREATED, tags=["☁️ Cloud DB (808files)"], include_in_schema=False)
async def upload_cloud_dataset(request: CloudUploadRequest):
    """Fetches multi-year historical OHLCV data, obfuscates it in Base64+gzip, and uploads it to 808files unlimited cloud storage."""
    candles = CANDLES.get_candles(request.coin_id, request.timeframe, limit=request.limit)
    if not candles:
        raise HTTPException(status_code=404, detail="No historical candles found to archive.")
    
    sym = COIN_META.get(request.coin_id, (f"#{request.coin_id}", ""))[0]
    key = f"c{request.coin_id}_{request.timeframe}_{len(candles)}"
    
    try:
        entry = CLOUD_DB.upload_dataset(key, {
            "coin_id": request.coin_id, "symbol": sym, "timeframe": request.timeframe,
            "count": len(candles), "candles": candles, "archived_iso": datetime.now().isoformat()
        }, description=request.description)
        return {"message": "Dataset successfully obfuscated and archived to 808files cloud DB!", "archive": entry}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cloud DB upload error: {e}")

@app.get("/api/cloud-db/download/{key}", tags=["☁️ Cloud DB (808files)"], summary="Download & Decode Dataset from 808files")
@app.get("/cloud-db/download/{key}", tags=["☁️ Cloud DB (808files)"], include_in_schema=False)
async def download_cloud_dataset(key: str = Path(..., description="Unique dataset archive key")):
    """Fetches, decodes (Base64->gzip->JSON), and returns an archived multi-year dataset from 808files."""
    data = CLOUD_DB.download_dataset(key)
    if not data:
        raise HTTPException(status_code=404, detail="Dataset not found or stream inaccessible on 808files.")
    return data

@app.delete("/api/cloud-db/{key}", tags=["☁️ Cloud DB (808files)"], summary="Remove Dataset from Cloud DB Index")
@app.delete("/cloud-db/{key}", tags=["☁️ Cloud DB (808files)"], include_in_schema=False)
async def delete_cloud_dataset(key: str = Path(..., description="Unique dataset archive key")):
    """Removes a dataset from the local index."""
    if CLOUD_DB.delete_dataset(key):
        return {"message": f"Archive key '{key}' removed from index."}
    raise HTTPException(status_code=404, detail="Key not found in index.")

# ══════════════════════════════════════════════════════════════════════════════
# SERVER-SENT EVENTS (SSE) REAL-TIME STREAMING ENDPOINT
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/stream", tags=["📡 Real-Time Streaming"], summary="Server-Sent Events (SSE) Live Data Feed")
@app.get("/stream", tags=["📡 Real-Time Streaming"], include_in_schema=False)
async def stream_live_data(
    request: Request,
    interval: float = Query(0.5, ge=0.1, le=10.0, description="Streaming update interval in seconds (default 0.5s / 2Hz, set to 1.0 for 1Hz)"),
    coin_id: Optional[int] = Query(None, description="Optional Asset ID to stream its exact real-time active OHLCV candle"),
    timeframe: str = Query("1h", description="Candle interval if streaming active candle: '1m', '5m', '15m', '1h', '4h', '1d'")
):
    """
    Establishes an SSE persistent streaming connection.
    Pushes real-time price quotes, flash indicators, active OHLCV candlestick objects, and fired alert notifications to external apps or browsers every `interval` seconds!
    """
    async def event_generator():
        last_alert_count = len(ALERTS.triggered_logs)
        while True:
            if await request.is_disconnected():
                break

            current_alerts = len(ALERTS.triggered_logs)
            new_alerts = []
            if current_alerts > last_alert_count:
                new_alerts = ALERTS.triggered_logs[last_alert_count:]
                last_alert_count = current_alerts
            else:
                new_alerts = ALERTS.check_alerts(STORE)
                if new_alerts:
                    last_alert_count = len(ALERTS.triggered_logs)

            snap = STORE.snapshot()
            top_coins = sorted(snap.values(), key=lambda x: -(x.get("mc") or 0))[:50]
            
            stream_payload = []
            for c in top_coins:
                cid = c.get("id")
                stream_payload.append({
                    "id": cid,
                    "p": c.get("p"),
                    "p24h": c.get("p24h"),
                    "v24h": c.get("v24h"),
                    "mc": c.get("mc"),
                    "flash": STORE.flash_direction(cid)
                })

            active_candle = None
            if coin_id:
                candles = CANDLES.get_candles(coin_id, timeframe, limit=1)
                if candles:
                    active_candle = candles[-1]

            data_str = json.dumps({
                "timestamp": int(time.time() * 1000),
                "throughput": round(STORE.msg_per_sec, 1),
                "uptime": round(STORE.uptime, 0),
                "prices": stream_payload,
                "active_candle": active_candle,
                "new_alerts": new_alerts
            })

            yield f"data: {data_str}\n\n"
            await asyncio.sleep(interval)

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no"
    })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=7860, reload=True)
