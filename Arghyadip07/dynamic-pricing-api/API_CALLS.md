# Dynamic Pricing API - cURL Examples

**Base URL**: `https://Arghyadip07-dynamic-pricing-api.hf.space`

---

## Health & Status

### Health Check
```bash
curl https://Arghyadip07-dynamic-pricing-api.hf.space/health
```

### Home
```bash
curl https://Arghyadip07-dynamic-pricing-api.hf.space/
```

---

## Pricing Endpoints

### Calculate Optimal Price
```bash
curl -X POST https://Arghyadip07-dynamic-pricing-api.hf.space/calculate_optimal_price \
  -H "Content-Type: application/json" \
  -d '{
    "current_price": 100,
    "competitor_price": 95,
    "inventory": 50,
    "day_of_week": 3,
    "unit_cost": 50
  }'
```

---

## Elasticity Endpoints

### Estimate Elasticity at Single Price Point
```bash
curl -X POST https://Arghyadip07-dynamic-pricing-api.hf.space/estimate_elasticity \
  -H "Content-Type: application/json" \
  -d '{
    "price": 100,
    "competitor_price": 95,
    "inventory": 50,
    "day_of_week": 3
  }'
```

### Estimate Elasticity Across Price Range
```bash
curl -X POST https://Arghyadip07-dynamic-pricing-api.hf.space/estimate_elasticity_range \
  -H "Content-Type: application/json" \
  -d '{
    "price": 100,
    "competitor_price": 95,
    "inventory": 50,
    "day_of_week": 3,
    "price_points": 5,
    "min_price": 50,
    "max_price": 150
  }'
```

---

## Reinforcement Learning (RL) Pricing

### Get RL-Based Price Recommendation
```bash
curl -X POST https://Arghyadip07-dynamic-pricing-api.hf.space/rl_pricing \
  -H "Content-Type: application/json" \
  -d '{
    "competitor_price": 95,
    "inventory": 50,
    "day_of_week": 3,
    "unit_cost": 60
  }'
```

### Train RL Agent
```bash
curl -X POST https://Arghyadip07-dynamic-pricing-api.hf.space/rl_training \
  -H "Content-Type: application/json" \
  -d '{
    "competitor_price": 95,
    "inventory": 50,
    "day_of_week": 3,
    "unit_cost": 60,
    "num_episodes": 5
  }'
```

---

## Autonomous Agent Endpoints

### Start Agent
```bash
curl -X POST https://Arghyadip07-dynamic-pricing-api.hf.space/agent/start
```

### Stop Agent
```bash
curl -X POST https://Arghyadip07-dynamic-pricing-api.hf.space/agent/stop
```

### Get Agent Status
```bash
curl https://Arghyadip07-dynamic-pricing-api.hf.space/agent/status
```

### Get Agent History (Last 50 decisions)
```bash
curl "https://Arghyadip07-dynamic-pricing-api.hf.space/agent/history?limit=50"
```

### Get Agent History (Last 20 decisions)
```bash
curl "https://Arghyadip07-dynamic-pricing-api.hf.space/agent/history?limit=20"
```

### Set Agent Interval (30 seconds)
```bash
curl -X POST "https://Arghyadip07-dynamic-pricing-api.hf.space/agent/interval?seconds=30"
```

### Set Agent Interval (60 seconds)
```bash
curl -X POST "https://Arghyadip07-dynamic-pricing-api.hf.space/agent/interval?seconds=60"
```

---

## API Documentation

- **Swagger UI**: https://Arghyadip07-dynamic-pricing-api.hf.space/docs
- **ReDoc**: https://Arghyadip07-dynamic-pricing-api.hf.space/redoc

---

## PowerShell Notes

If using PowerShell, use `-UseBasicParsing` to avoid security warnings:

```powershell
curl -UseBasicParsing https://Arghyadip07-dynamic-pricing-api.hf.space/health
```

Or use `Invoke-WebRequest`:

```powershell
$body = @{
    current_price = 100
    competitor_price = 95
    inventory = 50
    day_of_week = 3
    unit_cost = 50
} | ConvertTo-Json

Invoke-WebRequest -Uri "https://Arghyadip07-dynamic-pricing-api.hf.space/calculate_optimal_price" `
  -Method POST `
  -ContentType "application/json" `
  -Body $body
