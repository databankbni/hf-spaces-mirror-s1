from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from utils.db import get_shop_by_slug, get_shop_index
import json

router = APIRouter()

@router.get("/{slug}", response_class=HTMLResponse)
async def seo_redirect(slug: str, request: Request):
    """SEO meta tag page for crawlers. Humans get redirected to app."""
    shop = get_shop_by_slug(slug.lower().strip())
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    shop_json = shop.get("shop_json", {})
    if isinstance(shop_json, str):
        try:
            shop_json = json.loads(shop_json)
        except:
            shop_json = {}

    plan = shop.get("plan", "free")
    business_name = shop_json.get("business_name", "My Hub")
    tagline = shop_json.get("tagline", "")
    description = shop_json.get("description", "") or tagline or f"Visit {business_name} on MyShub"
    logo_url = shop_json.get("logo_url", "")
    category = shop_json.get("category", "")
    location = shop_json.get("contact", {}).get("location", "") if isinstance(shop_json.get("contact"), dict) else ""
    catalog_url = shop_json.get("catalog", {}).get("url", "") if isinstance(shop_json.get("catalog"), dict) else ""

    if not logo_url:
        logo_url = "https://myshub.site/icon.svg"

    # Plan-aware SEO
    if plan == "premium":
        title = business_name
        site_name = ""
        og_title = business_name
        og_description = description
        og_image = logo_url
        twitter_card = "summary_large_image"
        twitter_title = business_name
        twitter_description = description
        twitter_image = logo_url
    elif plan == "pro":
        title = f"{business_name} - MyShub Hub"
        site_name = "MyShub Hub"
        og_title = f"{business_name} - MyShub Hub"
        og_description = description
        og_image = logo_url
        twitter_card = "summary_large_image"
        twitter_title = f"{business_name} - MyShub Hub"
        twitter_description = description
        twitter_image = logo_url
    else:
        title = f"{business_name} - MyShub Hub"
        site_name = "MyShub Hub"
        og_title = f"Visit {business_name} on MyShub"
        og_description = description
        og_image = "https://myshub.site/icon.svg"
        twitter_card = "summary"
        twitter_title = f"{business_name} - MyShub Hub"
        twitter_description = description
        twitter_image = "https://myshub.site/icon.svg"

    # Structured data (JSON-LD)
    structured_data = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness" if location else "Organization",
        "name": business_name,
        "description": description,
        "url": f"https://myshub.site/{slug}",
        "image": logo_url,
    }
    if location:
        structured_data["address"] = {"@type": "PostalAddress", "addressLocality": location}
    if catalog_url:
        structured_data["sameAs"] = [catalog_url]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
{f'<meta property="og:site_name" content="{site_name}">' if site_name else ''}
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{og_description}">
<meta property="og:image" content="{og_image}">
<meta property="og:url" content="https://myshub.site/{slug}">
<meta property="og:type" content="website">
<meta name="twitter:card" content="{twitter_card}">
<meta name="twitter:title" content="{twitter_title}">
<meta name="twitter:description" content="{twitter_description}">
<meta name="twitter:image" content="{twitter_image}">
<meta name="description" content="{description}">
<meta name="keywords" content="{business_name}, {category}, MyShub, business hub, online store">
<link rel="canonical" href="https://myshub.site/{slug}">
<script type="application/ld+json">{json.dumps(structured_data)}</script>
<style>body{{font-family:system-ui;margin:0;padding:40px;text-align:center;color:#333}}h1{{font-size:2rem;margin-bottom:10px}}p{{color:#666;max-width:500px;margin:0 auto 20px}}a{{display:inline-block;background:#1e40af;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600}}</style>
</head>
<body>
<h1>{business_name}</h1>
<p>{description}</p>
<a href="https://myshub.site/shop.html?slug={slug}">Visit Shop →</a>
<script>setTimeout(()=>window.location.href="https://myshub.site/shop.html?slug={slug}",2000)</script>
</body>
</html>"""
    return HTMLResponse(content=html)

@router.get("/sitemap.xml", response_class=PlainTextResponse)
def sitemap():
    """Generate XML sitemap for all active shops."""
    index = get_shop_index()
    urls = []
    for slug, meta in index.items():
        if meta.get("status") == "active":
            urls.append(f"""<url>
<loc>https://myshub.site/{slug}</loc>
<lastmod>{meta.get('created_at', '')[:10]}</lastmod>
<changefreq>weekly</changefreq>
<priority>0.8</priority>
</url>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url>
<loc>https://myshub.site/</loc>
<changefreq>daily</changefreq>
<priority>1.0</priority>
</url>
<url>
<loc>https://myshub.site/discover</loc>
<changefreq>daily</changefreq>
<priority>0.9</priority>
</url>
{chr(10).join(urls)}
</urlset>"""
    return PlainTextResponse(content=xml, media_type="application/xml")

@router.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return PlainTextResponse(
        content="""User-agent: *
Allow: /
Sitemap: https://myshub.site/sitemap.xml
""",
        media_type="text/plain"
    )
