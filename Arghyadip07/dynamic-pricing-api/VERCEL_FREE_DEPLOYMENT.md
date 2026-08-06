# 🚀 Deploy to Vercel (FREE Serverless)

**Why Vercel?**
- ✅ Completely FREE (up to 100GB bandwidth/month)
- ✅ One-click GitHub deploy
- ✅ Auto-scaling
- ✅ Global CDN
- ⚠️ Better for short-lived requests (serverless model)
- ⚠️ May have cold start delays

## Setup (5 minutes)

### 1. Install Vercel CLI
```bash
npm install -g vercel
# or use: npx vercel
```

### 2. Deploy
```bash
cd c:\Dynamic_pricing_AI
vercel
# Login with GitHub
# Select project settings as shown
```

### 3. Configure vercel.json
Already included in repo. Vercel will auto-detect.

### 4. Set Environment Variables
In Vercel Dashboard → Settings → Environment Variables:
```
API_HOST=0.0.0.0
API_PORT=8000
PYTHON_VERSION=3.11
```

## Your Free API URL
```
https://dynamic-pricing-ai-YOUR_USERNAME.vercel.app
```

## Testing

### Health Check
```bash
curl https://dynamic-pricing-ai-YOUR_USERNAME.vercel.app/health
```

### Calculate Price
```bash
curl -X POST https://dynamic-pricing-ai-YOUR_USERNAME.vercel.app/api/calculate_optimal_price \
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
- **Serverless Functions**: FREE
- **Bandwidth**: 100GB/month FREE
- **Build minutes**: 6000/month FREE
- **Edge Network**: ✅ FREE

## Known Limitations
- ⚠️ Cold starts (~3-5s first request after idle)
- ⚠️ Function timeout: 60 seconds
- ⚠️ Memory: 1GB per function
- ⚠️ Model loading on each invocation (slower)

## Upgrade Recommendation
If cold starts are unacceptable:
- **Vercel Pro**: $20/month → Better function limits
- **Or use**: Render.com or Hugging Face (better for this use case)

## Configuration Files
- `vercel.json`: Serverless function configuration
- `api/` directory: API routes for serverless

---

**Note**: For this pricing API, Hugging Face Spaces or Render is recommended over Vercel due to model loading overhead.