```

---

## Field Descriptions

### Common Fields
- **current_price**: Current product price (must be > 0)
- **competitor_price**: Competitor's price (must be > 0)
- **inventory**: Available units (must be >= 0)
- **day_of_week**: Day (0=Monday, 6=Sunday)
- **unit_cost**: Production cost (default: 60)

### Elasticity Fields
- **price**: Price point to analyze (must be > 0)
- **price_points**: Number of data points in range (3-20, default: 5)
- **min_price**: Minimum price for range (default: 50)
- **max_price**: Maximum price for range (default: 150)

### RL Training Fields
- **num_episodes**: Training episodes (1-100, default: 5)

### Agent Fields
- **seconds**: Pricing interval in seconds (5-3600)
- **limit**: Number of history records to retrieve (1-500, default: 50)

---

## Extended Endpoints (multi-product, inventory, signals, A/B, causal uplift)

Note: The extended endpoints below are provided by the full API codebase and may not be available on every hosted/demo instance. If you get a `404 Not Found` from a hosted URL (for example the demo HF space), run the API locally and call `http://localhost:8000` (or redeploy your server) to access these endpoints.

### Multi-product Optimize (local)
Submit multiple products and get per-product recommendations (grid-search heuristic).
```bash
curl -X POST http://localhost:8000/multi_product_optimize \
  -H "Content-Type: application/json" \
  -d '{"products": [{"product_id": 101, "current_price": 120, "unit_cost": 60, "inventory": 50, "competitor_price": 115}, {"product_id": 102, "current_price": 80, "unit_cost": 40, "inventory": 200, "competitor_price": 78}] }'
```

### Inventory-aware Optimize (local)
Adjust price considering inventory heuristics.
```bash
curl -X POST http://localhost:8000/inventory_optimize \
  -H "Content-Type: application/json" \
  -d '{"product_id": 101, "current_price": 120, "inventory": 10, "unit_cost": 60, "competitor_price": 115 }'
```

### Ingest Competitor Signal (local)
Post competitor price updates (stored to DB by default).
```bash
curl -X POST http://localhost:8000/competitor_signal \
  -H "Content-Type: application/json" \
  -d '{"product_id": 101, "competitor_price": 117.5, "source": "scraper-1", "timestamp": "2026-06-04T12:00:00Z" }'
```

### A/B Test — Assign (local)
Assign a subject to an experiment group.
```bash
curl -X POST http://localhost:8000/ab_test/assign \
  -H "Content-Type: application/json" \
  -d '{"experiment": "price_test_v1", "subject_id": "user_123" }'
```

### A/B Test — Record Outcome (local)
Record an outcome for an assigned subject (include `metric` for simple summaries).
```bash
curl -X POST http://localhost:8000/ab_test/outcome \
  -H "Content-Type: application/json" \
  -d '{"experiment": "price_test_v1", "subject_id": "user_123", "outcome": {"metric": 1, "revenue": 120.0} }'
```

### Causal Uplift Estimate (local)
Estimate uplift for a batch of feature vectors (stub model returns zeros until trained).
```bash
curl -X POST http://localhost:8000/causal_uplift/estimate \
  -H "Content-Type: application/json" \
  -d '{"features": [[0.1, 1.2, 3.4], [0.3, 0.8, 2.1]] }'
```

---

## Admin Endpoints (inspect persisted data)

These endpoints read from the configured database. By default the app uses a local SQLite file `data/dpai.sqlite`. To use Postgres (or another SQL DB) set `DATABASE_URL` in your environment before starting the server.

### List recent competitor signals (persisted)
```bash
curl "https://Arghyadip07-dynamic-pricing-api.hf.space/admin/competitor_signals?product_id=101&limit=50"
```

### A/B summary
```bash
curl "https://Arghyadip07-dynamic-pricing-api.hf.space/admin/ab_summary?experiment=price_test_v1"
```

### A/B recent outcomes
```bash
curl "https://Arghyadip07-dynamic-pricing-api.hf.space/admin/ab_outcomes?experiment=price_test_v1&limit=200"
```

---

## Notes on persistence
- Default (no env): local SQLite file at `data/dpai.sqlite` is used and created automatically.
- To use Postgres or another SQL DB, set `DATABASE_URL` to a SQLAlchemy-compatible URL (e.g. `postgresql+psycopg2://user:pass@host:5432/dbname`) before starting the server.

---
