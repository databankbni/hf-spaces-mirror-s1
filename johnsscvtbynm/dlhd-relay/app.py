import re
import asyncio
import base64
import urllib.parse
import html as htmllib
import unicodedata
from curl_cffi.requests import AsyncSession
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

DLHD_DOMAINS = [
    "https://dlhd.st",          # current primary (dlhd.pk migrated here)
    "https://daddylivestream.com",
    "https://daddylive.watch",
    "https://thedaddy.to",
    "https://dlhd.link",
    "https://dlhd.sx",
    "https://dlhd.dad",
    "https://daddyhd.com",
    "https://dlhd.pk",          # legacy — kept last as fallback
]

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# Headers for media segment / playlist fetches (different Sec-Fetch values)
# NOTE: No Range header here — it must only be added for .ts segment fetches,
# not m3u8 playlists. Sending Range on a playlist can cause the CDN to return
# 206 partial content, truncating the playlist so hls.js can't parse it.
SEGMENT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "identity",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
}

# Persistent session with cookie jar shared across segment requests.
# Keyed by embed_url so different channels don't clobber each other's cookies.
# IMPORTANT: sessions are created lazily (no warm-up visit) to avoid adding
# latency and failure points. Cookies accumulate naturally from responses.
_cookie_sessions: dict[str, AsyncSession] = {}

async def get_session_for_embed(embed_url: str) -> AsyncSession:
    """Get or create a shared AsyncSession. The session persists across
    requests so cookies set by the CDN on the first response are carried
    forward to subsequent segment requests. This fixes both:
    1. The streaming bug (no async with context manager that closes early)
    2. Cookie persistence (CDNs set session cookies then check them)"""
    if embed_url not in _cookie_sessions:
        session = AsyncSession(impersonate="chrome120")
        _cookie_sessions[embed_url] = session
    return _cookie_sessions[embed_url]

# ── Helpers ───────────────────────────────────────────────────────────────────

async def fetch_first_live(session, path: str):
    for domain in DLHD_DOMAINS:
        url = f"{domain}{path}"
        try:
            r = await session.get(
                url,
                headers={**BROWSER_HEADERS, "Referer": f"{domain}/"},
                timeout=12,
            )
            if r.status_code == 200 and len(r.text) > 500:
                return domain, r
        except Exception:
            continue
    return None, None


def extract_stream_url(html: str) -> str | None:
    for pattern in [
        r"window\.atob\(['\"]([A-Za-z0-9+/=]+)['\"]\)",
        r"atob\(['\"]([A-Za-z0-9+/=]+)['\"]\)",
        r"source:\s*window\.atob\(['\"]([A-Za-z0-9+/=]+)['\"]\)",
    ]:
        m = re.search(pattern, html)
        if m:
            try:
                decoded = base64.b64decode(m.group(1)).decode("utf-8")
                if "m3u8" in decoded or "http" in decoded:
                    return decoded
            except Exception:
                continue

    m = re.search(r"source:\s*['\"]([^'\"]+\.m3u8[^'\"]*)['\"]", html)
    if m:
        return m.group(1)

    return None


def make_proxy_url(request, target_url: str, referer: str, embed: str = "") -> str:
    """Build a /proxy/segment?url=...&ref=...&embed=... URL pointing back at this relay.
    The embed param carries the full embed page URL so /proxy/segment can
    key into the shared cookie session."""
    base = str(request.base_url).rstrip("/")
    # Force https — HuggingFace internal routing may give http://
    # which causes mixed content blocks in the browser
    if base.startswith("http://"):
        base = "https://" + base[7:]
    encoded_url = urllib.parse.quote(target_url, safe="")
    encoded_ref = urllib.parse.quote(referer, safe="")
    # Include embed key so segment requests get the right cookie jar
    if embed:
        encoded_embed = urllib.parse.quote(embed, safe="")
        return f"{base}/proxy/segment?url={encoded_url}&ref={encoded_ref}&embed={encoded_embed}"
    return f"{base}/proxy/segment?url={encoded_url}&ref={encoded_ref}"


def rewrite_m3u8(content: str, m3u8_url: str, request, referer: str, embed: str = "") -> str:
    """
    Rewrite an m3u8 playlist so every segment URL and child playlist URL
    is replaced with a proxied /proxy/segment?url=...&ref=...&embed=... URL.

    Handles:
      - Absolute URLs  (https://cdn.example.com/seg.ts)
      - Protocol-relative URLs (//cdn.example.com/seg.ts)
      - Relative URLs  (seg001.ts  or  /tracks-v1a1/mono.m3u8)
    """
    base = m3u8_url.rsplit("/", 1)[0] + "/"   # directory of the m3u8

    def resolve(raw: str) -> str:
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        if raw.startswith("//"):
            return "https:" + raw
        if raw.startswith("/"):
            parsed = urllib.parse.urlparse(m3u8_url)
            return f"{parsed.scheme}://{parsed.netloc}{raw}"
        return base + raw

    lines = content.splitlines()
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            # Rewrite URI= attributes inside tags like #EXT-X-MAP, #EXT-X-KEY
            def replace_uri(match):
                uri = match.group(1)
                absolute = resolve(uri)
                proxied = make_proxy_url(request, absolute, referer, embed)
                return f'URI="{proxied}"'
            line = re.sub(r'URI="([^"]+)"', replace_uri, line)
            out.append(line)
        elif stripped == "":
            out.append(line)
        else:
            # Segment or child playlist URL
            absolute = resolve(stripped)
            proxied = make_proxy_url(request, absolute, referer, embed)
            out.append(proxied)
    return "\n".join(out)


# Track relay base URL from first real request so child m3u8 rewriting works
_relay_base_url: str | None = None

@app.middleware("http")
async def capture_base_url(request: Request, call_next):
    global _relay_base_url
    if _relay_base_url is None and request.url.path not in ("/health",):
        base = str(request.base_url).rstrip("/")
        # HuggingFace internal routing may give http:// — force https
        # so rewritten segment URLs aren't blocked as mixed content
        if base.startswith("http://"):
            base = "https://" + base[7:]
        _relay_base_url = base
    return await call_next(request)


# ── Core endpoints ────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/probe")
async def probe():
    results = {}
    async with AsyncSession(impersonate="chrome120") as session:
        for domain in DLHD_DOMAINS:
            try:
                r = await session.get(
                    f"{domain}/stream/stream-1.php",
                    headers={**BROWSER_HEADERS, "Referer": f"{domain}/"},
                    timeout=8,
                )
                results[domain] = {
                    "status": r.status_code,
                    "bytes": len(r.text),
                    "ok": r.status_code == 200 and len(r.text) > 500,
                }
            except Exception as e:
                results[domain] = {"status": "error", "error": str(e)[:120], "ok": False}
    return results


@app.get("/stream/{channel_num}")
async def get_stream(channel_num: int, request: Request):
    async with AsyncSession(impersonate="chrome120") as session:
        # Step 1 — fetch stream page
        domain, r1 = await fetch_first_live(session, f"/stream/stream-{channel_num}.php")
        if not r1:
            raise HTTPException(status_code=502, detail="Step 1: all domains failed — check /probe")

        # ── PRIMARY: inproviszon readable-slug path (the WORKING source) ──────
        # The player builds inproviszon.st/<slug>.m3u8 CLIENT-SIDE from the
        # channel name (e.g. 'Sky Sports F1' -> sky-sports-f1), so that URL never
        # appears in the page HTML or the daddy embed — which is exactly why the
        # scanners can't see it. We rebuild it directly from the channel name.
        try:
            names = _extract_channel_names(r1.text)
            nm = await _lookup_channel_name(session, channel_num)
            if nm:
                names.append(nm)
            names = list(dict.fromkeys(names))

            inpro_url = None
            slug = _slug_cache.get(channel_num)
            if slug:
                cu = f"{INPROVISZON}/{slug}.m3u8"
                cr = await session.get(cu, headers={**BROWSER_HEADERS, "Referer": VILE_REFERER}, timeout=10)
                if cr.status_code == 200 and "mpegurl" in (cr.headers.get("content-type") or "").lower():
                    inpro_url = cu
                else:
                    slug = None
            if not inpro_url:
                slug, inpro_url, _ = await resolve_inproviszon(session, names)
                if slug:
                    _slug_cache[channel_num] = slug

            if inpro_url:
                ir = await session.get(inpro_url, headers={**BROWSER_HEADERS, "Referer": VILE_REFERER}, timeout=10)
                if ir.status_code == 200:
                    rewritten = rewrite_m3u8(ir.text, inpro_url, request, VILE_REFERER, "")
                    from fastapi.responses import Response
                    return Response(
                        content=rewritten,
                        media_type="application/vnd.apple.mpegurl",
                        headers={
                            "Access-Control-Allow-Origin": "*",
                            "Cache-Control": "no-cache",
                            "X-Raw-Stream-Url": inpro_url,
                            "X-Resolved-Slug": slug or "",
                            "X-Source": "inproviszon",
                        },
                    )
        except Exception:
            pass  # fall through to the legacy phantemlis iframe path below

        iframe_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', r1.text, re.IGNORECASE)
        if not iframe_match:
            raise HTTPException(
                status_code=502,
                detail=f"Step 1: no iframe found in page from {domain} ({len(r1.text)} bytes)",
            )

        embed_url = iframe_match.group(1)
        if embed_url.startswith("//"):
            embed_url = "https:" + embed_url
        elif embed_url.startswith("/"):
            embed_url = domain + embed_url

        # Step 2 — fetch embed page
        try:
            r2 = await session.get(
                embed_url,
                headers={**BROWSER_HEADERS, "Referer": f"{domain}/"},
                timeout=12,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Step 2 fetch failed: {e}")

        if r2.status_code != 200:
            raise HTTPException(status_code=r2.status_code, detail=f"Step 2 HTTP {r2.status_code}")

        raw_stream_url = extract_stream_url(r2.text)
        if not raw_stream_url:
            raise HTTPException(
                status_code=502,
                detail=f"Step 2: no atob/m3u8 found in embed page ({embed_url})",
            )

        # Step 3 — fetch the raw m3u8 and rewrite it so segments go through /proxy/segment
        # Use the FULL embed URL as Referer (not just the origin) — daddylive-style
        # CDNs check the exact embed page path, not just the bare domain.
        embed_origin = "/".join(embed_url.split("/")[:3])  # https://host
        stream_referer = embed_url  # full embed page URL, not bare domain

        try:
            r3 = await session.get(
                raw_stream_url,
                headers={
                    **BROWSER_HEADERS,
                    "Referer": stream_referer,
                    "Origin": embed_origin,
                },
                timeout=10,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Step 3 m3u8 fetch failed: {e}")

        if r3.status_code != 200:
            # Surface the CDN's response body + key headers so we can see WHY it rejects.
            body_snip = ""
            try:
                body_snip = r3.text[:400]
            except Exception:
                body_snip = "<non-text body>"
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Step 3 HTTP {r3.status_code} | url={raw_stream_url} | "
                    f"ct={r3.headers.get('content-type')} | body={body_snip!r}"
                ),
            )

        rewritten = rewrite_m3u8(r3.text, raw_stream_url, request, stream_referer, embed_url)

        from fastapi.responses import Response
        return Response(
            content=rewritten,
            media_type="application/vnd.apple.mpegurl",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache",
                "X-Raw-Stream-Url": raw_stream_url,
                "X-Base-Domain": domain,
            },
        )


