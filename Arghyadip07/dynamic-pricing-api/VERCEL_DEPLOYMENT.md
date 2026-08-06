# Vercel Deployment Guide (FREE API Tier)

## Important: Vercel Limitations

⚠️ **Vercel is for serverless/APIs only** (not suitable for Streamlit dashboard)
- ✅ Can host FastAPI backend as serverless functions
- ❌ Cannot run Streamlit (needs persistent connection)

**Better Alternative:** Use **Railway.app** for BOTH services (truly free)
- See `RAILWAY_DEPLOYMENT.md` for complete free setup

---

## Option 1: Vercel API + Railway Dashboard (Recommended)

This is the best free setup:
- **API**: Deploy on Vercel (free)
- **Dashboard**: Deploy on Railway (free)

See `RAILWAY_DEPLOYMENT.md` for complete guide.

---

## Option 2: Vercel API Only (if you want to try)

### Step 1: Install Vercel CLI
```bash
npm install -g vercel
```

### Step 2: Login to Vercel
```bash
vercel login
```

### Step 3: Deploy API
```bash
cd c:\Dynamic_pricing_AI
vercel
```

### Step 4: Get API URL
```
https://your-project.vercel.app
```

### Step 5: Test API
```bash
curl https://your-project.vercel.app/calculate_optimal_price \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "current_price": 120,
    "competitor_price": 115,
    "inventory": 500,
    "day_of_week": 2,
    "unit_cost": 60
  }'
```

---

## ⚠️ Vercel Limitations

1. **Max Execution Time**: 30 seconds (not suitable for long operations)
2. **No Persistent State**: Model loading on every request
3. **Streaming**: Limited for Streamlit
4. **Cost**: Free tier included, but limited

---

## ✅ Better Solution: Railway.app

Use Railway instead - it's actually free and supports everything:

1. Docker deployment ✅
2. Streamlit dashboard ✅
3. FastAPI API ✅
4. Persistent services ✅
5. Free tier with $5 credit ✅

**See `RAILWAY_DEPLOYMENT.md` for complete free setup!**

---

## Why Railway > Vercel for this project?

| Feature | Vercel | Railway |
|---------|--------|---------|
| API Support | ✅ | ✅ |
| Streamlit | ❌ | ✅ |
| Docker | ❌ | ✅ |
| Free Tier | Limited | Generous ($5) |
| Persistence | No | Yes |
| Best for | Serverless | Full apps |

---

**Recommendation: Use Railway.app for full deployment!**
