---
title: CMC Terminal Pro — Web Dashboard & REST API Hub
emoji: 💎
colorFrom: indigo
colorTo: blue
sdk: docker
pinned: false
app_port: 7860
---

# ◆ CMC TERMINAL PRO — Web Dashboard & REST API Hub
**Rebuilt from the CLI terminal edition into an ultra-high performance FastAPI REST server and Cyberpunk Bloomberg Terminal Web Dashboard for Hugging Face Spaces.**

---

## 🌟 Why Rebuild for Hugging Face Spaces?
In the original command-line interface (CLI) edition, interacting with real-time crypto markets required running a terminal script with complex keyboard shortcuts (`↑/↓`, `S`, `1/5/H`, `A`, etc.).

This modern deployment **replaces all CLI commands with structured REST API `GET` and `POST` endpoints** while delivering an **incredible Web UI ("UI pazzesca")** that renders real-time TradingView charts, sub-second price flashes, and sound-enabled alert notifications!

---

## 🖥️ The Incredible Web Dashboard ("UI Pazzesca")
The front-end is built with **Tailwind CSS**, **Lucide Icons**, and **TradingView Lightweight Charts** over a dark obsidian Bloomberg/Cyberpunk aesthetic:
* **📡 Real-Time Marquee Ticker**: An auto-scrolling header streaming live gainers and losers.
* **⚡ Sub-Second Price Flashes**: Cell backgrounds pulse neon emerald when prices tick up and crimson when prices tick down via **Server-Sent Events (SSE)** at 2 Hz!
* **📈 Interactive Candlestick Charts**: Embedded TradingView charts supporting `1m`, `5m`, `15m`, `1h`, `4h`, and `1d` intervals with volume histograms.
* **🔔 Persistent Alert Engine**: Arm price threshold alerts (`>`, `<`, `cross_up`, `cross_down`) with automated **web audio synth beeps** and floating toast banners when rules fire!
* **📥 One-Click Exporters**: Instant downloads of market snapshots in HTML, JSON, CSV, and Markdown formats.
* **🌐 Italian Translation Support**: Automated translation of asset descriptions and category tags.

---

## 🛠️ REST API Endpoints (CLI Replacement Guide)
Every feature of the CLI terminal is now mapped to a clean REST API. Explore and execute these interactively inside the web dashboard's **REST API Console** tab or open the full Swagger UI at `/docs`.

### 1️⃣ Get Market Overview & Status
* **CLI equivalent**: Dashboard header KPIs and statistics box.
* **REST Endpoint**: `GET /api/status`
* **Response**:
```json
{
  "status": "LIVE",
  "uptime_seconds": 124.5,
  "throughput_msg_per_sec": 14.8,
  "tracked_assets": 250,
  "bullish_percentage": 62.4,
  "avg_change_1h": 0.15,
  "avg_change_24h": 2.34,
  "avg_change_7d": 8.12
}
```

### 2️⃣ List, Sort & Filter Cryptocurrencies
* **CLI equivalent**: Main terminal table, `S` key sort cycling, `/` search, and watchlist filtering.
* **REST Endpoint**: `GET /api/coins?sort_by=mc&order=desc&limit=50&search=BTC&category=DeFi`
* **Query Parameters**:
  * `sort_by`: `'mc'` (Market Cap), `'p24h'` (24h Change), `'p'` (Price), `'v24h'` (Volume), `'rank'`.
  * `order`: `'desc'` or `'asc'`.
  * `search`: Filter by symbol or asset name (e.g., `'solana'`).
  * `category`: Filter by category tag (e.g., `'DeFi'`, `'Layer 1'`, `'Meme'`).
  * `limit` & `offset`: Pagination controls.

### 3️⃣ Get Detailed Asset Metadata & Quotes
* **CLI equivalent**: Pressing `ENTER` on a coin row to open fullscreen detail mode.
* **REST Endpoint**: `GET /api/coins/{coin_id}` (e.g. `GET /api/coins/1` for Bitcoin)
* **Response**: Returns real-time price, ATH/ATL statistics, circulating vs max supply distribution, official website/whitepaper/explorer links, and Italian translated description.

### 4️⃣ Get Historical & Real-Time OHLCV Candles
* **CLI equivalent**: `1`, `5`, `Q`, `H`, `D` timeframe shortcut keys.
* **REST Endpoint**: `GET /api/coins/{coin_id}/candles?timeframe=1h&limit=150`
* **Query Parameters**: `timeframe` (`'1m'`, `'5m'`, `'15m'`, `'1h'`, `'4h'`, `'1d'`), `limit` (up to 500).
* **Note**: Our backend engine aggregates sub-second real-time streaming ticks directly into public historical REST API data!

### 5️⃣ Manage Alert Rules
* **CLI equivalent**: `A` alert dialog, `L` list view, `DEL` delete rule, and `C` clear logs.
* **REST Endpoints**:
  * `GET /api/alerts`: List all active rules and triggered notification logs.
  * `POST /api/alerts`: Arm a new price threshold rule.
    ```json
    {
      "coin_id": 1027,
      "field": "p",
      "operator": ">",
      "value": 5000.0,
      "note": "ETH $5k milestone target"
    }
    ```
  * `DELETE /api/alerts/{alert_id}`: Remove an armed rule.
  * `POST /api/alerts/clear-triggered`: Clear fired alert notification logs.
  * `POST /api/alerts/test`: Trigger a simulated alert event to test cyberpunk audio/toast effects.

### 6️⃣ Generate Snapshot Exports
* **CLI equivalent**: `E` export shortcut key and `--save` flag.
* **REST Endpoint**: `GET /api/export?format=html`
* **Formats supported**: `'html'` (Stylized Report), `'json'`, `'csv'`, `'md'` (Markdown table).

### 7️⃣ Live Server-Sent Events (SSE) Stream
* **REST Endpoint**: `GET /api/stream`
* **Description**: Persistent SSE streaming feed pushing real-time ticker updates, price flashes, throughput KPIs, and fired alert triggers at 2 Hz directly to your client without requiring external API keys.

---

## 🚀 How to Deploy on Hugging Face Spaces
This repository is configured as a **Docker SDK Space** listening on port `7860`.
1. Create a new Space on [Hugging Face Spaces](https://huggingface.co/spaces).
2. Select **Docker** as the SDK and choose the **Blank** template.
3. Upload all files from this folder (`Dockerfile`, `requirements.txt`, `app.py`, `backend/`, `static/`, `templates/`, `README.md`).
4. The container will automatically build and launch the FastAPI server on port `7860`!

---

## 💻 Local Testing & Development
To run the server locally on your machine:
```bash
# 1. Install required Python packages
pip install -r requirements.txt

# 2. Launch Uvicorn development server
uvicorn app:app --host 0.0.0.0 --port 7860 --reload
```
Open your browser at **http://localhost:7860** to experience the dashboard or visit **http://localhost:7860/docs** for interactive Swagger API documentation.