@app.get("/stream-url/{channel_num}")
async def get_stream_url(channel_num: int):
    """Legacy: returns the raw stream_url JSON (unproxied). Kept for debugging."""
    async with AsyncSession(impersonate="chrome120") as session:
        domain, r1 = await fetch_first_live(session, f"/stream/stream-{channel_num}.php")
        if not r1:
            raise HTTPException(status_code=502, detail="All domains failed")

        iframe_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', r1.text, re.IGNORECASE)
        if not iframe_match:
            raise HTTPException(status_code=502, detail="No iframe found")

        embed_url = iframe_match.group(1)
        if embed_url.startswith("//"):
            embed_url = "https:" + embed_url
        elif embed_url.startswith("/"):
            embed_url = domain + embed_url

        r2 = await session.get(embed_url, headers={**BROWSER_HEADERS, "Referer": f"{domain}/"}, timeout=12)
        stream_url = extract_stream_url(r2.text)
        if not stream_url:
            raise HTTPException(status_code=502, detail="No stream URL found")

        return {"channel_num": channel_num, "stream_url": stream_url, "embed_url": embed_url, "base_domain": domain}


# ── Player list endpoint (for frontend source picker) ──────────────────────────

@app.get("/stream_player/{channel_num}/{player_idx}")
async def stream_player(channel_num: int, player_idx: int, request: Request):
    """Return a proxied m3u8 for a SPECIFIC player index (1-based).
    The frontend calls /players_list/{num} first to get the list, then calls
    /stream_player/{num}/{idx} to load a specific source the user picked.
    """
    async with AsyncSession(impersonate="chrome120") as session:
        domain, r1 = await fetch_first_live(session, f"/stream/stream-{channel_num}.php")
        if not r1:
            raise HTTPException(status_code=502, detail="All domains failed")

        # Collect all candidate embed URLs
        embed_candidates: list[str] = []
        for u in re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', r1.text, re.IGNORECASE):
            if u.startswith("//"):
                u = "https:" + u
            elif u.startswith("/"):
                u = domain + u
            if u.startswith("http") and u not in embed_candidates:
                embed_candidates.append(u)

        # Expand daddyN.php variants
        expanded: list[str] = []
        for eu in embed_candidates:
            expanded.append(eu)
            m = re.search(r'daddy(\d+)\.php', eu, re.IGNORECASE)
            if m:
                for n in range(1, 8):
                    variant = re.sub(r'daddy\d+\.php', f'daddy{n}.php', eu, flags=re.IGNORECASE)
                    if variant not in expanded:
                        expanded.append(variant)
        embed_candidates = list(dict.fromkeys(expanded))

        if player_idx < 1 or player_idx > len(embed_candidates):
            raise HTTPException(status_code=400, detail=f"Invalid player index {player_idx}, available: 1-{len(embed_candidates)}")

        embed_url = embed_candidates[player_idx - 1]

        # Fetch embed page
        r2 = await session.get(embed_url, headers={**BROWSER_HEADERS, "Referer": f"{domain}/"}, timeout=12)
        if r2.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Embed HTTP {r2.status_code}")

        raw_stream_url = extract_stream_url(r2.text)
        if not raw_stream_url:
            raise HTTPException(status_code=502, detail=f"No stream URL in embed page")

        embed_origin = "/".join(embed_url.split("/")[:3])
        stream_referer = embed_url

        # Fetch master m3u8
        r3 = await session.get(raw_stream_url, headers={**BROWSER_HEADERS, "Referer": stream_referer, "Origin": embed_origin}, timeout=10)
        if r3.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Master HTTP {r3.status_code}")

        rewritten = rewrite_m3u8(r3.text, raw_stream_url, request, stream_referer, embed_url)
        from fastapi.responses import Response
        return Response(
            content=rewritten,
            media_type="application/vnd.apple.mpegurl",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache",
                "X-Raw-Stream-Url": raw_stream_url,
                "X-Player-Index": str(player_idx),
            },
        )


@app.get("/players_list/{channel_num}")
async def players_list(channel_num: int):
    """List ALL available players for a channel with generic names (Source 1, 2, 3...).
    Probes each daddyN.php embed -> master -> child playlist and returns which ones work.
    The frontend uses this to show a source picker so users can choose which stream to use.
    """
    out: dict = {"channel_num": channel_num, "players": [], "working_count": 0}
    async with AsyncSession(impersonate="chrome120") as session:
        domain, r1 = await fetch_first_live(session, f"/stream/stream-{channel_num}.php")
        if not r1:
            return out

        # Collect all candidate embed URLs
        embed_candidates: list[str] = []
        for u in re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', r1.text, re.IGNORECASE):
            if u.startswith("//"):
                u = "https:" + u
            elif u.startswith("/"):
                u = domain + u
            if u.startswith("http") and u not in embed_candidates:
                embed_candidates.append(u)

        # Expand daddyN.php variants
        expanded: list[str] = []
        for eu in embed_candidates:
            expanded.append(eu)
            m = re.search(r'daddy(\d+)\.php', eu, re.IGNORECASE)
            if m:
                for n in range(1, 8):
                    variant = re.sub(r'daddy\d+\.php', f'daddy{n}.php', eu, flags=re.IGNORECASE)
                    if variant not in expanded:
                        expanded.append(variant)
        embed_candidates = list(dict.fromkeys(expanded))

        source_idx = 0
        for embed_url in embed_candidates[:12]:
            source_idx += 1
            entry: dict = {
                "source_num": source_idx,
                "name": f"Source {source_idx}",
                "embed_url": embed_url,
                "working": False,
            }
            try:
                r2 = await session.get(embed_url, headers={**BROWSER_HEADERS, "Referer": f"{domain}/"}, timeout=10)
                if r2.status_code != 200:
                    entry["status"] = f"embed {r2.status_code}"
                    out["players"].append(entry)
                    continue

                raw_stream_url = extract_stream_url(r2.text)
                if not raw_stream_url:
                    entry["status"] = "no stream url"
                    out["players"].append(entry)
                    continue

                entry["cdn_host"] = urllib.parse.urlparse(raw_stream_url).netloc
                embed_origin = "/".join(embed_url.split("/")[:3])

                # Fetch master m3u8
                try:
                    rm = await session.get(raw_stream_url, headers={**BROWSER_HEADERS, "Referer": embed_url, "Origin": embed_origin}, timeout=10)
                except Exception as e:
                    entry["status"] = f"master error: {str(e)[:80]}"
                    out["players"].append(entry)
                    continue

                if rm.status_code != 200:
                    entry["status"] = f"master {rm.status_code}"
                    out["players"].append(entry)
                    continue

                # Find child playlist URL from master
                child_url = None
                base = raw_stream_url.rsplit("/", 1)[0] + "/"
                for line in rm.text.splitlines():
                    s = line.strip()
                    if s and not s.startswith("#"):
                        if s.startswith("http"):
                            child_url = s
                        elif s.startswith("//"):
                            child_url = "https:" + s
                        elif s.startswith("/"):
                            p = urllib.parse.urlparse(raw_stream_url)
                            child_url = f"{p.scheme}://{p.netloc}{s}"
                        else:
                            child_url = base + s
                        break

                if not child_url:
                    entry["status"] = "no child in master"
                    out["players"].append(entry)
                    continue

                # Reconstruct query params if child has none
                if "?" not in child_url:
                    q = urllib.parse.parse_qs(urllib.parse.urlparse(raw_stream_url).query)
                    md5v1 = (q.get("md5v1") or [""])[0]
                    expires = (q.get("expires") or [""])[0]
                    if md5v1 and expires:
                        child_url = f"{child_url}?md5={md5v1}&expires={expires}"

                # Probe the child playlist
                try:
                    rc = await session.get(child_url, headers={**BROWSER_HEADERS, "Referer": embed_url, "Origin": embed_origin}, timeout=10)
                except Exception as e:
                    entry["status"] = f"child error: {str(e)[:80]}"
                    out["players"].append(entry)
                    continue

                if rc.status_code == 200 and rc.text.strip().startswith("#EXTM3U"):
                    entry["working"] = True
                    entry["status"] = "live"
                    out["working_count"] += 1
                else:
                    entry["status"] = f"child {rc.status_code}"

                out["players"].append(entry)
            except Exception as e:
                entry["status"] = f"error: {str(e)[:80]}"
                out["players"].append(entry)

        return out


# ── Segment / m3u8 proxy ──────────────────────────────────────────────────────

@app.get("/proxy/segment")
async def proxy_segment(url: str, ref: str = "", embed: str = ""):
    """
    Proxy any segment (.ts) or child playlist (.m3u8) with the correct Referer
    and cookies.
    url   — fully qualified URL to fetch
    ref   — Referer header to send (the full embed page URL)
    embed — full embed page URL; used to key the shared cookie session so
            segment requests carry the same cookies the embed page set.
            Falls back to ref if not provided.
    """
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")

    # Use the full embed URL for the cookie session key
    embed_key = embed or ref or ""
    ref_origin = "/".join(ref.split("/")[:3]) if ref.startswith("http") else ""

    headers = {
        **SEGMENT_HEADERS,
    }
    if ref:
        headers["Referer"] = ref
    if ref_origin:
        headers["Origin"] = ref_origin

    # Detect m3u8 from URL BEFORE fetching — never rely on CDN content-type.
    # CDN obfuscates segment URLs with fake extensions (.pdf, .png, .jpg etc.)
    # so we can only trust .m3u8 — everything else is treated as a .ts segment.
    clean_url = url.split("?")[0]
    is_m3u8 = clean_url.endswith(".m3u8")

    try:
        # Use the shared cookie session keyed by embed URL so segment
        # requests carry the same cookies the embed page set. This is the
        # critical fix: daddylive CDNs set a session cookie on the embed
        # page, then check it on every segment request. A fresh session
        # per request has no cookies → CDN serves junk/filler TS segments.
        session = await get_session_for_embed(embed_key)

        if is_m3u8:
            # Fetch WITHOUT stream=True so .text is always populated.
            # Restreamer CDNs (Express/Varnish) intermittently 500 with
            # "Error fetching index playlist" — retry a few times before giving up.
            r = None
            for attempt in range(3):
                r = await session.get(url, headers=headers, timeout=15)
                if r.status_code == 200:
                    break
                if r.status_code in (401, 403):
                    raise HTTPException(status_code=r.status_code, detail=f"CDN rejected ({r.status_code}): {url}")
                await asyncio.sleep(0.4 * (attempt + 1))

            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Upstream {r.status_code} after retries | body={r.text[:200]!r}")

            relay_base = _relay_base_url or "https://johnsscvtbynm-dlhd-relay.hf.space"

            class _FakeRequest:
                def __init__(self, base_url):
                    self.base_url = base_url

            fake_req = _FakeRequest(relay_base + "/")
            rewritten = rewrite_m3u8(r.text, url, fake_req, ref, embed or ref)

            from fastapi.responses import Response as FastAPIResponse
            return FastAPIResponse(
                content=rewritten,
                media_type="application/vnd.apple.mpegurl",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Cache-Control": "no-cache",
                },
            )

        else:
            # Binary segment — CDN obfuscates with fake extensions (.pdf, .png, .jpg, .zst etc.)
            # Ignore extension and content-type entirely; always stream as video/mp2t.
            # The shared session carries cookies from the embed page warm-up.
            r = None
            for attempt in range(3):
                r = await session.get(url, headers=headers, timeout=15, stream=True)
                if r.status_code == 200:
                    break
                try:
                    r.aclose()
                except Exception:
                    pass
                if r.status_code in (401, 403):
                    raise HTTPException(status_code=r.status_code, detail=f"CDN rejected ({r.status_code}): {url}")
                await asyncio.sleep(0.4 * (attempt + 1))

            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Upstream {r.status_code} after retries")

            async def stream_body():
                try:
                    async for chunk in r.aiter_content():
                        yield chunk
                finally:
                    # Explicitly close the stream response to release the
                    # cloned curl handle back to the session pool. Without this,
                    # every segment leaks a handle until the session is GC'd.
                    try:
                        r.aclose()
                    except Exception:
                        pass

            return StreamingResponse(
                stream_body(),
                media_type="video/mp2t",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                },
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Proxy fetch failed: {str(e)[:200]}")


