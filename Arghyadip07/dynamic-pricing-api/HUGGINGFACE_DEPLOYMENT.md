# 🚀 Deploy to Hugging Face Spaces (100% FREE)

**Why Hugging Face Spaces?**
- ✅ Completely FREE
- ✅ Built for ML models & APIs
- ✅ One-click GitHub deploy
- ✅ No cold start issues
- ✅ Persistent storage for model artifacts
- ✅ Docker support for FastAPI

## Setup (5 minutes)

### 1. Create Hugging Face Account
```bash
# Go to https://huggingface.co
# Sign up with GitHub
```

### 2. Create New Space
```bash
# Go to https://huggingface.co/spaces
# Click "Create new Space"
# Name: dynamic-pricing-api
# License: openrail
# Space SDK: Docker
```

### 3. Configure Docker Space
```bash
# In your Space:
# Settings → Repository → 
# Link GitHub Repo: Arghyadip07/dynamic_pricing_ai
# Branch: master
```

### 4. Add Dockerfile (Already in repo!)
Your Dockerfile is already configured and will be auto-detected.

### 5. Deploy
```bash
# Hugging Face auto-builds and deploys
# Watch the logs at https://huggingface.co/spaces/Arghyadip07/dynamic-pricing-api
```

## Your Free API URL
```
https://Arghyadip07-dynamic-pricing-api.hf.space
```

## Testing

### Health Check
```bash
curl https://Arghyadip07-dynamic-pricing-api.hf.space/health
```

### Calculate Price
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

## Pricing
- **Docker Spaces**: FREE (CPU)
- **Persistent storage**: ✅ FREE (includes artifacts/)
- **Auto-deploy from GitHub**: ✅ FREE
- **Team members**: Unlimited

## Features
- ✅ Auto-restart on failure
- ✅ View logs in real-time
- ✅ Persistent `/data` directory for artifacts
- ✅ Free SSL certificates
- ✅ One-click GitHub integration

## Environment Variables
Set in Space Settings → Repository secrets:
```
API_HOST=0.0.0.0
API_PORT=8000
```

## File Structure in Space
```
/
├── Dockerfile
├── requirements.txt
├── scripts/
├── src/
├── artifacts/        (persisted)
├── data/processed/   (needs to be copied)
└── config/
```

---

**Status**: Ready to deploy to Hugging Face Spaces ✅
