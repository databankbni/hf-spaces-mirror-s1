"""
KOMBAZ // QUANT — Multi-Strategy Equity Intelligence
By Shai Kombaz · 2026 · https://kombaz.co

Combines four investing philosophies into one score:
  Simons (momentum/quant) · Buffett (quality/value) · Graham (margin of safety) · Ackman (catalyst/concentration)

Real market data via Stooq (no API key required). Optional Finnhub key for live quotes.
"""
from fastapi import FastAPI, Request, APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timezone
import os, io, csv, math, statistics, httpx, asyncio, random, json, hmac, hashlib

app = FastAPI(title="KOMBAZ QUANT", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ═══════════════════════════════════════════════════════════════
# KOMBAZ CREDITS — Wallet router (inlined here so the whole backend
# is a single app.py file — nothing extra to remember to upload)
# ═══════════════════════════════════════════════════════════════
wallet_router = APIRouter(prefix="/api/wallet", tags=["wallet"])

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
GUMROAD_WEBHOOK_SECRET = os.environ.get("GUMROAD_WEBHOOK_SECRET", "")

SB_HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
}


def _require_configured():
    """Wallet endpoints fail loudly with a clear message instead of the whole
    app crashing at import time if Supabase secrets aren't set yet."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise HTTPException(503, "wallet not configured yet — set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")


async def get_current_user_id(request: Request) -> str:
    """Verify the Supabase JWT sent by the frontend and return the user id.
    Reuses the same Supabase Auth you already run for KOMBAZ SYNTH — no new
    auth system needed."""
    _require_configured()
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = auth_header.split(" ", 1)[1]
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {token}"},
        )
    if r.status_code != 200:
        raise HTTPException(401, "invalid or expired session")
    return r.json()["id"]


async def _sb_insert_ledger_row(user_id: str, amount_cents: int, kind: str,
                                 source: str, reference_id: str | None,
                                 description: str):
    """Insert one ledger row. Relies on the unique (source, reference_id)
    index for idempotency — a duplicate webhook simply gets a 409 from
    Postgres, which we swallow as 'already processed'."""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{SUPABASE_URL}/rest/v1/wallet_ledger",
            headers={**SB_HEADERS, "Prefer": "return=representation"},
            json={
                "user_id": user_id,
                "amount_cents": amount_cents,
                "kind": kind,
                "source": source,
                "reference_id": reference_id,
                "description": description,
            },
        )
    if r.status_code == 409:
        return {"already_processed": True}
    if r.status_code >= 300:
        raise HTTPException(500, f"ledger write failed: {r.text}")
    return r.json()


async def _sb_get_balance(user_id: str) -> int:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/wallet_balances",
            headers=SB_HEADERS,
            params={"user_id": f"eq.{user_id}", "select": "balance_cents"},
        )
    rows = r.json()
    return rows[0]["balance_cents"] if rows else 0


@wallet_router.get("/balance")
async def get_balance(user_id: str = Depends(get_current_user_id)):
    cents = await _sb_get_balance(user_id)
    return {"balance_ils": cents / 100.0, "balance_cents": cents}


@wallet_router.get("/history")
async def get_history(user_id: str = Depends(get_current_user_id), limit: int = 50):
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/wallet_ledger",
            headers=SB_HEADERS,
            params={
                "user_id": f"eq.{user_id}",
                "select": "amount_cents,kind,source,description,created_at",
                "order": "created_at.desc",
                "limit": str(limit),
            },
        )
    return r.json()


class SpendRequest(BaseModel):
    amount_ils: float          # positive number, e.g. 25.00
    source: str                # 'academy' | 'synth-store' | 'market-stall'
    reference_id: str          # your own order/course id — for idempotency
    description: str


@wallet_router.post("/spend")
async def spend(body: SpendRequest, user_id: str = Depends(get_current_user_id)):
    if body.amount_ils <= 0:
        raise HTTPException(400, "amount_ils must be positive")
    cents = round(body.amount_ils * 100)
    balance = await _sb_get_balance(user_id)
    if balance < cents:
        raise HTTPException(402, "insufficient credit balance")
    result = await _sb_insert_ledger_row(
        user_id, -cents, "spend", body.source, body.reference_id, body.description
    )
    new_balance = await _sb_get_balance(user_id)
    return {"ok": True, "spent_ils": body.amount_ils, "new_balance_ils": new_balance / 100.0,
            "ledger": result}


# ─── Gumroad webhook: real-money top-up → credit ───────────────────────
# In Gumroad: Settings → Advanced → Ping URL → set to
#   https://<your-space>.hf.space/api/wallet/gumroad-webhook
# Sell a "KOMBAZ Credits ₪100 top-up" style product; the webhook credits
# the buyer's wallet automatically. The buyer must be logged in and have
# entered their kombaz account email at Gumroad checkout — match on email.

def _verify_gumroad_signature(raw_body: bytes, signature: str) -> bool:
    if not GUMROAD_WEBHOOK_SECRET:
        return True  # no secret configured — skip verification (dev only)
    expected = hmac.new(GUMROAD_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


@wallet_router.post("/gumroad-webhook")
async def gumroad_webhook(request: Request):
    _require_configured()
    raw = await request.body()
    form = await request.form()
    signature = request.headers.get("x-gumroad-signature", "")
    if not _verify_gumroad_signature(raw, signature):
        raise HTTPException(401, "bad signature")

    sale_id = form.get("sale_id")
    email = form.get("email")
    price_cents = int(form.get("price", "0"))  # Gumroad sends price in cents
    if not sale_id or not email or price_cents <= 0:
        raise HTTPException(400, "malformed webhook payload")

    # Look up the kombaz user by email via Supabase Auth admin API
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            headers=SB_HEADERS,
            params={"email": email},
        )
    users = r.json().get("users", [])
    if not users:
        # Buyer paid but has no kombaz account yet — log for manual reconciliation
        # rather than silently dropping real money.
        raise HTTPException(202, f"no kombaz account for {email} — needs manual credit")
    user_id = users[0]["id"]

    result = await _sb_insert_ledger_row(
        user_id=user_id,
        amount_cents=price_cents,
        kind="topup",
        source="gumroad",
        reference_id=sale_id,
        description=f"Gumroad top-up, sale {sale_id}",
    )
    return {"ok": True, "credited_cents": price_cents, "ledger": result}

app.include_router(wallet_router)

# Serve /static/* directly (images, js, css, data files) alongside the API routes below.
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# ─── Data layer: real daily prices, with fallback chain ───────────────────────
# Primary: Stooq CSV. Fallback: Yahoo Finance chart API. Neither needs a key.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KombazQuant/1.0)"}


async def _fetch_stooq(ticker: str):
    sym = ticker.lower() + ".us"
    url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
    try:
        async with httpx.AsyncClient(timeout=20, headers=HEADERS, follow_redirects=True) as client:
            r = await client.get(url)
        if r.status_code != 200 or "Date" not in r.text[:60]:
            return None
        rows = list(csv.DictReader(io.StringIO(r.text)))
        out = []
        for row in rows:
            try:
                out.append({"date": row["Date"], "close": float(row["Close"]),
                            "volume": float(row.get("Volume") or 0)})
            except (ValueError, KeyError):
                continue
        return out if len(out) >= 30 else None
    except Exception:
        return None


async def _fetch_yahoo(ticker: str):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}"
           f"?range=2y&interval=1d")
    try:
        async with httpx.AsyncClient(timeout=20, headers=HEADERS, follow_redirects=True) as client:
            r = await client.get(url)
        if r.status_code != 200:
            return None
        j = r.json()
        res = j.get("chart", {}).get("result")
        if not res:
            return None
        res = res[0]
        ts = res.get("timestamp", [])
        closes = res.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        vols = res.get("indicators", {}).get("quote", [{}])[0].get("volume", [])
        out = []
        for i, t in enumerate(ts):
            c = closes[i] if i < len(closes) else None
            if c is None:
                continue
            d = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
            out.append({"date": d, "close": float(c),
                        "volume": float(vols[i] or 0) if i < len(vols) and vols[i] else 0})
        return out if len(out) >= 30 else None
    except Exception:
        return None


async def fetch_stooq_daily(ticker: str):
    """Try Stooq first, then Yahoo. Returns list of {date, close, volume} or None."""
    data = await _fetch_stooq(ticker)
    if data:
        return data
    return await _fetch_yahoo(ticker)


def pct_change(series, lookback):
    """Percent change over the last `lookback` trading days."""
    if len(series) < lookback + 1:
        return None
    old = series[-(lookback + 1)]["close"]
    new = series[-1]["close"]
    if old == 0:
        return None
    return (new - old) / old * 100


def volatility(series, lookback=30):
    if len(series) < lookback + 1:
        return None
    closes = [s["close"] for s in series[-(lookback + 1):]]
    rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes)) if closes[i-1]]
    if len(rets) < 2:
        return None
    return statistics.pstdev(rets) * math.sqrt(252) * 100  # annualized %


def moving_avg(series, n):
    if len(series) < n:
        return None
    return sum(s["close"] for s in series[-n:]) / n


# ─── The four-philosophy scoring engine ───────────────────────────────────────
def score_symbol(series):
    """Return a dict of sub-scores (0-100) and a blended score."""
    price = series[-1]["close"]
    m1  = pct_change(series, 21)    # ~1 month
    m3  = pct_change(series, 63)    # ~3 months
    m6  = pct_change(series, 126)   # ~6 months
    m12 = pct_change(series, 252)   # ~1 year
    vol = volatility(series, 30)
    ma50  = moving_avg(series, 50)
    ma200 = moving_avg(series, 200)

    def clamp(x): return max(0, min(100, x))

    # SIMONS — momentum & trend. Reward positive multi-horizon momentum + price above MAs.
    sim = 50
    if m3 is not None:  sim += m3 * 0.8
    if m6 is not None:  sim += m6 * 0.4
    if ma50 and ma200 and price:
        if price > ma50:  sim += 8
        if ma50 > ma200:  sim += 8   # golden-cross regime
    simons = clamp(sim)

    # BUFFETT — quality/stability. Reward steady long-term uptrend + low volatility.
    buf = 50
    if m12 is not None: buf += m12 * 0.25
    if vol is not None: buf += (40 - vol) * 0.6   # lower vol => higher score
    buffett = clamp(buf)

    # GRAHAM — margin of safety. Reward being well below recent highs (cheap) but not collapsing.
    closes = [s["close"] for s in series[-252:]] if len(series) >= 252 else [s["close"] for s in series]
    hi = max(closes); lo = min(closes)
    drawdown = (hi - price) / hi * 100 if hi else 0  # how far below the high
    gra = 50 + drawdown * 0.7                          # cheaper = safer entry
    if m1 is not None and m1 < -15: gra -= 20          # but penalize a falling knife
    graham = clamp(gra)

    # ACKMAN — catalyst/concentration momentum. Reward strong recent breakout vs base.
    ack = 50
    if m1 is not None:  ack += m1 * 1.1
    if m3 is not None and m1 is not None and m1 > m3 / 3:  ack += 10  # accelerating
    ackman = clamp(ack)

    blended = round((simons + buffett + graham + ackman) / 4, 1)

    return {
        "price": round(price, 2),
        "mom_1m": round(m1, 2) if m1 is not None else None,
        "mom_3m": round(m3, 2) if m3 is not None else None,
        "mom_6m": round(m6, 2) if m6 is not None else None,
        "mom_12m": round(m12, 2) if m12 is not None else None,
        "volatility": round(vol, 1) if vol is not None else None,
        "above_ma50": bool(ma50 and price > ma50),
        "above_ma200": bool(ma200 and price > ma200),
        "drawdown_from_high": round(drawdown, 1),
        "scores": {
            "simons": round(simons, 1), "buffett": round(buffett, 1),
            "graham": round(graham, 1), "ackman": round(ackman, 1),
            "blended": blended,
        },
    }


# ─── Quantum Monte Carlo engine ───────────────────────────────────────────────
# Each simulated path is a "particle" undergoing a random walk (Geometric Brownian
# Motion) through price-space, with a jump-diffusion overlay layered on top to
# capture gap risk (earnings, catalyst news) that pure Gaussian diffusion misses.
# Drift & volatility are fitted from real historical daily log-returns — not
# guessed. Thousands of particles are fired at once; we read off the probability
# cloud of where they end up, whether each one crosses the Operation-1050 target
# or stop first, and how that probability accumulates day by day.

def _ewma_vol(log_rets, lam=0.94, seed_n=20):
    """RiskMetrics-style exponentially-weighted volatility — more regime-aware
    than a flat historical stdev, since recent moves are weighted more heavily."""
    if len(log_rets) < seed_n + 5:
        return statistics.pstdev(log_rets) or 1e-6
    var = statistics.pvariance(log_rets[:seed_n])
    for r in log_rets[seed_n:]:
        var = lam * var + (1 - lam) * r * r
    return math.sqrt(var) or 1e-6


def _calibrate_jumps(log_rets, sigma_hist):
    """Detect historical tail moves (>2.5 sigma) and calibrate a jump-diffusion
    overlay from them. Falls back to a light synthetic tail component if the
    history doesn't contain enough real jumps to calibrate from directly."""
    if sigma_hist <= 0:
        return 0.0, 0.0, 0.0, False
    threshold = 2.5 * sigma_hist
    jumps = [r for r in log_rets if abs(r) > threshold]
    n = len(log_rets)
    if len(jumps) >= 3:
        return len(jumps) / n, statistics.mean(jumps), (statistics.pstdev(jumps) or sigma_hist), True
    return 0.03, 0.0, sigma_hist * 2.0, False