# ── Diagnostics ──────────────────────────────────────────────────────────────

@app.get("/debug/{channel_num}")
async def debug_stream(channel_num: int):
    """Walk every step of resolution and return a JSON trace so we can see
    exactly where/why a channel fails. Safe to call repeatedly."""
    trace: dict = {"channel_num": channel_num, "steps": []}
    async with AsyncSession(impersonate="chrome120") as session:
        # Step 1 — stream page
        domain, r1 = await fetch_first_live(session, f"/stream/stream-{channel_num}.php")
        if not r1:
            trace["steps"].append({"step": 1, "ok": False, "error": "all domains failed"})
            return trace
        iframe_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', r1.text, re.IGNORECASE)
        trace["steps"].append({
            "step": 1, "ok": True, "domain": domain,
            "status": r1.status_code, "bytes": len(r1.text),
            "iframe_found": bool(iframe_match),
        })
        if not iframe_match:
            trace["stream_page_snip"] = r1.text[:1500]
            return trace

        embed_url = iframe_match.group(1)
        if embed_url.startswith("//"):
            embed_url = "https:" + embed_url
        elif embed_url.startswith("/"):
            embed_url = domain + embed_url

        # Step 2 — embed page
        try:
            r2 = await session.get(embed_url, headers={**BROWSER_HEADERS, "Referer": f"{domain}/"}, timeout=12)
        except Exception as e:
            trace["steps"].append({"step": 2, "ok": False, "embed_url": embed_url, "error": str(e)[:200]})
            return trace

        html2 = r2.text
        # Detect modern DaddyLive auth-flow variables (if present, old atob extraction is dead)
        def grab(pat):
            m = re.search(pat, html2, re.IGNORECASE)
            return m.group(1) if m else None
        auth_vars = {
            "channelKey":  grab(r'channelKey\s*=\s*["\\\']([^"\\\']+)'),
            "authTs":      grab(r'(?:authTs|__c)\s*=\s*["\\\']([^"\\\']+)'),
            "authRnd":     grab(r'authRnd\s*=\s*["\\\']([^"\\\']+)'),
            "authSig":     grab(r'authSig\s*=\s*["\\\']([^"\\\']+)'),
            "auth_host":   grab(r'(?:auth_host|authHost)\s*=\s*["\\\']([^"\\\']+)'),
            "server_lookup": grab(r'([^"\\\']*server_lookup[^"\\\']*)'),
            "has_atob":    bool(re.search(r'atob\(', html2)),
            "has_iframe":  bool(re.search(r'<iframe', html2, re.IGNORECASE)),
            "nested_iframe": grab(r'<iframe[^>]+src=["\\\']([^"\\\']+)'),
        }
        raw_stream_url = extract_stream_url(html2)
        trace["steps"].append({
            "step": 2, "ok": True, "embed_url": embed_url,
            "status": r2.status_code, "bytes": len(html2),
            "extracted_stream_url": raw_stream_url,
            "auth_vars": auth_vars,
        })
        trace["embed_page_snip"] = html2[:2500]

        if not raw_stream_url:
            return trace

        # Step 3 — fetch the m3u8 exactly like /stream does
        embed_origin = "/".join(embed_url.split("/")[:3])
        try:
            r3 = await session.get(
                raw_stream_url,
                headers={**BROWSER_HEADERS, "Referer": embed_url, "Origin": embed_origin},
                timeout=10,
            )
            trace["steps"].append({
                "step": 3, "ok": r3.status_code == 200, "url": raw_stream_url,
                "status": r3.status_code,
                "content_type": r3.headers.get("content-type"),
                "resp_headers": dict(r3.headers),
                "body_snip": r3.text[:600],
            })
        except Exception as e:
            trace["steps"].append({"step": 3, "ok": False, "url": raw_stream_url, "error": str(e)[:200]})
            return trace

        # Step 4/5 — test the CHILD media playlist + first segment (the hop that fails at runtime)
        child_abs = None
        if r3.status_code == 200:
            base = raw_stream_url.rsplit('/', 1)[0] + '/'
            for line in r3.text.splitlines():
                s = line.strip()
                if s and not s.startswith('#'):
                    if s.startswith('http'):
                        child_abs = s
                    elif s.startswith('/'):
                        p = urllib.parse.urlparse(raw_stream_url)
                        child_abs = f"{p.scheme}://{p.netloc}{s}"
                    else:
                        child_abs = base + s
                    break

        rc_seg = None
        rc_brw = None
        if child_abs:
            # 4a — child with the SAME headers /proxy/segment currently uses
            try:
                rc_seg = await session.get(child_abs, headers={**SEGMENT_HEADERS, "Referer": embed_url, "Origin": embed_origin}, timeout=12)
                trace["steps"].append({"step": "4a-child-SEGMENT_HEADERS", "url": child_abs, "ok": rc_seg.status_code == 200, "status": rc_seg.status_code, "content_type": rc_seg.headers.get("content-type"), "body_snip": rc_seg.text[:400]})
            except Exception as e:
                trace["steps"].append({"step": "4a", "url": child_abs, "ok": False, "error": str(e)[:200]})
            # 4b — child with BROWSER_HEADERS (same style that made index succeed)
            try:
                rc_brw = await session.get(child_abs, headers={**BROWSER_HEADERS, "Referer": embed_url, "Origin": embed_origin}, timeout=12)
                trace["steps"].append({"step": "4b-child-BROWSER_HEADERS", "url": child_abs, "ok": rc_brw.status_code == 200, "status": rc_brw.status_code, "content_type": rc_brw.headers.get("content-type"), "body_snip": rc_brw.text[:400]})
            except Exception as e:
                trace["steps"].append({"step": "4b", "url": child_abs, "ok": False, "error": str(e)[:200]})
            # 4c — child in a BRAND-NEW COLD session: this is EXACTLY what /proxy/segment
            # does at runtime (get_session_for_embed makes a fresh session that never
            # visited the embed/index). If 4a/4b pass but 4c fails, the runtime bug is proven.
            try:
                async with AsyncSession(impersonate="chrome120") as cold:
                    rc_cold = await cold.get(child_abs, headers={**SEGMENT_HEADERS, "Referer": embed_url, "Origin": embed_origin}, timeout=12)
                    trace["steps"].append({"step": "4c-child-COLD-session", "note": "mimics /proxy/segment runtime path", "url": child_abs, "ok": rc_cold.status_code == 200, "status": rc_cold.status_code, "content_type": rc_cold.headers.get("content-type"), "body_snip": rc_cold.text[:400]})
            except Exception as e:
                trace["steps"].append({"step": "4c", "url": child_abs, "ok": False, "error": str(e)[:200]})
            # 4d — child with NO Referer/Origin at all (isolates whether headers matter)
            try:
                async with AsyncSession(impersonate="chrome120") as bare:
                    rc_bare = await bare.get(child_abs, headers={**SEGMENT_HEADERS}, timeout=12)
                    trace["steps"].append({"step": "4d-child-NO-referer", "url": child_abs, "ok": rc_bare.status_code == 200, "status": rc_bare.status_code, "content_type": rc_bare.headers.get("content-type"), "body_snip": rc_bare.text[:400]})
            except Exception as e:
                trace["steps"].append({"step": "4d", "url": child_abs, "ok": False, "error": str(e)[:200]})

            media = rc_brw if (rc_brw is not None and rc_brw.status_code == 200) else (rc_seg if (rc_seg is not None and rc_seg.status_code == 200) else None)
            if media is not None:
                seg_abs = None
                cbase = child_abs.rsplit('/', 1)[0] + '/'
                for line in media.text.splitlines():
                    s = line.strip()
                    if s and not s.startswith('#'):
                        if s.startswith('http'):
                            seg_abs = s
                        elif s.startswith('/'):
                            p = urllib.parse.urlparse(child_abs)
                            seg_abs = f"{p.scheme}://{p.netloc}{s}"
                        else:
                            seg_abs = cbase + s
                        break
                if seg_abs:
                    try:
                        rs = await session.get(seg_abs, headers={**SEGMENT_HEADERS, "Referer": embed_url, "Origin": embed_origin}, timeout=12)
                        trace["steps"].append({"step": "5-first-segment", "url": seg_abs[:220], "ok": rs.status_code == 200, "status": rs.status_code, "content_type": rs.headers.get("content-type"), "content_length": rs.headers.get("content-length")})
                    except Exception as e:
                        trace["steps"].append({"step": "5", "url": seg_abs[:220], "ok": False, "error": str(e)[:200]})
    return trace


@app.get("/resolve/{num}")
async def resolve(num: int):
    """Diagnostic for the inproviszon primary path: shows the channel names we
    extracted, the slug candidates, and which slug (if any) resolves to a live
    inproviszon.st/<slug>.m3u8. If resolved_slug is null, paste 'names' back to
    me so we can fix the name source."""
    async with AsyncSession(impersonate="chrome120") as session:
        domain, r1 = await fetch_first_live(session, f"/stream/stream-{num}.php")
        if not r1:
            raise HTTPException(status_code=502, detail="stream page failed on all domains")
        names = _extract_channel_names(r1.text)
        nm = await _lookup_channel_name(session, num)
        if nm:
            names.append(nm)
        names = list(dict.fromkeys(names))
        cands = []
        for n in names:
            cands += slug_candidates(n)
        cands = list(dict.fromkeys(cands))
        slug, url, report = await resolve_inproviszon(session, names)
        return {
            "num": num,
            "names": names,
            "candidate_count": len(cands),
            "candidates_top": cands[:15],
            "resolved_slug": slug,
            "manifest": url,
            "probe_report": report[:15],
        }


