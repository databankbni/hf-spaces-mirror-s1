---
title: Dynamic Pricing AI
emoji: 🤖
colorFrom: indigo
colorTo: blue
sdk: docker
pinned: false
---

# 🤖 Dynamic Pricing AI — Agentic Edition

An **autonomous AI pricing agent** that continuously perceives market conditions, decides optimal prices using ML + Reinforcement Learning, acts on those decisions, and learns from outcomes — all without human intervention.

> 🚀 **Live API:** `https://Arghyadip07-dynamic-pricing-api.hf.space`  
> 📖 **Interactive Docs:** `https://Arghyadip07-dynamic-pricing-api.hf.space/docs`

---

## 🧠 What Makes This Agentic?

This project crosses from an ML system into a **true AI agent** by implementing the classic agent loop autonomously:

```
┌─────────────────────────────────────────────────────────┐
│                  AUTONOMOUS AGENT LOOP                  │
│                  (every 30 seconds)                     │
│                                                         │
│  1. PERCEIVE  →  Sense competitor price, inventory,     │
│                  day-of-week from the market            │
│                                                         │
│  2. DECIDE    →  RL agent + XGBoost ML model compute    │
│                  the optimal price independently        │
│                                                         │
│  3. ACT       →  Emit the repricing decision with       │
│                  full audit trail + expected profit     │
│                                                         │
│  4. LEARN     →  RL agent trains on the experience,     │
│                  improving future decisions over time   │
└─────────────────────────────────────────────────────────┘
```

---

## 🏗️ Architecture

```
Dynamic_pricing_AI/
├── src/
│   ├── api/
│   │   └── pricing_api.py        # FastAPI — all endpoints incl. /agent/*
│   ├── services/
│   │   ├── pricing_agent.py      # 🆕 Autonomous agent (perceive→decide→act→learn)
│   │   ├── pricing_service.py    # ML-based optimal price calculation
│   │   ├── elasticity_service.py # Price sensitivity analysis
│   │   └── rl_pricing_service.py # Q-learning RL pricing policy
│   ├── models/
│   │   ├── demand.py             # XGBoost demand forecasting model
│   │   ├── elasticity_model.py   # Elasticity curve model
│   │   └── rl_pricing_agent.py   # Q-learning agent with replay buffer
│   ├── domain/
│   │   └── pricing.py            # Profit optimization logic
│   ├── features/
│   │   └── data_generation.py    # Synthetic market data pipeline
│   └── core/
│       └── settings.py           # Centralized configuration
├── apps/dashboard/
│   └── streamlit_app.py          # Streamlit frontend dashboard
├── scripts/                      # run_api, run_dashboard, run_pipeline
├── tests/                        # 22-test suite
├── artifacts/                    # Trained model artifacts (persisted)
├── data/                         # Raw + processed market data
└── Dockerfile                    # Production container
```

---

## 🔌 API Endpoints

### 🤖 Autonomous Agent Control

| Endpoint | Method | Description |
|---|---|---|
| `/agent/start` | `POST` | Start the autonomous repricing loop |
| `/agent/stop` | `POST` | Stop the agent gracefully |
| `/agent/status` | `GET` | Get cycles run, avg reward, last decision |
| `/agent/history` | `GET` | Retrieve last N repricing decisions |
| `/agent/interval` | `POST` | Change repricing frequency (5s–1h) |

#### `GET /agent/status` — Example Response
```json
{
  "running": true,
  "interval_seconds": 30.0,
  "cycles_completed": 48,
  "total_reward": 1243200.5,
  "average_reward": 25900.01,
  "history_size": 48,
  "last_decision": {
    "timestamp": "2026-05-19T08:12:01Z",
    "competitor_price": 97.5,
    "inventory": 143,
    "day_of_week": 1,
    "unit_cost": 58.3,
    "rl_price": 112.0,
    "ml_price": 109.5,
    "final_price": 112.0,
    "expected_profit": 26040.0,
    "episode_reward": 26040.0
  }
}
```

---

### 📊 ML Pricing Endpoints

#### 1. `POST /calculate_optimal_price`
Finds the profit-maximizing price using the XGBoost demand model.

```json
// Request
{
  "competitor_price": 115,
  "inventory": 500,
  "day_of_week": 2,
  "unit_cost": 60
}

// Response
{
  "optimal_price": 150.0,
  "expected_demand": 347.18,
  "expected_profit": 31246.73
}
```

#### 2. `POST /estimate_elasticity`
Estimates price elasticity of demand at a specific price point.

```json
// Request
{ "price": 120, "competitor_price": 115, "inventory": 500, "day_of_week": 2 }

// Response
{ "price": 120, "elasticity": -1.23, "interpretation": "Elastic (price-sensitive demand)" }
```

#### 3. `POST /estimate_elasticity_range`
Computes a full elasticity curve across a price range for strategic analysis.

```json
// Request
{
  "price": 120, "competitor_price": 115, "inventory": 500,
  "day_of_week": 2, "price_points": 5, "min_price": 100, "max_price": 140
}

// Response
{
  "market_context": { "current_price": 120, "competitor_price": 115, ... },
  "elasticity_curve": [
    {"price": 100.0, "elasticity": -0.95},
    {"price": 110.0, "elasticity": -1.12},
    {"price": 120.0, "elasticity": -1.23},
    {"price": 130.0, "elasticity": -1.35},
    {"price": 140.0, "elasticity": -1.45}
  ]
}
```

#### 4. `POST /rl_pricing`
Gets a price recommendation from the Q-learning RL policy.

```json
// Request
{ "competitor_price": 115, "inventory": 500, "day_of_week": 2, "unit_cost": 60 }

// Response
{ "rl_price": 128.0, "expected_profit": 25430.5, "strategy": "RL Policy" }
```

#### 5. `POST /rl_training`
Manually trigger RL agent training on simulated market episodes.

```json
// Request
{ "competitor_price": 115, "inventory": 500, "day_of_week": 2, "unit_cost": 60, "num_episodes": 5 }

// Response
{ "episodes_completed": 5, "average_reward": 18500.25, "max_reward": 32100.75, "buffer_size": 5 }
```

---

## 🛒 E-Commerce Integration

This API works with any platform that can make HTTP requests:

```
User visits product page
        ↓
Your backend calls → POST /calculate_optimal_price
        ↓
API returns optimal_price, expected_demand, expected_profit
        ↓
Display dynamic price to user
```

**Compatible with:** Shopify, WooCommerce, Magento, Headless/custom stacks.

---

## 🚀 Run Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Generate and process dataset
python scripts/run_pipeline.py

# 3. Start API (agent auto-starts)
python scripts/run_api.py

# 4. Start dashboard
python scripts/run_dashboard.py
```

---

## 🧪 Tests

```bash
python -m unittest discover -s tests -v
```

22 tests covering: demand model, pricing logic, elasticity, RL agent, API endpoints.

---

## ✅ Features

| Feature | Status |
|---|---|
| Autonomous agent loop (Perceive→Decide→Act→Learn) | ✅ |
| XGBoost demand forecasting | ✅ |
| Profit-maximizing price optimization | ✅ |
| Price elasticity estimation + curves | ✅ |
| Q-learning RL pricing policy | ✅ |
| Experience replay buffer | ✅ |
| Agent history + audit trail | ✅ |
| Dynamic repricing interval control | ✅ |
| Production-ready FastAPI backend | ✅ |
| Streamlit dashboard frontend | ✅ |
| Docker containerization | ✅ |
| Hugging Face Spaces deployment | ✅ |
| 22-test comprehensive test suite | ✅ |
