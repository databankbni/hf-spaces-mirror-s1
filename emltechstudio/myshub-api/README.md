---
title: MyShub API
emoji: 🏪
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
---

# MyShub API

Backend for MyShub — business discovery platform.

## Architecture

- **Private Dataset** (`emltechstudio/myshub-db-private`): Users, admins, shop metadata
- **Public Dataset** (`emltechstudio/myshub-db-public`): Shop content files (unlimited scaling)
- **Local Disk Cache** (`/data/shops/`): Fast reads, synced to public dataset every 30s

## Environment Variables

Create a `.env` file or set these in Hugging Face Space settings:

```
HF_TOKEN=hf_your_token_here
DATASET_PRIVATE=emltechstudio/myshub-db-private
DATASET_PUBLIC=emltechstudio/myshub-db-public
IMGBB_KEY=your_imgbb_key
ADMIN_KEY=myshub-admin-2026
JWT_SECRET=your-strong-jwt-secret
```

## Setup Steps

### 1. Create Datasets

Create two datasets on Hugging Face:
- `emltechstudio/myshub-db-private` (Private)
- `emltechstudio/myshub-db-public` (Public)

### 2. Create HF Space

Create a new Space: `emltechstudio/myshub-api`
- SDK: Gradio/Streamlit/Blank (we use FastAPI directly)
- Hardware: Free tier (CPU)

### 3. Upload Files

Upload all files from this repo to the Space.

### 4. Set Environment Variables

In Space Settings → Secrets, add all environment variables.

### 5. Install Dependencies

The `requirements.txt` will be auto-installed by HF Spaces.

### 6. Restart Space

The app will start and restore shop data from public dataset.

## API Endpoints

### Auth (`/auth`)
- `POST /auth/register` — Create account + shop
- `POST /auth/login` — Login
- `GET /auth/security-questions?email=` — Get security questions
- `POST /auth/verify-security-answer` — Verify answer
- `POST /auth/reset-password` — Reset password

### Shop (`/shop`)
- `GET /shop/live/{slug}` — Public shop data (JSON)
- `GET /shop/preview/{slug}` — Owner preview (auth required)
- `GET /shop/status/{slug}` — Get plan status
- `PUT /shop/edit/{slug}` — Edit shop
- `POST /shop/upload` — Upload image
- `GET /shop/referrals` — Get referral stats
- `POST /shop/{slug}/deactivate` — Deactivate shop
- `POST /shop/{slug}/reactivate` — Reactivate shop

### Discover (`/discover`) — NEW
- `GET /discover` — List/search shops (paginated)
- `GET /discover/nearby?lat=&lng=&radius=` — Proximity search
- `GET /discover/categories` — List categories
- `GET /discover/category/{category}` — Shops by category

### Admin (`/admin`)
- `POST /admin/login` — Admin login
- `POST /admin/register` — Admin register
- `GET /admin/me` — Current admin info
- `GET /admin/analytics` — Platform analytics
- `GET /admin/shops` — List all shops
- `GET /admin/shop/{slug_or_email}` — Shop details
- `POST /admin/shop/{slug_or_email}/upgrade` — Upgrade plan
- `POST /admin/shop/{slug_or_email}/status` — Set status
- `GET /admin/referral-payouts` — Referral payouts

### Payment (`/payment`)
- `GET /payment/activate/{plan}` — Payment placeholder

### SEO
- `GET /sitemap.xml` — Dynamic sitemap
- `GET /robots.txt` — Robots file

## Plan Limits

| Feature | Free | Pro (₦1,500) | Premium (₦3,500) |
|---|---|---|---|
| Socials | 5 | 10 | Unlimited |
| Custom Links | 3 | 10 | Unlimited |
| Brand Colors | Basic | Full | Full |
| Gradients | ❌ | ❌ | ✅ |
| Custom Fonts | ❌ | ✅ | ✅ |
| Location/Map | ✅ | ✅ | ✅ |
| Analytics | Basic | Full | Full + Export |

## Data Flow

```
User creates shop → Backend saves to:
  ├── Private dataset (metadata: slug, plan, status, etc.)
  └── Public dataset (content: name, description, images, etc.)
      └── Local disk cache (/data/shops/)

Visitor requests shop → Backend reads from local disk (fast)

Every 30s → Background sync: local disk → public dataset

Space restarts → Restore from public dataset
```

## Notifications (Phase 2)

In-app notifications will be added later:
- Plan expiry reminders
- Milestone celebrations (first 100 visits, etc.)
- Custom admin messages

## Cloudflare Worker (for SEO)

Deploy this Worker to serve pre-rendered HTML to bots:

```javascript
// worker.js
addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request))
})

function isBot(userAgent) {
  const patterns = [
    'googlebot', 'bingbot', 'yandex', 'baiduspider',
    'facebookexternalhit', 'whatsapp', 'twitterbot', 'telegrambot',
    'linkedinbot', 'slackbot', 'discordbot', 'applebot',
    'crawler', 'spider', 'bot', 'preview'
  ]
  return patterns.some(p => userAgent.toLowerCase().includes(p))
}

async function handleRequest(request) {
  const url = new URL(request.url)
  const path = url.pathname

  const reserved = ['/', '/app', '/admin', '/discover', '/index.html', '/app.html', '/admin.html']
  if (reserved.includes(path) || path.startsWith('/static/')) {
    return fetch(request)
  }

  const ua = request.headers.get('User-Agent') || ''
  if (!isBot(ua)) {
    return fetch(request)
  }

  const slug = path.replace('/', '')
  const apiUrl = `https://emltechstudio-myshub-api.hf.space/shop/live/${slug}`

  try {
    const apiResponse = await fetch(apiUrl, { headers: { 'User-Agent': 'MyShub-Bot/1.0' }})
    if (!apiResponse.ok) return fetch(request)

    const shopData = await apiResponse.json()
    const shopJson = shopData.shop_json || {}

    const html = `<!DOCTYPE html>
<html>
<head>
  <title>${shopJson.business_name || 'MyShub Shop'} | MyShub</title>
  <meta name="description" content="${(shopJson.description || '').slice(0, 160)}">
  <meta property="og:title" content="${shopJson.business_name || 'MyShub Shop'}">
  <meta property="og:description" content="${(shopJson.description || '').slice(0, 160)}">
  <meta property="og:image" content="${shopJson.logo_url || 'https://myshub.site/icon.svg'}">
  <meta property="og:url" content="https://myshub.site/${slug}">
</head>
<body>
  <h1>${shopJson.business_name || 'MyShub Shop'}</h1>
  <p>${shopJson.description || ''}</p>
</body>
</html>`

    return new Response(html, { headers: { 'Content-Type': 'text/html' }})
  } catch (e) {
    return fetch(request)
  }
}
```

## Support

EML Tech Studio