@app.get("/childprobe/{num}")
async def childprobe(num: int):
    """Isolate the child media-playlist 500. Master carries md5v1 AND md5v2 but
    rewrites the child to md5v1 - try every signature permutation to see which
    one the origin actually accepts, plus a cold-start warm-up retry."""
    out: dict = {"num": num, "variants": []}
    async with AsyncSession(impersonate="chrome120") as s:
        domain, r1 = await fetch_first_live(s, f"/stream/stream-{num}.php")
        if not r1:
            raise HTTPException(status_code=502, detail="stream page failed on all domains")
        m = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', r1.text, re.IGNORECASE)
        if not m:
            raise HTTPException(status_code=502, detail="no iframe on stream page")
        embed = m.group(1)
        if embed.startswith("//"):
            embed = "https:" + embed
        elif embed.startswith("/"):
            embed = domain + embed
        r2 = await s.get(embed, headers={**BROWSER_HEADERS, "Referer": f"{domain}/"}, timeout=12)
        master = extract_stream_url(r2.text)
        out["embed"] = embed
        out["master"] = master
        if not master:
            out["error"] = "could not extract master url from embed"
            return out

        q = urllib.parse.parse_qs(urllib.parse.urlparse(master).query)
        md5v1 = (q.get("md5v1") or [""])[0]
        md5v2 = (q.get("md5v2") or [""])[0]
        expires = (q.get("expires") or [""])[0]
        out["parsed"] = {"md5v1": md5v1, "md5v2": md5v2, "expires": expires}

        hdrs = {**BROWSER_HEADERS, "Referer": embed, "Origin": "/".join(embed.split("/")[:3])}
        rm = await s.get(master, headers=hdrs, timeout=12)
        out["master_status"] = rm.status_code
        child_rel = next((ln.strip() for ln in rm.text.splitlines()
                          if ln.strip() and not ln.startswith("#")), None)
        out["child_rel"] = child_rel
        if not child_rel:
            out["error"] = "no child playlist line in master"
            return out
        base = master.rsplit("/", 1)[0] + "/"
        cpath = base + child_rel.split("?")[0]  # strip the master-supplied query
        out["child_path"] = cpath

        variants = {
            "a_md5v1_only":    f"{cpath}?md5={md5v1}&expires={expires}",          # current (known 500)
            "b_md5v2_only":    f"{cpath}?md5={md5v2}&expires={expires}",          # <-- prime suspect
            "c_full_master_q": f"{cpath}?md5v1={md5v1}&md5v2={md5v2}&expires={expires}",
            "d_md5v2_as_v1":   f"{cpath}?md5v1={md5v2}&expires={expires}",
            "e_both":          f"{cpath}?md5={md5v1}&md5v2={md5v2}&expires={expires}",
        }
        for name, url in variants.items():
            rec: dict = {"name": name, "url": url}
            try:
                rr = await s.get(url, headers=hdrs, timeout=12)
                rec["status"] = rr.status_code
                rec["ct"] = rr.headers.get("content-type")
                rec["body_snip"] = rr.text[:120]
            except Exception as e:
                rec["error"] = str(e)[:150]
            out["variants"].append(rec)

        # cold-start test: retry the CURRENT child a few times with a real delay
        warm = []
        for _ in range(6):
            rr = await s.get(variants["a_md5v1_only"], headers=hdrs, timeout=12)
            warm.append(rr.status_code)
            if rr.status_code == 200:
                break
            await asyncio.sleep(1.2)
        out["warmup_statuses"] = warm
    return out


def _scanall_abs(link: str, domain: str, page_url: str) -> str:
    if link.startswith("http"):
        return link
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("/"):
        return domain + link
    return page_url.rsplit("/", 1)[0] + "/" + link


@app.get("/scanall/{num}")
async def scanall(num: int):
    """Enumerate EVERY candidate player on the stream page (not just daddyN
    variants) and resolve each one end-to-end: embed -> master -> CHILD.
    Reports each player's CDN host + child status so the WORKING source
    (a different embed host than the dead phantemlis one) actually shows up.
    Anything with child_status 200 is a live, playable player."""
    out: dict = {"num": num, "candidates": [], "WORKING": []}
    async with AsyncSession(impersonate="chrome120") as session:
        domain, r1 = await fetch_first_live(session, f"/stream/stream-{num}.php")
        if not r1:
            raise HTTPException(status_code=502, detail="stream page failed on all domains")
        html = r1.text
        page_url = f"{domain}/stream/stream-{num}.php"
        out["domain"] = domain

        # ---- Discover candidate embed/player URLs from EVERYTHING on the page ----
        cands: list[str] = []

        def add(u: str):
            if not u:
                return
            u = _scanall_abs(u.strip(), domain, page_url)
            if u.startswith("http") and u not in cands:
                cands.append(u)

        for u in re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I):
            add(u)
        for u in re.findall(r'data-(?:url|src|link|embed|file|stream|server)=["\']([^"\']+)["\']', html, re.I):
            add(u)
        for u in re.findall(r'["\'](https?:\\?/\\?/[^"\']+\.php[^"\']*)["\']', html):
            add(u.replace("\\/", "/"))
        # any full https url that looks like an embed/player/stream endpoint
        for u in re.findall(r'https?://[^\s"\'\\<>]+', html):
            if any(k in u.lower() for k in ("embed", "player", "/premiumtv/", "daddy", ".m3u8", "stream")):
                add(u)
        # decode base64 blobs on the MAIN page (some server lists are obfuscated)
        for b in re.findall(r"atob\(\s*['\"]([A-Za-z0-9+/=]{16,})['\"]\s*\)", html):
            try:
                dec = base64.b64decode(b).decode("utf-8", "ignore")
            except Exception:
                continue
            for u in re.findall(r'https?://[^\s"\'\\<>]+', dec):
                add(u)
        # expand daddyN.php variants of anything we found
        for u in list(cands):
            m = re.search(r'daddy(\d+)\.php', u, re.I)
            if m:
                for n in range(1, 7):
                    add(re.sub(r'daddy\d+\.php', f'daddy{n}.php', u, flags=re.I))

        out["discovered"] = cands[:60]

        # ---- Resolve each candidate end-to-end ----
        for embed_url in cands[:40]:
            entry: dict = {"embed_url": embed_url}
            try:
                r2 = await session.get(embed_url, headers={**BROWSER_HEADERS, "Referer": f"{domain}/"}, timeout=12)
                entry["embed_status"] = r2.status_code
                if r2.status_code != 200:
                    out["candidates"].append(entry); continue
                master = extract_stream_url(r2.text)
                entry["master_url"] = master
                if not master:
                    entry["note"] = "no stream url in embed"
                    out["candidates"].append(entry); continue
                entry["cdn_host"] = urllib.parse.urlparse(master).netloc
                embed_origin = "/".join(embed_url.split("/")[:3])
                hdrs = {**BROWSER_HEADERS, "Referer": embed_url, "Origin": embed_origin}
                rm = await session.get(master, headers=hdrs, timeout=12)
                entry["master_status"] = rm.status_code
                if rm.status_code != 200:
                    out["candidates"].append(entry); continue
                child = None
                base = master.rsplit("/", 1)[0] + "/"
                for line in rm.text.splitlines():
                    s = line.strip()
                    if s and not s.startswith("#"):
                        child = s if s.startswith("http") else (base + s)
                        break
                entry["child_url"] = child
                if child:
                    rc = await session.get(child, headers=hdrs, timeout=12)
                    entry["child_status"] = rc.status_code
                    entry["child_body"] = rc.text[:100]
                    entry["WORKS"] = rc.status_code == 200
                    if entry["WORKS"]:
                        out["WORKING"].append({"embed_url": embed_url, "cdn_host": entry["cdn_host"], "master_url": master})
            except Exception as e:
                entry["error"] = str(e)[:160]
            out["candidates"].append(entry)
    return out


@app.get("/players/{channel_num}")
async def list_players(channel_num: int):
    """Enumerate EVERY candidate player/server/mirror on the stream page so we
    can see exactly how dlhd.st exposes its multiple players. Makes no
    assumptions about the markup — dumps all iframes, switcher buttons/links,
    data-* url attrs, and JS php-url arrays."""
    out: dict = {"channel_num": channel_num}
    async with AsyncSession(impersonate="chrome120") as session:
        domain, r1 = await fetch_first_live(session, f"/stream/stream-{channel_num}.php")
        if not r1:
            out["error"] = "all domains failed"
            return out
        html = r1.text
        out["domain"] = domain
        out["bytes"] = len(html)

        # 1) every iframe src (relay currently only uses the FIRST of these)
        out["iframes"] = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)

        # 2) every anchor/button that looks like a player/server switcher
        players = []
        for m in re.finditer(r'<(a|button)\b([^>]*)>(.*?)</\1>', html, re.IGNORECASE | re.DOTALL):
            attrs = m.group(2)
            text = re.sub(r'<[^>]+>', '', m.group(3)).strip()
            blob = (attrs + " " + text).lower()
            if any(k in blob for k in ("player", "server", "mirror", "embed", "stream", ".php", "watch", "channel")):
                players.append({"tag": m.group(1), "text": text[:60], "attrs": attrs.strip()[:300]})
        out["player_buttons"] = players[:40]

        # 3) data-* url attributes (players are often data-url / data-src)
        out["data_urls"] = re.findall(r'data-(?:url|src|link|embed|file|stream|server)=["\']([^"\']+)["\']', html, re.IGNORECASE)[:40]

        # 4) JS url arrays / server lists referencing .php endpoints
        js_urls = re.findall(r'["\'](https?:\\?/\\?/[^"\']+\.php[^"\']*)["\']', html)
        out["js_php_urls"] = list(dict.fromkeys(js_urls))[:40]

        # 5) explicit players/servers JS arrays if present
        out["script_arrays"] = re.findall(r'(?:players?|servers?|sources?)\s*[:=]\s*(\[[^\]]{0,700}\])', html, re.IGNORECASE)[:10]

    return out