def _monte_carlo_particles(series, days=30, n_paths=2000, target_pct=10.0, stop_pct=-8.0,
                            lookback=120, n_sample_paths=30):
    closes = [s["close"] for s in series]
    if len(closes) < 40:
        return None
    lb = min(lookback, len(closes) - 1)
    window = closes[-(lb + 1):]
    log_rets = [math.log(window[i] / window[i - 1])
                for i in range(1, len(window)) if window[i - 1] > 0 and window[i] > 0]
    if len(log_rets) < 15:
        return None

    mu = statistics.mean(log_rets)                      # fitted daily drift
    sigma_hist = statistics.pstdev(log_rets) or 1e-6     # flat historical volatility
    sigma = _ewma_vol(log_rets) or sigma_hist            # regime-aware (EWMA) volatility
    p_jump, jump_mean, jump_std, jump_calibrated = _calibrate_jumps(log_rets, sigma_hist)

    price0 = closes[-1]
    target_price = price0 * (1 + target_pct / 100)
    stop_price = price0 * (1 + stop_pct / 100)

    finals = []
    hit_target = hit_stop = 0
    target_hit_day = [0] * (days + 1)
    stop_hit_day = [0] * (days + 1)
    target_days = []
    sample_paths = []

    for i in range(n_paths):
        price = price0
        resolved = False
        trace = [round(price, 2)] if i < n_sample_paths else None
        for d in range(1, days + 1):
            z = random.gauss(0, 1)
            step = mu + sigma * z                        # diffusion step
            if random.random() < p_jump:
                step += jump_mean + jump_std * random.gauss(0, 1)   # jump overlay
            price *= math.exp(step)
            if trace is not None:
                trace.append(round(price, 2))
            if not resolved:
                if price >= target_price:
                    hit_target += 1
                    target_days.append(d)
                    target_hit_day[d] += 1
                    resolved = True
                elif price <= stop_price:
                    hit_stop += 1
                    stop_hit_day[d] += 1
                    resolved = True
        finals.append(price)
        if trace is not None:
            sample_paths.append(trace)

    finals.sort()
    n = len(finals)

    def pct_(q):
        idx = min(n - 1, max(0, int(n * q)))
        return round(finals[idx], 2)

    hit_neither = n - hit_target - hit_stop

    # 24-bin histogram of the final-price probability cloud
    lo, hi = finals[0], finals[-1]
    bins = 24
    span = (hi - lo) or 1.0
    counts = [0] * bins
    for f in finals:
        idx = min(bins - 1, int((f - lo) / span * bins))
        counts[idx] += 1
    edges = [round(lo + span * i / bins, 2) for i in range(bins + 1)]

    # cumulative hit-probability curves — how the odds build up day by day
    cum_target, cum_stop = [], []
    running_t = running_s = 0
    for d in range(1, days + 1):
        running_t += target_hit_day[d]
        running_s += stop_hit_day[d]
        cum_target.append(round(running_t / n * 100, 1))
        cum_stop.append(round(running_s / n * 100, 1))

    # theoretical edge / Kelly fraction from the simulated win rate & payoff ratio
    # (informational only — not a position-sizing recommendation)
    resolved_n = hit_target + hit_stop
    win_rate = (hit_target / resolved_n) if resolved_n > 0 else 0.5
    payoff_ratio = (target_pct / abs(stop_pct)) if stop_pct != 0 else target_pct
    kelly_raw = win_rate - (1 - win_rate) / payoff_ratio if payoff_ratio > 0 else 0.0
    kelly_pct = round(max(0.0, min(100.0, kelly_raw * 100)), 1)

    return {
        "price0": round(price0, 2),
        "target_price": round(target_price, 2),
        "stop_price": round(stop_price, 2),
        "days": days,
        "n_paths": n,
        "drift_daily_pct": round(mu * 100, 4),
        "vol_daily_pct": round(sigma * 100, 4),
        "vol_hist_daily_pct": round(sigma_hist * 100, 4),
        "vol_annualized_pct": round(sigma * math.sqrt(252) * 100, 1),
        "jump_prob_daily_pct": round(p_jump * 100, 2),
        "jump_calibrated": jump_calibrated,
        "prob_target_first": round(hit_target / n * 100, 1),
        "prob_stop_first": round(hit_stop / n * 100, 1),
        "prob_neither": round(hit_neither / n * 100, 1),
        "avg_days_to_target": round(statistics.mean(target_days), 1) if target_days else None,
        "expected_final_price": round(statistics.mean(finals), 2),
        "percentiles": {"p5": pct_(0.05), "p25": pct_(0.25), "p50": pct_(0.5),
                        "p75": pct_(0.75), "p95": pct_(0.95)},
        "histogram": {"edges": edges, "counts": counts},
        "cumulative": {"target": cum_target, "stop": cum_stop},
        "sample_paths": sample_paths,
        "win_rate_pct": round(win_rate * 100, 1),
        "payoff_ratio": round(payoff_ratio, 2),
        "kelly_pct": kelly_pct,
    }


