"""
KOMBAZ.ME — Mars 2045 / Abundance OS
Flask backend for Hugging Face Spaces + PWA support
By Shai Kombaz · 2026
v8.0 — Private Vault with Weekly Schedule + Portfolio 21.06.2026
"""

from flask import Flask, jsonify, send_from_directory, send_file
from flask_cors import CORS
import os, json
from datetime import datetime

app = Flask(__name__, static_folder='static')
CORS(app)


@app.route('/')
def index():
    with open('index.html', 'r', encoding='utf-8') as f:
        return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}


# PWA files
@app.route('/manifest.json')
def manifest():
    return send_file('manifest.json', mimetype='application/manifest+json')


@app.route('/sw.js')
def service_worker():
    return send_file('sw.js', mimetype='application/javascript')


@app.route('/ads.txt')
def ads_txt():
    """Required by Google AdSense — must be served at the site root.
    Fill in your real publisher ID (from AdSense > Account > Settings) in ads.txt."""
    try:
        with open('ads.txt', 'r', encoding='utf-8') as f:
            return f.read(), 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception:
        return '# ads.txt not configured yet — add your AdSense publisher ID here', 200, {'Content-Type': 'text/plain; charset=utf-8'}


@app.route('/privacy')
def privacy():
    with open('privacy.html', 'r', encoding='utf-8') as f:
        return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.route('/static/<path:path>')
def static_files(path):
    return send_from_directory('static', path)


# API
@app.route('/api/health')
def health():
    return jsonify({
        'status': 'running',
        'app': 'KOMBAZ.ME',
        'version': '8.0',
        'pwa': True,
        'portfolio_updated': '2026-06-21',
        'timestamp': datetime.utcnow().isoformat()
    })


@app.route('/api/missions')
def missions():
    try:
        with open('static/data/missions.json', 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify({'missions': []})


@app.route('/api/portfolio')
def portfolio():
    """Current portfolio snapshot — 21.06.2026"""
    holdings = [
        {"ticker": "MU",   "name": "Micron Technology",      "qty": 10,  "avg": 999.78,  "value_ils": 33532, "roi_pct": 13.42},
        {"ticker": "ASML", "name": "ASML Holding",           "qty": 4,   "avg": 1782.19, "value_ils": 22824, "roi_pct": 8.28},
        {"ticker": "SPCX", "name": "SpaceX ETF",             "qty": 40,  "avg": 198.54,  "value_ils": 21882, "roi_pct": -6.82},
        {"ticker": "AMD",  "name": "Advanced Micro Devices", "qty": 10,  "avg": 394.36,  "value_ils": 15890, "roi_pct": 36.26},
        {"ticker": "NVDY", "name": "YieldMax NVDA",          "qty": 300, "avg": 13.81,   "value_ils": 11603, "roi_pct": -5.29},
        {"ticker": "IONQ", "name": "IonQ",                   "qty": 54,  "avg": 48.21,   "value_ils": 9030,  "roi_pct": 17.30},
        {"ticker": "NVDA", "name": "NVIDIA",                 "qty": 15,  "avg": 192.31,  "value_ils": 9345,  "roi_pct": 9.56},
        {"ticker": "AAPL", "name": "Apple",                  "qty": 10,  "avg": 260.63,  "value_ils": 8812,  "roi_pct": 14.34},
        {"ticker": "INTC", "name": "Intel",                  "qty": 15,  "avg": 114.48,  "value_ils": 5943,  "roi_pct": 17.05},
        {"ticker": "TER",  "name": "Teradyne",               "qty": 5,   "avg": 335.06,  "value_ils": 6475,  "roi_pct": 30.70},
        {"ticker": "RGTI", "name": "Rigetti Computing",      "qty": 100, "avg": 20.82,   "value_ils": 6316,  "roi_pct": 2.59},
        {"ticker": "DELL", "name": "Dell Technologies",      "qty": 5,   "avg": 351.70,  "value_ils": 6054,  "roi_pct": 16.43},
        {"ticker": "AVGO", "name": "Broadcom",               "qty": 5,   "avg": 375.54,  "value_ils": 6082,  "roi_pct": 9.53},
        {"ticker": "QCOM", "name": "Qualcomm",               "qty": 8,   "avg": 211.87,  "value_ils": 5349,  "roi_pct": 6.72},
        {"ticker": "RKLB", "name": "Rocket Lab USA",         "qty": 8,   "avg": 67.02,   "value_ils": 2537,  "roi_pct": 60.01},
    ]
    total = sum(h["value_ils"] for h in holdings)
    return jsonify({
        "date": "2026-06-21",
        "total_ils": 171674,
        "daily_change_pct": 3.59,
        "holdings": holdings,
        "positions": len(holdings)
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 7860)), debug=False)