@app.get("/scanplayers/{channel_num}")
async def scan_players(channel_num: int):
    """Resolve EVERY daddyN.php player variant end-to-end (embed -> index -> CHILD)
    and report each player's CDN host + child-playlist status. This validates the
    multi-player theory vs a datacenter-IP block:
      - if some player's child returns 200  -> multi-player fallback is the fix
      - if ALL players' children 500 (across different CDN hosts) -> IP/source issue
    """
    result: dict = {"channel_num": channel_num, "players": []}
    async with AsyncSession(impersonate="chrome120") as session:
        domain, r1 = await fetch_first_live(session, f"/stream/stream-{channel_num}.php")
        if not r1:
            result["error"] = "all domains failed"
            return result
        iframe_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', r1.text, re.IGNORECASE)
        if not iframe_match:
            result["error"] = "no iframe on stream page"
            return result
        base_embed = iframe_match.group(1)
        if base_embed.startswith("//"):
            base_embed = "https:" + base_embed
        elif base_embed.startswith("/"):
            base_embed = domain + base_embed
        result["base_embed"] = base_embed

        # Build daddyN.php variants by swapping the number in the embed path.
        m = re.search(r'daddy(\d+)\.php', base_embed, re.IGNORECASE)
        if m:
            variants = [re.sub(r'daddy\d+\.php', f'daddy{n}.php', base_embed, flags=re.IGNORECASE) for n in range(1, 7)]
        else:
            variants = [base_embed]
        variants = list(dict.fromkeys(variants))  # de-dup, keep order

        for embed_url in variants:
            entry: dict = {"embed_url": embed_url}
            try:
                r2 = await session.get(embed_url, headers={**BROWSER_HEADERS, "Referer": f"{domain}/"}, timeout=12)
                entry["embed_status"] = r2.status_code
                if r2.status_code != 200:
                    result["players"].append(entry); continue
                raw = extract_stream_url(r2.text)
                entry["stream_url"] = raw
                if not raw:
                    entry["error"] = "no stream url extracted"
                    result["players"].append(entry); continue
                entry["cdn_host"] = urllib.parse.urlparse(raw).netloc
                embed_origin = "/".join(embed_url.split("/")[:3])
                ri = await session.get(raw, headers={**BROWSER_HEADERS, "Referer": embed_url, "Origin": embed_origin}, timeout=10)
                entry["index_status"] = ri.status_code
                if ri.status_code != 200:
                    entry["index_body"] = ri.text[:120]
                    result["players"].append(entry); continue
                child = None
                base = raw.rsplit('/', 1)[0] + '/'
                for line in ri.text.splitlines():
                    s = line.strip()
                    if s and not s.startswith('#'):
                        child = s if s.startswith('http') else (base + s)
                        break
                entry["child_url"] = child
                if child:
                    rc = await session.get(child, headers={**SEGMENT_HEADERS, "Referer": embed_url, "Origin": embed_origin}, timeout=12)
                    entry["child_status"] = rc.status_code
                    entry["child_body"] = rc.text[:120]
                    entry["WORKS"] = rc.status_code == 200
            except Exception as e:
                entry["error"] = str(e)[:160]
            result["players"].append(entry)
    return result


@app.get("/probe2")
async def probe2(index: str = "", manifest: str = "", segment: str = ""):
    """Test, FROM THE HF RELAY, reachability of the REAL working chain discovered
    in the browser. Pass URL-encoded query params:
      index    = the phantemlis .../index.m3u8 (checks for a 3xx redirect Location)
      manifest = the inproviszon.st/<slug>.m3u8 (can the relay reach it? 200?)
      segment  = a tiktokcdn ...tplv-tiktokx-origin.image segment (200?)
    """
    out: dict = {}
    async with AsyncSession(impersonate="chrome120") as s:
        for key, url in (("index", index), ("manifest", manifest), ("segment", segment)):
            if not url:
                continue
            url = urllib.parse.unquote(url)
            rec: dict = {"url": url[:220]}
            # (a) no-redirect: reveals Location header if it 3xx-redirects
            try:
                r = await s.get(url, headers=BROWSER_HEADERS, allow_redirects=False, timeout=15)
                rec["status_noredirect"] = r.status_code
                rec["location"] = r.headers.get("location")
                rec["content_type"] = r.headers.get("content-type")
                rec["server"] = r.headers.get("server")
                rec["cf_cache"] = r.headers.get("cf-cache-status")
                rec["acao"] = r.headers.get("access-control-allow-origin")
                rec["body_snip"] = r.text[:300]
            except TypeError:
                # older curl_cffi without allow_redirects kw
                r = await s.get(url, headers=BROWSER_HEADERS, timeout=15)
                rec["status_followed"] = r.status_code
                rec["content_type"] = r.headers.get("content-type")
                rec["server"] = r.headers.get("server")
                rec["body_snip"] = r.text[:300]
            except Exception as e:
                rec["error"] = str(e)[:200]
            out[key] = rec
    return out


@app.get("/cfprobe")
async def cfprobe(url: str, referer: str = ""):
    """Try to beat the Cloudflare 403 on a manifest URL with several header
    strategies. If NONE return 200, it's a hard bot/IP block (needs residential
    proxy or a browser-side fetch); if one works, we adopt those headers."""
    url = urllib.parse.unquote(url)
    strategies = [
        ("minimal", {}),
        ("browser_headers", dict(BROWSER_HEADERS)),
        ("ref_romponalis", {**BROWSER_HEADERS, "Referer": "https://hamis.romponalis.st/", "Origin": "https://hamis.romponalis.st"}),
        ("ref_dlhd", {**BROWSER_HEADERS, "Referer": "https://dlhd.st/", "Origin": "https://dlhd.st"}),
        ("ref_self", {**BROWSER_HEADERS, "Referer": "https://inproviszon.st/", "Origin": "https://inproviszon.st"}),
    ]
    if referer:
        referer = urllib.parse.unquote(referer)
        strategies.append(("ref_custom", {**BROWSER_HEADERS, "Referer": referer, "Origin": referer.rstrip('/')}))
    out: dict = {"url": url[:220], "results": []}
    async with AsyncSession(impersonate="chrome120") as s:
        for name, hdrs in strategies:
            rec: dict = {"strategy": name}
            try:
                r = await s.get(url, headers=hdrs, timeout=15)
                rec["status"] = r.status_code
                rec["server"] = r.headers.get("server")
                rec["cf_ray"] = r.headers.get("cf-ray")
                rec["content_type"] = r.headers.get("content-type")
                rec["body_snip"] = r.text[:160]
            except Exception as e:
                rec["error"] = str(e)[:160]
            out["results"].append(rec)
    return out


@app.get("/replayprobe")
async def replayprobe(url: str, cookie: str = "", referer: str = "", ua: str = ""):
    """THE decisive IP-vs-session test. Replay the EXACT cookies/headers from the
    browser's WORKING manifest request, but from the relay's (datacenter) IP.
      - 200  => access is SESSION/COOKIE based -> we can replicate it server-side, NO proxy.
      - 403  => access is IP/ASN bound -> the relay's IP is the blocker -> need residential proxy.
    """
    url = urllib.parse.unquote(url)
    hdrs = dict(BROWSER_HEADERS)
    if cookie:
        hdrs["Cookie"] = urllib.parse.unquote(cookie)
    if referer:
        referer = urllib.parse.unquote(referer)
        hdrs["Referer"] = referer
        hdrs["Origin"] = referer.rstrip("/")
    if ua:
        hdrs["User-Agent"] = urllib.parse.unquote(ua)
    out: dict = {
        "url": url[:220],
        "sent_cookie_len": len(hdrs.get("Cookie", "")),
        "sent_referer": hdrs.get("Referer"),
    }
    async with AsyncSession(impersonate="chrome120") as s:
        try:
            r = await s.get(url, headers=hdrs, timeout=15)
            out["status"] = r.status_code
            out["server"] = r.headers.get("server")
            out["cf_ray"] = r.headers.get("cf-ray")
            out["content_type"] = r.headers.get("content-type")
            out["body_snip"] = r.text[:200]
        except Exception as e:
            out["error"] = str(e)[:200]
    return out


@app.get("/vileprobe")
async def vileprobe(url: str, referer: str = "https://vileembeds.pages.dev/"):
    """Fetch a vileembeds player/embed URL from the relay and extract HOW it
    resolves the real inproviszon manifest (discovery). Reports any inproviszon
    URLs, .m3u8 refs, atob blobs (decoded), and api/announce endpoints."""
    url = urllib.parse.unquote(url)
    referer = urllib.parse.unquote(referer)
    hdrs = {**BROWSER_HEADERS, "Referer": referer, "Origin": referer.rstrip("/")}
    out: dict = {"url": url[:220]}
    async with AsyncSession(impersonate="chrome120") as s:
        try:
            r = await s.get(url, headers=hdrs, timeout=20)
            out["status"] = r.status_code
            out["content_type"] = r.headers.get("content-type")
            body = r.text
            out["bytes"] = len(body)
            out["inproviszon_urls"] = list(dict.fromkeys(
                re.findall(r"https?://[^\s'\"\\<>]*inproviszon[^\s'\"\\<>]*", body)))[:10]
            out["m3u8_refs"] = list(dict.fromkeys(
                re.findall(r"[^\s'\"\\<>()]+\.m3u8[^\s'\"\\<>()]*", body)))[:10]
            blobs = re.findall(r"atob\(['\"]([A-Za-z0-9+/=]{16,})['\"]\)", body)[:5]
            decoded = []
            for b in blobs:
                try:
                    decoded.append(base64.b64decode(b).decode("utf-8", "replace")[:200])
                except Exception:
                    decoded.append("<decode-failed>")
            out["atob_decoded"] = decoded
            out["api_endpoints"] = list(dict.fromkeys(
                re.findall(r"https?://[^\s'\"\\<>]*(?:api|ann\.|cdn-lab|ntwkbc|/ip)[^\s'\"\\<>]*", body)))[:15]
            out["script_srcs"] = list(dict.fromkeys(
                re.findall(r"<script[^>]+src=['\"]([^'\"]+)['\"]", body)))[:15]
            out["body_head"] = body[:800]
        except Exception as e:
            out["error"] = str(e)[:200]
    return out


# ── Discovery: channel name -> inproviszon slug ────────────────────────
VILE_REFERER = "https://vileembeds.pages.dev/"
INPROVISZON = "https://inproviszon.st"
_slug_cache: dict[int, str] = {}