# ─── Routes ───────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>KOMBAZ QUANT — index.html not found</h1>"


@app.get("/index.html", response_class=HTMLResponse)
async def index_html():
    return await root()


@app.get("/manifest.json")
async def manifest():
    if os.path.exists("manifest.json"):
        return FileResponse("manifest.json", media_type="application/manifest+json")
    return JSONResponse({"error": "manifest.json not found"}, status_code=404)


@app.get("/sw.js")
async def service_worker():
    if os.path.exists("sw.js"):
        return FileResponse("sw.js", media_type="application/javascript")
    return JSONResponse({"error": "sw.js not found"}, status_code=404)


@app.get("/api/missions")
async def missions():
    try:
        with open("static/data/missions.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"missions": []}


@app.get("/api/portfolio-snapshot")
async def portfolio_snapshot():
    """Static current-holdings snapshot for the Trading Vault UI — updated 14.08.2026.
    (Distinct from POST /api/portfolio below, which analyzes an arbitrary holdings list
    against live market data.)"""
    holdings = [
        {"ticker": "SNXX", "name": "Tradr 2X Long SNDK Daily ETF",   "qty": 757, "value_ils": 36047, "roi_pct": 66.99},
        {"ticker": "IONX", "name": "Defiance Dly T 2X L IonQ ETF",   "qty": 270, "value_ils": 26839, "roi_pct": -9.47},
        {"ticker": "ASML", "name": "ASML Holding NV",                "qty": 4,   "value_ils": 21545, "roi_pct": 2.31},
        {"ticker": "MULL", "name": "GraniteShares 2X Long MU ETF",   "qty": 258, "value_ils": 16931, "roi_pct": 13.57},
        {"ticker": "INTW", "name": "GraniteShares 2X Long INTC ETF", "qty": 196, "value_ils": 14284, "roi_pct": -19.38},
        {"ticker": "AMD",  "name": "Advanced Micro Devices",         "qty": 5,   "value_ils": 7515,  "roi_pct": -6.78},
        {"ticker": "IONQ", "name": "IonQ Inc",                       "qty": 54,  "value_ils": 7395,  "roi_pct": -3.84},
        {"ticker": "DELL", "name": "Dell Technologies -C",           "qty": 5,   "value_ils": 7308,  "roi_pct": 40.68},
        {"ticker": "TER",  "name": "Teradyne Inc",                   "qty": 5,   "value_ils": 5961,  "roi_pct": 20.45},
        {"ticker": "AVGO", "name": "Broadcom Inc",                   "qty": 5,   "value_ils": 5751,  "roi_pct": 3.68},
        {"ticker": "RGTI", "name": "Rigetti Computing Inc",          "qty": 100, "value_ils": 5521,  "roi_pct": -1.32},
        {"ticker": "AAPL", "name": "Apple Inc",                      "qty": 5,   "value_ils": 4516,  "roi_pct": 17.31},
        {"ticker": "PSEC", "name": "Prospect Capital Corp",          "qty": 7,   "value_ils": 48,    "roi_pct": 10.77},
    ]
    total = sum(h["value_ils"] for h in holdings)
    return {
        "date": "2026-08-14",
        "total_ils": round(total, 2),
        "daily_change_pct": 3.79,
        "cash_ils": -49408.58,
        "cash_usd": 1.01,
        "holdings": holdings,
        "positions": len(holdings),
    }





@app.get("/api/health")
async def health():
    return {"status": "online", "app": "KOMBAZ.ME / KOMBAZ QUANT", "version": "9.0",
            "portfolio_updated": "2026-08-14",
            "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    pw = body.get("password") or ""
    if pw == "shai1987":
        import hashlib
        token = hashlib.sha256(f"auth{datetime.now()}".encode()).hexdigest()[:24]
        return {"ok": True, "token": token, "role": "principal"}
    return JSONResponse({"ok": False, "error": "Access denied"}, status_code=401)


@app.get("/api/analyze/{ticker}")
async def analyze_ticker(ticker: str):
    """Full four-philosophy analysis for one ticker, real Stooq data."""
    series = await fetch_stooq_daily(ticker)
    if not series or len(series) < 30:
        return JSONResponse({"error": f"No data for {ticker.upper()}"}, status_code=404)
    result = score_symbol(series)
    result["ticker"] = ticker.upper()
    # 90-day price line for sparkline
    result["history"] = [{"date": s["date"], "close": round(s["close"], 2)} for s in series[-90:]]
    return result


@app.post("/api/scan")
async def scan(request: Request):
    """Scan & rank a watchlist of tickers by blended score."""
    body = await request.json()
    tickers = body.get("tickers", [])
    if not tickers:
        tickers = ["NVDA","AMD","AVGO","ASML","MU","QCOM","INTC","TER","SMCI","VRT","MOD",
                   "IONQ","RGTI","QBTS","QUBT","QNT","ARQQ",
                   "MARA","RIOT","CLSK","WULF","IREN","HUT","APLD",
                   "RKLB"]
    tickers = [t.strip().upper() for t in tickers if t.strip()][:30]
    # Fetch all tickers in parallel — much faster for large watchlists
    series_list = await asyncio.gather(*[fetch_stooq_daily(t) for t in tickers])
    results = []
    for t, series in zip(tickers, series_list):
        if series and len(series) >= 30:
            r = score_symbol(series)
            results.append({"ticker": t, "price": r["price"],
                            "mom_1m": r["mom_1m"], "mom_3m": r["mom_3m"],
                            "volatility": r["volatility"],
                            "scores": r["scores"]})
    results.sort(key=lambda x: x["scores"]["blended"], reverse=True)
    return {"count": len(results), "ranked": results,
            "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/api/rotation")
async def rotation(request: Request):
    """Operation-1050 style rotation sizing.
    Given capital and a fixed per-tail size, recommend top-2 concentrated positions."""
    body = await request.json()
    tickers = body.get("tickers", ["NVDA","AMD","AVGO","ASML","MU","QCOM"])
    capital = float(body.get("capital", 10000))
    tail_size = float(body.get("tail_size", 1050))
    tickers = [t.strip().upper() for t in tickers if t.strip()][:30]
    series_list = await asyncio.gather(*[fetch_stooq_daily(t) for t in tickers])
    scored = []
    for t, series in zip(tickers, series_list):
        if series and len(series) >= 30:
            r = score_symbol(series)
            scored.append({"ticker": t, "price": r["price"],
                           "blended": r["scores"]["blended"],
                           "mom_1m": r["mom_1m"], "volatility": r["volatility"]})
    scored.sort(key=lambda x: x["blended"], reverse=True)
    # Two-position concentration limit
    top2 = scored[:2]
    plan = []
    for s in top2:
        shares = int(tail_size // s["price"]) if s["price"] else 0
        alloc = round(shares * s["price"], 2)
        stop = round(s["price"] * 0.92, 2)   # pre-entry stop ~8% below
        target = round(s["price"] * 1.10, 2) # asymmetric ~10% target
        plan.append({"ticker": s["ticker"], "price": s["price"], "shares": shares,
                     "allocation": alloc, "stop": stop, "target": target,
                     "blended": s["blended"],
                     "risk": round((s["price"] - stop) * shares, 2),
                     "reward": round((target - s["price"]) * shares, 2)})
    return {"capital": capital, "tail_size": tail_size, "plan": plan,
            "candidates": scored[:8],
            "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/api/quantum/{ticker}")
async def quantum_sim(ticker: str, request: Request):
    """Quantum Monte Carlo — fire thousands of particle paths (GBM random walks)
    fitted to real historical drift/volatility, and read off the probability of
    reaching the Operation-1050 target before the stop."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    days = int(body.get("days", 30) or 30)
    n_paths = int(body.get("n_paths", 2000) or 2000)
    target_pct = float(body.get("target_pct", 10) or 10)
    stop_pct = float(body.get("stop_pct", -8) or -8)
    days = max(1, min(days, 252))
    n_paths = max(200, min(n_paths, 5000))

    series = await fetch_stooq_daily(ticker)
    if not series or len(series) < 40:
        return JSONResponse({"error": f"No data for {ticker.upper()}"}, status_code=404)

    result = _monte_carlo_particles(series, days=days, n_paths=n_paths,
                                     target_pct=target_pct, stop_pct=stop_pct)
    if result is None:
        return JSONResponse({"error": "Insufficient history for simulation"}, status_code=400)

    result["ticker"] = ticker.upper()
    result["timestamp"] = datetime.now(timezone.utc).isoformat()
    return result


# ─── Sector map (static, extend as needed) ────────────────────────────────────
SECTOR_MAP = {
    # AI Infra & Semiconductors — institutional backbone, clearer trends
    "NVDA":"AI Infra/Semis","AMD":"AI Infra/Semis","AVGO":"AI Infra/Semis","MU":"AI Infra/Semis",
    "QCOM":"AI Infra/Semis","INTC":"AI Infra/Semis","TER":"AI Infra/Semis","ASML":"AI Infra/Semis",
    "TSM":"AI Infra/Semis","ARM":"AI Infra/Semis","MRVL":"AI Infra/Semis","SMCI":"AI Infra/Semis",
    "VRT":"AI Infra/Semis","MOD":"AI Infra/Semis",
    # Quantum & Deep Tech — extreme volatility, mean-reversion / momentum-breakout candidates
    "IONQ":"Quantum/DeepTech","RGTI":"Quantum/DeepTech","QBTS":"Quantum/DeepTech",
    "QUBT":"Quantum/DeepTech","QNT":"Quantum/DeepTech","ARQQ":"Quantum/DeepTech",
    # Crypto Mining / DePIN → AI pivot — narrative shift from BTC-beta to AI power infra
    "MARA":"Crypto/DePIN-AI","RIOT":"Crypto/DePIN-AI","CLSK":"Crypto/DePIN-AI",
    "WULF":"Crypto/DePIN-AI","IREN":"Crypto/DePIN-AI","HUT":"Crypto/DePIN-AI","APLD":"Crypto/DePIN-AI",
    # Space / Defense
    "RKLB":"Space/Defense","SPCX":"Space/Defense","LUNR":"Space/Defense","ASTS":"Space/Defense",
    # Derivative / Income products — decay, not buy-and-hold
    "NVDY":"Derivative/Income","TSLY":"Derivative/Income","MSTY":"Derivative/Income",
    # Leveraged 2x daily-reset ETFs — compound decay in choppy markets, not buy-and-hold
    "INTW":"Leveraged 2x ETF","SNXX":"Leveraged 2x ETF","IONX":"Leveraged 2x ETF",
    # Big Tech / Other
    "AAPL":"Big Tech","MSFT":"Big Tech","GOOGL":"Big Tech","AMZN":"Big Tech","META":"Big Tech",
    "DELL":"Hardware","HPQ":"Hardware","SNDK":"Hardware","TSLA":"EV/Auto","RIVN":"EV/Auto",
    "HUBS":"Software/SaaS","PLTR":"Software/SaaS","CRM":"Software/SaaS","NOW":"Software/SaaS",
    "ADBE":"Software/SaaS","INTU":"Software/SaaS","NET":"Software/SaaS",
    "JPM":"Financials","BAC":"Financials","V":"Financials","MA":"Financials",
    "PSEC":"BDC/Income",
    "XOM":"Energy","CVX":"Energy","BE":"Clean Energy","PLUG":"Clean Energy",
    "JNJ":"Healthcare","PFE":"Healthcare","UNH":"Healthcare","LLY":"Healthcare","DHR":"Healthcare",
}

# Sector trading notes — surfaced in portfolio analysis
SECTOR_NOTES = {
    "Quantum/DeepTech": "Extreme volatility; early commercialization stage. Suited to mean-reversion or momentum-breakout strategies with tight risk management — partnership news can move these tens of percent in a day.",
    "Crypto/DePIN-AI": "Narrative shift underway: miners pivoting from BTC production to AI datacenter power/cooling infrastructure (e.g. WULF, IREN). No longer pure bitcoin beta.",
    "AI Infra/Semis": "Physical backbone of AI. Consistent institutional flows, clearer trends, less speculative noise — suited to steadier, longer-horizon strategies.",
    "Derivative/Income": "Option-income products decay over time. Not buy-and-hold instruments.",
    "Leveraged 2x ETF": "Daily-reset leverage compounds against you in choppy/sideways markets (volatility decay) even if the underlying is flat over time. Sized for short tactical holds, not long-term positions.",
}

def sector_of(t):
    return SECTOR_MAP.get(t.upper(), "Other")


@app.post("/api/portfolio")
async def portfolio(request: Request):
    """Analyze a real portfolio: holdings = [{ticker, shares, cost}].
    Returns per-holding scores, sector concentration, risk flags, totals."""
    body = await request.json()
    holdings = body.get("holdings", [])
    cash = float(body.get("cash", 0) or 0)  # negative = margin/leverage
    if not holdings:
        return JSONResponse({"error": "No holdings provided"}, status_code=400)

    rows = []
    total_value = 0.0
    total_cost = 0.0
    sector_value = {}

    # Normalize holdings, then fetch all price series in parallel
    norm = []
    for h in holdings:
        t = str(h.get("ticker", "")).strip().upper()
        shares = float(h.get("shares", 0) or 0)
        cost = float(h.get("cost", 0) or 0)  # cost basis per share (optional)
        if t and shares > 0:
            norm.append((t, shares, cost))
    series_list = await asyncio.gather(*[fetch_stooq_daily(t) for t, _, _ in norm])

    for (t, shares, cost), series in zip(norm, series_list):
        if not series or len(series) < 30:
            rows.append({"ticker": t, "error": True, "shares": shares})
            continue
        sc = score_symbol(series)
        price = sc["price"]
        value = round(price * shares, 2)
        cost_total = round(cost * shares, 2) if cost else None
        pl = round(value - cost_total, 2) if cost_total else None
        pl_pct = round((price - cost) / cost * 100, 1) if cost else None
        sector = sector_of(t)
        total_value += value
        if cost_total: total_cost += cost_total
        sector_value[sector] = sector_value.get(sector, 0) + value
        rows.append({
            "ticker": t, "shares": shares, "price": price, "value": value,
            "cost": cost or None, "pl": pl, "pl_pct": pl_pct, "sector": sector,
            "mom_1m": sc["mom_1m"], "mom_3m": sc["mom_3m"], "volatility": sc["volatility"],
            "drawdown_from_high": sc["drawdown_from_high"],
            "scores": sc["scores"], "above_ma50": sc["above_ma50"],
        })

    # weights & concentration
    for r in rows:
        if not r.get("error") and total_value:
            r["weight"] = round(r["value"] / total_value * 100, 1)

    sectors = sorted(
        [{"sector": s, "value": round(v, 2), "weight": round(v / total_value * 100, 1)}
         for s, v in sector_value.items()],
        key=lambda x: -x["value"]) if total_value else []

    # portfolio-level metrics
    valid = [r for r in rows if not r.get("error")]
    port_score = round(sum(r["scores"]["blended"] * r["value"] for r in valid) / total_value, 1) if total_value else 0
    port_vol = round(sum((r["volatility"] or 0) * r["value"] for r in valid) / total_value, 1) if total_value else 0

    # risk flags
    flags = []
    if sectors:
        top = sectors[0]
        if top["weight"] >= 60:
            flags.append({"level": "high", "msg": f"{top['weight']}% concentrated in {top['sector']} — very high single-sector risk."})
        elif top["weight"] >= 40:
            flags.append({"level": "med", "msg": f"{top['weight']}% in {top['sector']} — elevated concentration."})
    weak = [r for r in valid if r["scores"]["blended"] < 40]
    if weak:
        flags.append({"level": "med", "msg": f"{len(weak)} holding(s) score below 40: {', '.join(r['ticker'] for r in weak)}."})
    inc = [r for r in valid if r["sector"] == "Derivative/Income"]
    if inc:
        flags.append({"level": "info", "msg": f"Income/derivative products ({', '.join(r['ticker'] for r in inc)}) decay over time — not buy-and-hold."})
    big_dd = [r for r in valid if (r["drawdown_from_high"] or 0) > 25]
    if big_dd:
        flags.append({"level": "info", "msg": f"{len(big_dd)} holding(s) >25% below 1Y high — review thesis."})
    # Leverage / margin check
    if cash < 0 and total_value:
        lev_pct = round(abs(cash) / total_value * 100, 1)
        level = "high" if lev_pct >= 25 else "med"
        flags.append({"level": level,
            "msg": f"Negative cash balance ({cash:,.0f}) — ~{lev_pct}% of the portfolio is financed on margin. Leverage amplifies both gains and losses, and margin interest is a constant drag."})
    # Sector trading notes for sectors present in the portfolio (skip Derivative/Income — covered above)
    present_sectors = {r["sector"] for r in valid}
    for sec in present_sectors:
        if sec in SECTOR_NOTES and sec != "Derivative/Income":
            flags.append({"level": "note", "msg": f"[{sec}] {SECTOR_NOTES[sec]}"})
    if not flags:
        flags.append({"level": "ok", "msg": "No major concentration or quality flags detected."})

    total_pl = round(total_value - total_cost, 2) if total_cost else None
    total_pl_pct = round((total_value - total_cost) / total_cost * 100, 1) if total_cost else None

    rows.sort(key=lambda r: r.get("value", 0), reverse=True)
    return {
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2) if total_cost else None,
        "total_pl": total_pl, "total_pl_pct": total_pl_pct,
        "portfolio_score": port_score, "portfolio_volatility": port_vol,
        "holdings": rows, "sectors": sectors, "flags": flags,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/ai")
async def ai_brief(request: Request):
    """Optional Claude-powered narrative on the current scan."""
    body = await request.json()
    context = body.get("context", "")
    api_key = body.get("api_key", "")
    if not api_key:
        return JSONResponse({"error": "No API key provided"}, status_code=400)
    prompt = f"""You are a quantitative equity analyst. Given the scan data below, write a concise brief.

DATA:
{context}

Format:
TOP PICK: [ticker + one-line reason]
REGIME: [risk-on / risk-off / mixed, one line]
WATCH: [one risk to monitor]
Keep under 120 words. Not financial advice."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-sonnet-4-6", "max_tokens": 400,
                      "messages": [{"role": "user", "content": prompt}]})
        if resp.status_code != 200:
            return JSONResponse({"error": f"Claude API error: {resp.status_code}"}, status_code=502)
        return {"brief": resp.json()["content"][0]["text"]}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════
# HARDWARE BRIDGE — Trading Companion (ESP32 physical alert device)
# Thin polling layer over the existing scan/rotation engine. Nothing
# in score_symbol/fetch_stooq_daily is touched — this only reads their
# output and reshapes it into a tiny payload a microcontroller can
# parse in a few KB of RAM. A short-TTL in-memory cache means N
# devices polling every 10-30s never hammer Stooq/Yahoo directly.
# ═══════════════════════════════════════════════════════════════
HARDWARE_DEVICE_KEY = os.environ.get("HARDWARE_DEVICE_KEY", "")
_hw_cache: dict = {}          # cache_key -> (fetched_at_epoch, payload_dict)
_HW_CACHE_TTL = 45            # seconds — tune via HW_CACHE_TTL env if needed
_HW_DEFAULT_TICKERS = "NVDA,AMD,AVGO,ASML,MU,IONQ,RGTI,MARA,WULF,RKLB"


def _hw_check_key(request: Request):
    """Shared-secret check, same pattern as the Gumroad webhook above:
    if no key is configured, the endpoint stays open (dev/bench testing)."""
    if not HARDWARE_DEVICE_KEY:
        return
    supplied = request.headers.get("x-device-key") or request.query_params.get("key", "")
    if supplied != HARDWARE_DEVICE_KEY:
        raise HTTPException(401, "invalid device key")


def _hw_light(top_blended: float, flags: list) -> str:
    """Traffic-light classification for a physical RGB LED."""
    if any(f["level"] == "high" for f in flags):
        return "red"
    if top_blended >= 60:
        return "green"
    if top_blended >= 40:
        return "yellow"
    return "red"


@app.get("/api/hardware/config")
async def hardware_config(request: Request):
    """Remote config for the physical device — lets you retune poll
    interval / capital / tail size / default watchlist from env vars
    without reflashing firmware. Device reads this once at boot and
    again every config_refresh_sec."""
    _hw_check_key(request)
    return {
        "poll_interval_sec": int(os.environ.get("HW_POLL_INTERVAL", 20)),
        "config_refresh_sec": int(os.environ.get("HW_CONFIG_REFRESH", 1800)),
        "capital": float(os.environ.get("HW_CAPITAL", 10000)),
        "tail_size": float(os.environ.get("HW_TAIL_SIZE", 1050)),
        "green_threshold": 60,
        "yellow_threshold": 40,
        "default_tickers": os.environ.get("HW_TICKERS", _HW_DEFAULT_TICKERS),
    }


@app.get("/api/hardware/status")
async def hardware_status(request: Request, tickers: str = "",
                           capital: float = 10000, tail_size: float = 1050):
    """Minimal polling payload for the physical Trading Companion.
    GET only, tiny JSON, short-TTL cached. Safe for a device to hit
    every 10-30s. Reuses fetch_stooq_daily + score_symbol untouched —
    this endpoint only ranks and reshapes their existing output."""
    _hw_check_key(request)
    tlist = [t.strip().upper() for t in
             (tickers.split(",") if tickers
              else os.environ.get("HW_TICKERS", _HW_DEFAULT_TICKERS).split(","))
             if t.strip()][:15]

    cache_key = f"{','.join(tlist)}|{capital}|{tail_size}"
    now = datetime.now(timezone.utc).timestamp()
    cached = _hw_cache.get(cache_key)
    if cached and now - cached[0] < _HW_CACHE_TTL:
        payload = dict(cached[1])
        payload["cached"] = True
        return payload

    series_list = await asyncio.gather(*[fetch_stooq_daily(t) for t in tlist])
    scored = []
    for t, series in zip(tlist, series_list):
        if series and len(series) >= 30:
            r = score_symbol(series)
            scored.append({"ticker": t, "price": r["price"], "blended": r["scores"]["blended"],
                           "mom_1m": r["mom_1m"], "volatility": r["volatility"]})
    if not scored:
        raise HTTPException(502, "no market data available")
    scored.sort(key=lambda x: x["blended"], reverse=True)

    flags = []
    weak = [s for s in scored if s["blended"] < 40]
    if weak:
        flags.append({"level": "med", "msg": f"{len(weak)} weak candidate(s)"})
    high_vol = [s for s in scored if (s["volatility"] or 0) > 60]
    if high_vol:
        flags.append({"level": "high",
                      "msg": f"{len(high_vol)} high-volatility name(s): {','.join(s['ticker'] for s in high_vol)}"})

    top = scored[0]
    tail_plan = []
    for s in scored[:2]:
        shares = int(tail_size // s["price"]) if s["price"] else 0
        tail_plan.append({
            "ticker": s["ticker"], "shares": shares,
            "stop": round(s["price"] * 0.92, 2),
            "target": round(s["price"] * 1.10, 2),
            "blended": s["blended"],
        })

    payload = {
        "light": _hw_light(top["blended"], flags),
        "top_ticker": top["ticker"],
        "top_score": top["blended"],
        "top_price": top["price"],
        "tail_plan": tail_plan,
        "flags": flags,
        "avg_score": round(sum(s["blended"] for s in scored) / len(scored), 1),
        "n_scanned": len(scored),
        "cached": False,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }
    _hw_cache[cache_key] = (now, payload)
    return payload


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 7860)))