QUALITY_TOKENS = {"hd", "fhd", "uhd", "sd", "4k", "1080p", "720p", "hq", "hevc", "raw"}
REGION_TOKENS = {"uk", "us", "usa", "ie", "ca", "au", "nz", "int", "intl", "eu"}
FILLER_TOKENS = {"tv", "channel", "network", "the", "live"}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _slugify(s: str) -> str:
    s = _strip_accents(s.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def slug_candidates(name: str) -> list[str]:
    """Generate slug candidates for a channel name, most-specific first.
    inproviszon uses a readable slug (e.g. 'Sky Sports F1 UK' -> 'sky-sports-f1')
    that drops quality/region/filler tokens. We generate the full slug plus
    variants with those tokens removed, then progressively strip trailing
    tokens, plus +/& spelling variants and accent folding."""
    name = htmllib.unescape(name or "")
    base_forms = [name]
    if "+" in name:
        base_forms += [name.replace("+", " plus "), name.replace("+", " ")]
    if "&" in name:
        base_forms += [name.replace("&", " and "), name.replace("&", " ")]
    cands: list[str] = []
    seen: set[str] = set()

    def add(c: str):
        if c and c not in seen:
            seen.add(c)
            cands.append(c)

    drop_sets = [
        set(),
        QUALITY_TOKENS,
        REGION_TOKENS,
        FILLER_TOKENS,
        QUALITY_TOKENS | REGION_TOKENS,
        QUALITY_TOKENS | REGION_TOKENS | FILLER_TOKENS,
    ]
    for bf in base_forms:
        bf = re.sub(r"\([^)]*\)", " ", bf)  # drop parenthetical
        toks = [t for t in _slugify(bf).split("-") if t]
        if not toks:
            continue
        for drop in drop_sets:
            kept = [t for t in toks if t not in drop]
            for i in range(len(kept), 0, -1):
                add("-".join(kept[:i]))
    # longest (most specific) first
    cands.sort(key=len, reverse=True)
    return cands


def _extract_channel_names(html: str) -> list[str]:
    """Pull plausible channel-name strings from the stream page (title, og:title,
    headings, card titles). The player slugifies one of these to hit inproviszon,
    so we build candidates from all of them."""
    names: list[str] = []
    pats = [
        r"<title>([^<]+)</title>",
        r'property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
        r"<h1[^>]*>(.*?)</h1>",
        r"<h2[^>]*>(.*?)</h2>",
        r'class=["\']card__title["\'][^>]*>([^<]+)<',
    ]
    for pat in pats:
        for m in re.findall(pat, html, re.I | re.S):
            t = htmllib.unescape(re.sub(r"<[^>]+>", " ", m))
            t = re.sub(r"(?i)\b(live\s*stream(?:ing)?|livestream|watch|online|free|schedule|daddylive|daddy\s*live)\b", " ", t)
            t = re.sub(r"(?i)channel\s*\d+", " ", t)
            t = re.sub(r"\s+", " ", t).strip(" -|\u00b7:")
            if t and len(t) >= 2 and not t.isdigit():
                names.append(t)
    return list(dict.fromkeys(names))


async def resolve_inproviszon(session, names: list[str], max_probes: int = 30):
    """Build inproviszon.st/<slug>.m3u8 from the channel name(s) and probe.
    Longest candidate returning a 200 mpegurl wins. inproviszon is
    Cloudflare-fronted; try plain browser headers first, vile referer on 403.
    Returns (slug, url, report)."""
    cand_list: list[str] = []
    seen: set[str] = set()
    for nm in names:
        for c in slug_candidates(nm):
            if c not in seen:
                seen.add(c)
                cand_list.append(c)
    cand_list.sort(key=len, reverse=True)
    header_variants = [
        {**BROWSER_HEADERS},
        {**BROWSER_HEADERS, "Referer": VILE_REFERER, "Origin": VILE_REFERER.rstrip("/")},
    ]
    report: list[dict] = []
    for cand in cand_list[:max_probes]:
        url = f"{INPROVISZON}/{cand}.m3u8"
        last = None
        for hdrs in header_variants:
            try:
                r = await session.get(url, headers=hdrs, timeout=10)
                last = r.status_code
                if r.status_code == 200 and "mpegurl" in (r.headers.get("content-type") or "").lower():
                    report.append({"slug": cand, "status": 200, "hit": True})
                    return cand, url, report
                if r.status_code != 403:
                    break
            except Exception as e:
                last = str(e)[:80]
                break
        report.append({"slug": cand, "status": last})
    return None, None, report


async def resolve_slug(session, name: str, max_probes: int = 10):
    """Return (winning_slug, report). Probes inproviszon.st/<cand>.m3u8 with the
    vileembeds referer; the longest candidate returning 200 wins."""
    hdrs = {**BROWSER_HEADERS, "Referer": VILE_REFERER, "Origin": VILE_REFERER.rstrip("/")}
    report = []
    winner = None
    for cand in slug_candidates(name)[:max_probes]:
        url = f"{INPROVISZON}/{cand}.m3u8"
        rec = {"slug": cand}
        try:
            r = await session.get(url, headers=hdrs, timeout=12)
            rec["status"] = r.status_code
            rec["ct"] = r.headers.get("content-type")
            if r.status_code == 200 and "mpegurl" in (r.headers.get("content-type") or "").lower():
                rec["hit"] = True
                report.append(rec)
                winner = cand
                break
        except Exception as e:
            rec["error"] = str(e)[:120]
        report.append(rec)
    return winner, report


async def _lookup_channel_name(session, num: int) -> str | None:
    domain, r = await fetch_first_live(session, "/24-7-channels.php")
    if not r:
        return None
    for n, nm in re.findall(
        r'href="/watch\.php\?id=(\d+)"[^>]*>\s*<div class="card__title">([^<]+)</div>',
        r.text,
    ):
        if int(n) == num:
            return nm.strip()
    return None


async def _scrape_all_channel_names(session) -> dict[int, list[str]]:
    """Scrape every dlhd listing page and return {channel_num: [name, ...]}.
    Tries: /24-7-channels.php, /, /schedule.php, /channels.php, /all-channels.php
    and individual stream pages as a last resort for unknown numbers."""
    out: dict[int, list[str]] = {}

    def merge(num: int, name: str):
        name = htmllib.unescape(name).strip()
        if name:
            out.setdefault(num, [])
            if name not in out[num]:
                out[num].append(name)

    CARD_PAT = re.compile(
        r'href="/(?:watch|stream[^"]*)\.php\?id=(\d+)"[^>]*>[^<]*<[^>]+class="[^"]*card[^"]*title[^"]*"[^>]*>([^<]+)<',
        re.I,
    )
    WATCH_PAT = re.compile(
        r'href="/watch\.php\?id=(\d+)"[^>]*>\s*<div class="card__title">([^<]+)</div>',
        re.I,
    )
    GENERIC_PAT = re.compile(
        r'(?:watch|stream)[^"]*\.php\?id=(\d+)[^>]*>[^<]*([A-Z][^<]{2,40})</(?:a|div|span|li|td)',
        re.I,
    )

    pages = ["/24-7-channels.php", "/", "/schedule.php", "/channels.php",
             "/all-channels.php", "/live-channels.php", "/sports.php"]
    for path in pages:
        try:
            domain, r = await fetch_first_live(session, path)
            if not r:
                continue
            for pat in (WATCH_PAT, CARD_PAT, GENERIC_PAT):
                for n, nm in pat.findall(r.text):
                    merge(int(n), nm)
        except Exception:
            continue

    return out


# ── inproviszon slug catalogue ──────────────────────────────────────────────
_inproviszon_slugs: list[str] = []          # populated by /fetchslugs
_inproviszon_slugs_fetched: bool = False

async def _fetch_inproviszon_slugs(session) -> list[str]:
    """Scrape inproviszon's own pages to discover every slug they carry.
    Tries: /, /channels, /channels.php, /playlist.m3u, /index.m3u8, /list
    Returns a deduplicated list of slug strings like 'sky-sports-f1'."""
    global _inproviszon_slugs, _inproviszon_slugs_fetched
    if _inproviszon_slugs_fetched:
        return _inproviszon_slugs

    base = INPROVISZON  # e.g. "https://inproviszon.st"
    found: set[str] = set()
    SLUG_RE = re.compile(r'([a-z0-9]+(?:-[a-z0-9]+)+)\.m3u8', re.I)
    HREF_RE = re.compile(r'href=["\']?/?([a-z0-9][a-z0-9\-]+)\.m3u8', re.I)
    PATH_RE = re.compile(r'/([a-z0-9][a-z0-9\-]+)\.m3u8', re.I)

    probe_paths = [
        "/", "/channels", "/channels.php", "/channel-list",
        "/list", "/playlist.m3u", "/playlist.m3u8", "/index.m3u",
        "/streams", "/live", "/all",
    ]

    for path in probe_paths:
        try:
            r = await session.get(
                f"{base}{path}",
                headers={"User-Agent": "Mozilla/5.0", "Referer": VILE_REFERER},
                timeout=10,
            )
            if r.status_code not in (200, 206):
                continue
            text = r.text
            for pat in (HREF_RE, PATH_RE, SLUG_RE):
                for m in pat.findall(text):
                    slug = m.strip("/")
                    if len(slug) > 3 and "-" in slug:
                        found.add(slug.lower())
        except Exception:
            continue

    _inproviszon_slugs = sorted(found)
    _inproviszon_slugs_fetched = bool(found)
    return _inproviszon_slugs


def _slug_similarity(name: str, slug: str) -> float:
    """Rough similarity between a channel name and a slug.
    Returns 0.0–1.0; >=0.5 is a reasonable match candidate."""
    # normalise name to slug form for comparison
    name_slug = _slugify(name.lower())
    # check direct containment
    if name_slug == slug:
        return 1.0
    if name_slug in slug or slug in name_slug:
        return 0.8
    # token overlap
    name_tokens = set(name_slug.split("-"))
    slug_tokens = set(slug.split("-"))
    shared = name_tokens & slug_tokens
    if not name_tokens or not slug_tokens:
        return 0.0
    return len(shared) / max(len(name_tokens), len(slug_tokens))


# ── source discovery (multi-CDN) ───────────────────────────────────────────
# Known CDN backends and their slug patterns.
# Format: (domain, url_template, note)
# url_template uses {slug} placeholder.
_KNOWN_CDNS: list[tuple[str, str, str]] = [
    ("inproviszon.st",   "https://inproviszon.st/{slug}.m3u8",          "Cloudflare; slug = channel-name"),
    # add more as discovered
]

# Domains we know are dead or irrelevant — skip them in new-CDN discovery
_DEAD_DOMAINS = {
    "phantemlis", "romponalis", "hamis", "kolis", "vomos", "fomis", "zalis",
    "google", "facebook", "twitter", "jquery", "bootstrap", "cdn.jsdelivr",
    "fonts.google", "cloudflare", "analytics",
}


async def _hunt_channel_sources(session, num: int) -> dict:
    """Deep JS analysis for channel `num`.
    1. Fetches the stream page.
    2. Follows every iframe / embedded player URL.
    3. Downloads all <script src=...> files from each embed.
    4. Scans raw HTML + JS for:
       - Hardcoded .m3u8 URLs
       - atob() base64 blobs that decode to .m3u8 URLs
       - Any new CDN domain + path pattern referencing .m3u8
    5. For each candidate URL, does a HEAD/GET probe and reports status.
    Returns a dict with keys: m3u8_urls, new_domains, js_patterns, probe_results.
    """
    IFRAME_RE  = re.compile(r'(?:src|href)=["\']([^"\' >]+)["\']', re.I)
    SCRIPT_RE  = re.compile(r'<script[^>]+src=["\']([^"\' >]+)["\']', re.I)
    M3U8_RE    = re.compile(r'https?://[^\s"\'\'<>]+\.m3u8[^\s"\'\'<>]*', re.I)
    ATOB_RE    = re.compile(r'atob\(["\']([A-Za-z0-9+/=]{20,})["\']\)')
    DOMAIN_RE  = re.compile(r'https?://([a-z0-9][a-z0-9.\-]+)/[^\s"\'\'<>]*\.m3u8', re.I)
    # JS variable assignment patterns like:  var url = "https://cdn.../channel.m3u8"
    JSVAR_RE   = re.compile(
        r'(?:url|src|stream|source|m3u8|hls|live)[^=]*=\s*["\']([^"\' ]+\.m3u8[^"\' ]*)["\']', re.I
    )

    found_m3u8: set[str]  = set()
    new_domains: set[str] = set()
    visited: set[str]     = set()

    def extract_m3u8(text: str):
        for url in M3U8_RE.findall(text):
            found_m3u8.add(url.strip())
        for url in JSVAR_RE.findall(text):
            if url.startswith("http"):
                found_m3u8.add(url.strip())
        for b64 in ATOB_RE.findall(text):
            try:
                decoded = base64.b64decode(b64 + "==").decode("utf-8", errors="ignore")
                for url in M3U8_RE.findall(decoded):
                    found_m3u8.add(url.strip())
                # try nested atob
                inner = re.findall(r'atob\(["\']([A-Za-z0-9+/=]{20,})["\']\)', decoded)
                for ib in inner:
                    try:
                        d2 = base64.b64decode(ib + "==").decode("utf-8", errors="ignore")
                        for url in M3U8_RE.findall(d2):
                            found_m3u8.add(url.strip())
                    except Exception:
                        pass
            except Exception:
                pass

    def track_domains(text: str):
        for domain in DOMAIN_RE.findall(text):
            domain = domain.lower().rstrip(".")
            if not any(dead in domain for dead in _DEAD_DOMAINS):
                new_domains.add(domain)

    async def fetch_and_scan(url: str, depth: int = 0):
        if url in visited or depth > 3:
            return
        visited.add(url)
        try:
            r = await session.get(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://dlhd.st/"},
                timeout=12,
            )
            if r.status_code != 200:
                return
            text = r.text
        except Exception:
            return

        extract_m3u8(text)
        track_domains(text)

        if depth < 2:
            # follow iframes
            for href in IFRAME_RE.findall(text):
                if any(x in href for x in ("php", "embed", "player", "stream", "live", "daddy")):
                    full = href if href.startswith("http") else ("https://" + href.lstrip("/"))
                    await fetch_and_scan(full, depth + 1)

            # download JS files from embeds (depth==1 means we’re inside an embed)
            if depth >= 1:
                for src in SCRIPT_RE.findall(text):
                    if src.startswith("//"):
                        src = "https:" + src
                    elif not src.startswith("http"):
                        base_url = "/".join(url.split("/")[:3])
                        src = base_url + "/" + src.lstrip("/")
                    if src not in visited:
                        await fetch_and_scan(src, depth + 1)

    # Start from stream page
    stream_url = f"https://dlhd.st/stream/stream-{num}.php"
    await fetch_and_scan(stream_url)

    # Probe every found m3u8 URL
    probe_results = []
    for url in sorted(found_m3u8):
        try:
            r = await session.get(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://dlhd.st/"},
                timeout=8,
            )
            probe_results.append({"url": url, "status": r.status_code,
                                   "working": r.status_code == 200})
        except Exception as e:
            probe_results.append({"url": url, "status": -1, "error": str(e)[:60]})

    working = [p["url"] for p in probe_results if p.get("working")]
    return {
        "stream_page": stream_url,
        "m3u8_found": sorted(found_m3u8),
        "new_domains": sorted(new_domains),
        "probe_results": probe_results,
        "working": working,
    }


@app.get("/sourcehunt/{num}")
async def sourcehunt(num: int):
    """Deep JS analysis for channel `num`.
    Fetches the stream page, follows iframes, downloads all JS files,
    extracts every .m3u8 URL (including base64/atob-encoded ones),
    probes each URL, and returns which ones are live.

    Use this for channels that miss on inproviszon to discover OTHER
    CDN backends — just like channel 60’s inproviszon URL was found
    via the browser network tab."""
    async with AsyncSession(impersonate="chrome120") as session:
        result = await _hunt_channel_sources(session, num)
    return result


@app.get("/sourcehunt_batch")
async def sourcehunt_batch(nums: str = "", concurrency: int = 3):
    """Run /sourcehunt on multiple channels at once.
    Pass ?nums=35,37,38,130,31,32,33,34 (comma-separated channel numbers).
    Returns only channels where at least one working m3u8 was found,
    and lists the new CDN domains discovered."""
    if not nums:
        return {"error": "pass ?nums=35,37,38,..."}

    num_list = [int(n.strip()) for n in nums.split(",") if n.strip().isdigit()]
    results = {}
    all_new_domains: set[str] = set()
    sem = asyncio.Semaphore(concurrency)

    async def hunt_one(n: int):
        async with sem:
            async with AsyncSession(impersonate="chrome120") as session:
                r = await _hunt_channel_sources(session, n)
                results[str(n)] = r
                all_new_domains.update(r.get("new_domains", []))

    await asyncio.gather(*[hunt_one(n) for n in num_list])

    hits = {k: v for k, v in results.items() if v.get("working")}
    return {
        "channels_scanned": len(num_list),
        "channels_with_working_source": len(hits),
        "all_new_domains_discovered": sorted(all_new_domains),
        "hits": hits,
        "all_results": results,
    }


@app.get("/fetchslugs")
async def fetchslugs():
    """Scrape inproviszon's own pages to get their full channel slug catalogue.
    Populates the in-memory slug list used by /diagnose."""
    global _inproviszon_slugs_fetched
    _inproviszon_slugs_fetched = False  # force re-fetch
    async with AsyncSession(impersonate="chrome120") as session:
        slugs = await _fetch_inproviszon_slugs(session)
    return {"slug_count": len(slugs), "slugs": slugs}


@app.get("/diagnose")
async def diagnose(min_score: float = 0.5):
    """Cross-reference the miss list against inproviszon's known slug catalogue.

    For every channel in the miss list, fuzzy-match its name against every
    inproviszon slug.  Returns two buckets:

      slug_mismatch  — channel IS on inproviszon, our slug generator just
                       produced the wrong slug. Includes the best-matching
                       inproviszon slug so you can hardcode the fix.

      not_on_inproviszon — zero slug match above min_score; channel is
                           genuinely absent from inproviszon's catalogue.

    Pass ?min_score=0.4 to widen the net or 0.7 to tighten it."""
    async with AsyncSession(impersonate="chrome120") as session:
        known_slugs = await _fetch_inproviszon_slugs(session)
        if not known_slugs:
            return {"error": "Could not fetch inproviszon slug catalogue — run /fetchslugs first or inproviszon index is unreachable"}

        # get current miss list
        all_names = await _scrape_all_channel_names(session)

    misses = [
        (num, names)
        for num, names in all_names.items()
        if num not in _slug_cache
    ]

    slug_mismatch = []
    not_on_inproviszon = []

    for num, names in misses:
        best_slug = None
        best_score = 0.0
        for name in names:
            for slug in known_slugs:
                score = _slug_similarity(name, slug)
                if score > best_score:
                    best_score = score
                    best_slug = slug
        if best_score >= min_score:
            slug_mismatch.append({
                "num": num,
                "names": names,
                "best_inproviszon_slug": best_slug,
                "score": round(best_score, 2),
            })
        else:
            not_on_inproviszon.append({"num": num, "names": names})

    slug_mismatch.sort(key=lambda x: -x["score"])
    return {
        "inproviszon_slug_count": len(known_slugs),
        "slug_mismatch": slug_mismatch,
        "not_on_inproviszon": not_on_inproviszon,
        "summary": {
            "slug_mismatch": len(slug_mismatch),
            "not_on_inproviszon": len(not_on_inproviszon),
        },
    }


@app.get("/fixmismatches")
async def fixmismatches(min_score: float = 0.6, dry_run: bool = False):
    """Automatically probe the best-matching inproviszon slug for every
    slug-mismatch channel and cache the ones that actually return 200.

    Pass ?dry_run=true to see what would be probed without changing the cache.
    Pass ?min_score=0.7 to only attempt high-confidence matches."""
    async with AsyncSession(impersonate="chrome120") as session:
        known_slugs = await _fetch_inproviszon_slugs(session)
        if not known_slugs:
            return {"error": "Could not fetch inproviszon slug catalogue"}
        all_names = await _scrape_all_channel_names(session)

        misses = [
            (num, names)
            for num, names in all_names.items()
            if num not in _slug_cache
        ]

        fixed = []
        still_miss = []

        sem = asyncio.Semaphore(5)

        async def try_fix(num, names):
            # find best slug candidate from known catalogue
            best_slug = None
            best_score = 0.0
            for name in names:
                for slug in known_slugs:
                    score = _slug_similarity(name, slug)
                    if score > best_score:
                        best_score = score
                        best_slug = slug
            if best_score < min_score or not best_slug:
                return

            async with sem:
                if dry_run:
                    fixed.append({"num": num, "names": names, "would_try": best_slug, "score": round(best_score, 2)})
                    return
                try:
                    url = f"{INPROVISZON}/{best_slug}.m3u8"
                    r = await session.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": VILE_REFERER}, timeout=8)
                    if r.status_code == 200:
                        _slug_cache[num] = best_slug
                        fixed.append({"num": num, "names": names, "slug": best_slug, "score": round(best_score, 2)})
                    else:
                        still_miss.append({"num": num, "names": names, "tried": best_slug, "status": r.status_code})
                except Exception as e:
                    still_miss.append({"num": num, "names": names, "error": str(e)[:80]})

        await asyncio.gather(*[try_fix(n, nms) for n, nms in misses])

    return {
        "dry_run": dry_run,
        "fixed": fixed,
        "still_miss": still_miss,
        "summary": {"fixed": len(fixed), "still_miss": len(still_miss)},
    }


@app.get("/buildcache")
async def buildcache(start: int = 1, end: int = 0, concurrency: int = 5):
    """Bulk-resolve ALL channels against inproviszon and populate the slug
    cache. Channels that resolve get served from inproviszon (working);
    channels that don't fall back to the phantemlis iframe path as before.

    Pass ?start=1&end=200 to scan a specific range.
    If end=0, only resolves channels whose names we find in the dlhd listing pages.
    Returns: hits (inproviszon works), misses, and already_cached counts."""
    results: dict = {"hits": {}, "misses": [], "errors": [], "already_cached": []}

    async with AsyncSession(impersonate="chrome120") as session:
        # Step 1 — build num->names map from listing pages
        all_names = await _scrape_all_channel_names(session)

        # Step 2 — if a range was given, also fetch stream page titles for unknowns
        if end > 0:
            unknown = [n for n in range(start, end + 1) if n not in all_names]
            # fetch stream pages concurrently in batches
            sem = asyncio.Semaphore(concurrency)
            async def fetch_stream_names(num: int):
                async with sem:
                    try:
                        domain, r = await fetch_first_live(session, f"/stream/stream-{num}.php")
                        if not r:
                            return
                        names = _extract_channel_names(r.text)
                        for nm in names:
                            all_names.setdefault(num, [])
                            if nm not in all_names[num]:
                                all_names[num].append(nm)
                    except Exception:
                        pass
            await asyncio.gather(*[fetch_stream_names(n) for n in unknown])

        results["channels_found"] = len(all_names)

        # Step 3 — resolve each channel against inproviszon (concurrently)
        sem2 = asyncio.Semaphore(concurrency)

        async def resolve_one(num: int, names: list[str]):
            if num in _slug_cache:
                results["already_cached"].append({"num": num, "slug": _slug_cache[num]})
                return
            async with sem2:
                try:
                    slug, url, _ = await resolve_inproviszon(session, names, max_probes=30)
                    if slug:
                        _slug_cache[num] = slug
                        results["hits"][str(num)] = {"slug": slug, "manifest": url, "names": names}
                    else:
                        results["misses"].append({"num": num, "names": names})
                except Exception as e:
                    results["errors"].append({"num": num, "error": str(e)[:120]})

        await asyncio.gather(*[resolve_one(n, nms) for n, nms in all_names.items()])

    results["summary"] = {
        "hits": len(results["hits"]),
        "misses": len(results["misses"]),
        "errors": len(results["errors"]),
        "already_cached": len(results["already_cached"]),
        "total_checked": len(all_names),
    }
    return results


@app.get("/findslug")
async def findslug(name: str = "", num: int = 0):
    """Diagnostic: resolve a channel name (or number) to its inproviszon slug by
    probing candidates. Pass ?name=Sky+Sports+F1+UK or ?num=60."""
    async with AsyncSession(impersonate="chrome120") as session:
        if not name and num:
            name = await _lookup_channel_name(session, num) or ""
        if not name:
            raise HTTPException(status_code=400, detail="pass ?name= or a resolvable ?num=")
        winner, report = await resolve_slug(session, name)
        return {
            "name": name,
            "candidates_tried": [r["slug"] for r in report],
            "resolved_slug": winner,
            "manifest": f"{INPROVISZON}/{winner}.m3u8" if winner else None,
            "report": report,
        }


# ── Deep chain crawler: find where the vileembeds slug is built ────────
def _grep_slugs(text: str) -> dict:
    return {
        "vileembeds": list(dict.fromkeys(
            re.findall(r"[a-z0-9-]+\.pages\.dev/embed/[A-Za-z0-9_.-]+", text)))[:20],
        "pages_dev": list(dict.fromkeys(
            re.findall(r"[a-z0-9-]+\.pages\.dev[^\s'\"\\<>]*", text)))[:20],
        "inproviszon": list(dict.fromkeys(
            re.findall(r"inproviszon\.st/[A-Za-z0-9_.-]+", text)))[:20],
        "embed_paths": list(dict.fromkeys(
            re.findall(r"/embed/([A-Za-z0-9_-]+)", text)))[:30],
        "m3u8": list(dict.fromkeys(
            re.findall(r"https?://[^\s'\"\\<>]+\.m3u8[^\s'\"\\<>]*", text)))[:20],
    }


def _abs_url(link: str, domain: str, page_url: str) -> str:
    if link.startswith("http"):
        return link
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("/"):
        return domain + link
    return page_url.rsplit("/", 1)[0] + "/" + link


@app.get("/chase/{num}")
async def chase(num: int, max_depth: int = 2, max_fetches: int = 30):
    """Crawl the dlhd stream page and everything it loads (iframes + scripts),
    up to max_depth levels, grepping every document for vileembeds/inproviszon/
    /embed/ slugs and decoded base64. Reveals how the real slug is built."""
    out = {"num": num, "steps": [], "HITS": []}
    async with AsyncSession(impersonate="chrome120") as session:
        domain, r1 = await fetch_first_live(session, f"/stream/stream-{num}.php")
        if not r1:
            raise HTTPException(status_code=502, detail="stream page failed on all domains")
        out["domain"] = domain
        page_url = f"{domain}/stream/stream-{num}.php"
        visited = {page_url}
        # queue items: (kind, url, text, depth)
        queue = [("stream_page", page_url, r1.text, 0)]
        fetches = 0
        while queue and fetches < max_fetches:
            kind, url, text, depth = queue.pop(0)
            grep = _grep_slugs(text)
            scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', text, re.I)
            iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', text, re.I)
            b64s = re.findall(r"atob\(['\"]([A-Za-z0-9+/=]{16,})['\"]\)", text)
            decoded = []
            for b in b64s[:12]:
                try:
                    decoded.append(base64.b64decode(b).decode("utf-8", "ignore")[:300])
                except Exception:
                    pass
            step = {
                "where": kind, "url": url, "depth": depth,
                "bytes": len(text), "grep": grep,
                "scripts": scripts[:25], "iframes": iframes[:10],
                "atob_decoded": decoded,
            }
            out["steps"].append(step)
            if grep["vileembeds"] or grep["inproviszon"] or grep["pages_dev"]:
                out["HITS"].append({
                    "where": kind, "url": url,
                    "vileembeds": grep["vileembeds"],
                    "pages_dev": grep["pages_dev"],
                    "inproviszon": grep["inproviszon"],
                })
            if depth < max_depth:
                for link in iframes + scripts:
                    au = _abs_url(link, domain, url)
                    if au in visited:
                        continue
                    visited.add(au)
                    if fetches >= max_fetches:
                        break
                    fetches += 1
                    rr = await _fetch(session, au, referer=url)
                    if rr is None:
                        out["steps"].append({"where": "fetch_fail", "url": au, "depth": depth + 1})
                        continue
                    ck = "iframe" if link in iframes else "script"
                    queue.append((ck, au, rr.text, depth + 1))
    return out


async def _fetch(session, url: str, referer: str | None = None):
    h = {**BROWSER_HEADERS}
    if referer:
        h["Referer"] = referer
    try:
        return await session.get(url, headers=h, timeout=15)
    except Exception:
        return None


# ── Existing endpoints (unchanged) ───────────────────────────────────────────

@app.get("/raw/{channel_num}", response_class=PlainTextResponse)
async def raw_page(channel_num: int):
    async with AsyncSession(impersonate="chrome120") as session:
        domain, r1 = await fetch_first_live(session, f"/stream/stream-{channel_num}.php")
        if not r1:
            raise HTTPException(status_code=502, detail="All domains failed — check /probe")

        out = f"=== STREAM PAGE: {domain}/stream/stream-{channel_num}.php ===\n=== STATUS: {r1.status_code} ===\n\n{r1.text}\n"

        iframe_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', r1.text, re.IGNORECASE)
        if iframe_match:
            embed_url = iframe_match.group(1)
            if embed_url.startswith("//"):
                embed_url = "https:" + embed_url
            elif embed_url.startswith("/"):
                embed_url = domain + embed_url

            try:
                r2 = await session.get(
                    embed_url,
                    headers={**BROWSER_HEADERS, "Referer": f"{domain}/"},
                    timeout=12,
                )
                out += f"\n\n=== EMBED PAGE: {embed_url} ===\n=== STATUS: {r2.status_code} ===\n\n{r2.text}"
            except Exception as e:
                out += f"\n\n=== EMBED PAGE FETCH FAILED: {e} ==="
        else:
            out += "\n\n=== NO IFRAME FOUND IN STREAM PAGE ==="

        return out


@app.get("/channels")
async def channels():
    async with AsyncSession(impersonate="chrome120") as session:
        domain, r = await fetch_first_live(session, "/24-7-channels.php")
        if not r:
            raise HTTPException(status_code=502, detail="All domains failed for channels list")

        found = re.findall(
            r'href="/watch\.php\?id=(\d+)"[^>]*>\s*<div class="card__title">([^<]+)</div>',
            r.text,
        )
        channel_list = [
            {"num": int(n), "name": name.strip()}
            for n, name in found if name.strip()
        ]
        return {"domain": domain, "count": len(channel_list), "channels": channel_list}


@app.get("/schedule")
async def schedule():
    async with AsyncSession(impersonate="chrome120") as session:
        domain, r = await fetch_first_live(session, "/")
        if not r:
            raise HTTPException(status_code=502, detail="All domains failed for schedule")

        html = r.text
        events = []

        header_re = re.compile(
            r'<div[^>]+class="schedule__eventHeader"[^>]+data-title="([^"]+)"[^>]*>',
            re.IGNORECASE,
        )
        channels_re = re.compile(
            r'<div[^>]+class="schedule__channels"[^>]*>(.*?)</div>',
            re.DOTALL | re.IGNORECASE,
        )
        link_re = re.compile(
            r'href="/watch\.php\?id=(\d+)"[^>]*title="([^"]*)"',
            re.IGNORECASE,
        )
        cat_re = re.compile(
            r'<div[^>]+class="schedule__catHeader"[^>]*>.*?<div[^>]+class="card__meta"[^>]*>([^<]+)</div>',
            re.DOTALL | re.IGNORECASE,
        )

        cat_positions = []
        for m in cat_re.finditer(html):
            cat_positions.append((m.start(), m.group(1).strip()))

        def get_category_at(pos):
            cat = ""
            for cpos, cname in cat_positions:
                if cpos <= pos:
                    cat = cname
                else:
                    break
            return cat

        header_matches = list(header_re.finditer(html))

        for i, hm in enumerate(header_matches):
            raw_title = hm.group(1).strip()

            time_m = re.search(r'(\d{1,2}:\d{2})\s*$', raw_title)
            if time_m:
                time_str = time_m.group(1)
                title = raw_title[:time_m.start()].strip().rstrip(':').strip()
            else:
                time_str = ""
                title = raw_title

            title_clean = re.sub(r'[\U0001F1E0-\U0001F1FF\U0001F300-\U0001F9FF]+', '', title).strip()

            search_start = hm.end()
            search_end = header_matches[i + 1].start() if i + 1 < len(header_matches) else len(html)
            chunk = html[search_start:search_end]

            ch_match = channels_re.search(chunk)
            channels_list = []
            if ch_match:
                ch_html = ch_match.group(1)
                seen_ids = set()
                for lm in link_re.finditer(ch_html):
                    ch_id = int(lm.group(1))
                    ch_name = lm.group(2).strip()
                    if ch_id not in seen_ids:
                        seen_ids.add(ch_id)
                        channels_list.append({"id": ch_id, "name": ch_name})

            category = get_category_at(hm.start())

            if title_clean:
                events.append({
                    "title": title_clean.lower(),
                    "time": time_str,
                    "category": category,
                    "channels": channels_list,
                })

        return {"domain": domain, "count": len(events), "events": events}


@app.get("/raw-schedule", response_class=PlainTextResponse)
async def raw_schedule():
    async with AsyncSession(impersonate="chrome120") as session:
        results = []
        for domain in DLHD_DOMAINS:
            url = f"{domain}/"
            try:
                r = await session.get(
                    url,
                    headers={**BROWSER_HEADERS, "Referer": f"{domain}/"},
                    timeout=12,
                )
                results.append(f"=== {url} STATUS={r.status_code} BYTES={len(r.text)} ===\n{r.text[:3000]}\n")
                if r.status_code == 200 and len(r.text) > 500:
                    break
            except Exception as e:
                results.append(f"=== {url} ERROR: {e} ===\n")
        return "\n".join(results)