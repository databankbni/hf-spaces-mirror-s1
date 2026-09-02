#!/usr/bin/env python3
"""Shared web-data routes, mountable on any of our x402 FastAPI Spaces.

Why this exists: 30 days of agentic.market data (53,127 endpoints, 336,081 paid
calls) puts search + web-data at 59% of all x402 traffic at ~45 calls per endpoint,
while security/audit is the worst-served category on the network — 4,614 endpoints
splitting 8,800 calls, ~1.9 each. Our own on-chain history agrees: 331 settle events,
every one of them at $0.005 or $0.01, none at the premium security prices.

The catch is distribution: reaching the Coinbase CDP facilitator, which is what populates
the 24,827-entry CDP Bazaar and, downstream, agentic.market and 402index. So the web-data
routes live here, in one module, and get mounted on whichever Space can reach buyers.
(Corrected 2026-07-29: this used to say skill-audit settles through Dexter and is
invisible. It does not — `/` reports the CDP facilitator on BOTH Spaces. Re-verify from
the live `payment.facilitator` field before repeating any claim about which rail a Space
is on; the consequence of the stale version was nearly moving a Space OFF CDP.)

Mount with:
    from webdata_routes import build_router, route_specs
    app.include_router(build_router(), prefix="/web")
    routes.update(route_specs(prefix="/web", price_cheap="$0.005", ...))

Every outbound fetch goes through _safe_get/_fetch_text, which refuse loopback,
private, link-local and reserved targets (including cloud metadata at 169.254.169.254)
and re-validate on every redirect hop.
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class ReadRequest(BaseModel):
    url: str
    include_links: Optional[bool] = True
    max_size: Optional[int] = 2_000_000


class SearchRequest(BaseModel):
    query: str
    max_results: Optional[int] = 10


class CrawlRequest(BaseModel):
    url: str
    max_pages: Optional[int] = 5
    include_links: Optional[bool] = True


class SitemapRequest(BaseModel):
    url: str
    max_urls: Optional[int] = 500


class RssRequest(BaseModel):
    url: str
    max_items: Optional[int] = 50


def _host_is_blocked(host: str) -> bool:
    """True if `host` (name or literal) resolves to any non-public IP."""
    import ipaddress, socket
    host = host.strip("[]")  # strip IPv6 literal brackets
    try:  # already a literal?
        ip = ipaddress.ip_address(host)
        return not ip.is_global
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return True  # unresolvable → refuse
    for info in infos:
        ip_str = info[4][0].split("%")[0]  # drop scope id
        try:
            if not ipaddress.ip_address(ip_str).is_global:
                return True
        except ValueError:
            return True
    return False


def _validate_public_url(url: str):
    """Raise HTTPException(400) unless url is http(s) with a public host."""
    from urllib.parse import urlparse
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise HTTPException(400, "valid http/https URL required")
    if _host_is_blocked(p.hostname):
        raise HTTPException(400, "URL host is not a public address (private/loopback/link-local blocked)")


async def _safe_get(client, url: str, *, ua: str, max_redirects: int = 5):
    """GET with manual, SSRF-validated redirect following (each hop re-checked)."""
    _validate_public_url(url)
    current = url
    for _ in range(max_redirects + 1):
        resp = await client.get(current, headers={"User-Agent": ua})
        if resp.is_redirect and resp.headers.get("location"):
            from urllib.parse import urljoin
            current = urljoin(current, resp.headers["location"])
            _validate_public_url(current)  # block redirect-to-internal
            continue
        return resp
    raise HTTPException(400, "too many redirects")


async def _fetch_text(url: str, max_size: int, timeout: float = 20.0, ua: str = "Mozilla/5.0 (compatible; clean-read/1.0)"):
    """Fetch a URL and return its decoded body, truncated to max_size (SSRF-guarded)."""
    import httpx
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
        resp = await _safe_get(client, url, ua=ua)
        resp.raise_for_status()
    html = resp.text
    return (html[:max_size] if len(html) > max_size else html), str(resp.url)


def _to_markdown(html: str, include_links: bool):
    """trafilatura extraction shared by /read and /read/batch. Returns (markdown, title)."""
    import trafilatura
    markdown = trafilatura.extract(
        html, output_format="markdown",
        include_links=include_links, include_tables=True, favor_recall=True,
    )
    title = None
    try:
        meta = trafilatura.extract_metadata(html)
        if meta:
            title = meta.title
    except Exception:
        pass
    return markdown, title


@router.post("/read")
async def read_url(req: ReadRequest):
    url = req.url
    if not url or not url.startswith(("http://", "https://")):
        raise HTTPException(400, "valid http/https URL required")

    import httpx
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=20.0) as client:
            resp = await _safe_get(client, url, ua="Mozilla/5.0 (compatible; clean-read/1.0)")
            resp.raise_for_status()
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"upstream returned {e.response.status_code}")
    except Exception as e:
        raise HTTPException(502, f"fetch failed: {type(e).__name__}: {e}")

    html = resp.text
    if len(html) > req.max_size:
        html = html[: req.max_size]

    try:
        import trafilatura
    except ImportError:
        raise HTTPException(503, "extraction engine unavailable")

    markdown = trafilatura.extract(
        html, output_format="markdown",
        include_links=bool(req.include_links), include_tables=True, favor_recall=True,
    )
    if not markdown:
        raise HTTPException(422, "could not extract main content from this page")

    title = None
    try:
        meta = trafilatura.extract_metadata(html)
        if meta:
            title = meta.title
    except Exception:
        pass

    return {
        "url": str(resp.url),
        "title": title,
        "markdown": markdown,
        "word_count": len(markdown.split()),
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }


_SEARCH_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _unwrap_ddg(href: str) -> str:
    """DDG html wraps results as //duckduckgo.com/l/?uddg=<urlencoded target>."""
    from urllib.parse import urlparse, parse_qs, unquote
    if "uddg=" in href:
        q = parse_qs(urlparse(href if href.startswith("http") else "https:" + href).query)
        if q.get("uddg"):
            return unquote(q["uddg"][0])
    return href


def _parse_ddg(html: str, limit: int):
    from lxml import html as lh
    doc = lh.fromstring(html)
    out = []
    # Anchor-first: DDG nests several `result*`-classed divs per hit, so selecting
    # containers double-counts. One anchor == one hit; snippet lives in its ancestor.
    seen = set()
    for a in doc.xpath("//a[contains(@class,'result__a')]"):
        url = _unwrap_ddg(a.get("href") or "")
        if not url.startswith("http") or url in seen:
            continue
        if "duckduckgo.com/y.js" in url or "ad_provider" in url:  # sponsored
            continue
        seen.add(url)
        snip = a.xpath("ancestor::div[contains(@class,'result')][1]"
                       "//*[contains(@class,'result__snippet')]")
        out.append({"rank": len(out) + 1,
                    "title": " ".join(a.text_content().split()),
                    "url": url,
                    "snippet": " ".join(snip[0].text_content().split()) if snip else None})
        if len(out) >= limit:
            break
    return out


def _parse_ddg_lite(html: str, limit: int):
    """lite.duckduckgo.com/lite — table layout: a.result-link + td.result-snippet."""
    from lxml import html as lh
    doc = lh.fromstring(html)
    out, seen = [], set()
    for a in doc.xpath("//a[contains(@class,'result-link')]"):
        url = _unwrap_ddg(a.get("href") or "")
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        snip = a.xpath("ancestor::tr[1]/following-sibling::tr[1]//td[contains(@class,'result-snippet')]")
        out.append({"rank": len(out) + 1,
                    "title": " ".join(a.text_content().split()),
                    "url": url,
                    "snippet": " ".join(snip[0].text_content().split()) if snip else None})
        if len(out) >= limit:
            break
    return out


def _parse_wiby(body: str, limit: int):
    """wiby.me/json — a real JSON API: [{URL, Title, Snippet}]. Small index, but it is
    structured and answers reliably from a datacenter IP."""
    import json as _json
    try:
        data = _json.loads(body)
    except Exception:
        return []
    out = []
    for row in data if isinstance(data, list) else []:
        url = row.get("URL") or ""
        if not url.startswith("http"):
            url = "https://" + url.lstrip("/")
        out.append({"rank": len(out) + 1,
                    "title": " ".join((row.get("Title") or "").split()),
                    "url": url,
                    "snippet": " ".join((row.get("Snippet") or "").split()) or None})
        if len(out) >= limit:
            break
    return out


def _generic_parser(*self_hosts):
    """Heuristic result extractor for a server-rendered engine whose markup we cannot
    inspect (these hosts answer differently from a datacenter IP than from a desktop, so
    there is no way to develop a precise selector against them offline).

    Takes every outbound link with link text, drops the engine's own chrome and the usual
    social/footer destinations, and dedups by URL. `/web/selftest` reports how many results
    each engine yields, so this stays verifiable in production without paying.
    """
    JUNK = ("twitter.com", "x.com", "facebook.com", "github.com/marginalia",
            "wikipedia.org/wiki/Main_Page", "creativecommons.org", "mastodon",
            "patreon.com", "ko-fi.com", "reddit.com/r/", "discord.gg", "matrix.to")

    def parse(html: str, limit: int):
        from lxml import html as lh
        from urllib.parse import urlparse
        doc = lh.fromstring(html)
        out, seen = [], set()
        for a in doc.xpath("//a[@href]"):
            url = (a.get("href") or "").strip()
            if not url.startswith("http"):
                continue
            host = (urlparse(url).hostname or "").lower()
            if any(host == h or host.endswith("." + h) for h in self_hosts):
                continue
            if any(j in url for j in JUNK):
                continue
            title = " ".join(a.text_content().split())
            if len(title) < 12 or url in seen:  # nav/chrome links are short
                continue
            seen.add(url)
            # Snippet: the nearest following text block that is not another link.
            snippet = None
            for sib in a.xpath("following::p[1] | following::div[not(.//a)][1]"):
                t = " ".join(sib.text_content().split())
                if len(t) > 40:
                    snippet = t[:300]
                    break
            out.append({"rank": len(out) + 1, "title": title[:200], "url": url,
                        "snippet": snippet})
            if len(out) >= limit:
                break
        return out

    return parse


def _parse_mojeek(html: str, limit: int):
    from lxml import html as lh
    doc = lh.fromstring(html)
    out = []
    for li in doc.xpath("//ul[contains(@class,'results-standard')]/li"):
        a = li.xpath(".//a[contains(@class,'title')] | .//h2/a")
        if not a:
            continue
        url = a[0].get("href") or ""
        if not url.startswith("http"):
            continue
        p = li.xpath(".//p[@class='s']")
        out.append({"rank": len(out) + 1,
                    "title": " ".join(a[0].text_content().split()),
                    "url": url,
                    "snippet": " ".join(p[0].text_content().split()) if p else None})
        if len(out) >= limit:
            break
    return out


# Backend order is measured, not assumed. From this Space's datacenter IP,
# html.duckduckgo.com is INTERMITTENT (two probes connect-timed-out at 15s, a third
# returned 30KB), mojeek/ecosia/searx-instances/yep/qwant-api all 403 or 429, and
# lite.qwant.com serves a JS shell with zero anchors. Marginalia and wiby answer
# consistently, so they are the fallbacks that actually catch a DDG outage.
SEARCH_ENGINES = [
    ("duckduckgo", "https://html.duckduckgo.com/html/?q={q}", _parse_ddg),
    ("duckduckgo-lite", "https://lite.duckduckgo.com/lite/?q={q}", _parse_ddg_lite),
    ("marginalia", "https://old-search.marginalia.nu/search?query={q}",
     _generic_parser("marginalia.nu", "old-search.marginalia.nu", "search.marginalia.nu")),
    ("mojeek", "https://www.mojeek.com/search?q={q}", _parse_mojeek),
    ("wiby", "https://wiby.me/json/?q={q}", _parse_wiby),
]


async def _run_search(query: str, limit: int):
    """Try each backend in order; return (name, results, errors)."""
    from urllib.parse import quote_plus
    errors = {}
    for name, tmpl, parse in SEARCH_ENGINES:
        try:
            body, _ = await _fetch_text(tmpl.format(q=quote_plus(query)), 3_000_000,
                                        timeout=20.0, ua=_SEARCH_UA)
            results = parse(body, limit)
            if results:
                return name, results, errors
            errors[name] = "no results parsed"
        except Exception as e:
            errors[name] = f"{type(e).__name__}: {e}"
    return None, [], errors


@router.post("/search")
async def web_search(req: SearchRequest):
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(400, "query is required")
    limit = max(1, min(int(req.max_results or 10), 25))
    name, results, errors = await _run_search(query, limit)
    if not results:
        # 502 so the payment middleware never settles a call that returned nothing.
        raise HTTPException(502, f"all search backends failed or returned nothing: {errors}")
    return {"query": query, "engine": name, "count": len(results), "results": results,
            "fetched_at": datetime.utcnow().isoformat() + "Z"}


# GET/POST/HEAD: this is a free diagnostic and the crawler fleet POSTs it. Registered
# GET-only it answered 405, which tells a prober the path is not there at all. Its
# full path is also in mcp_http.FREE_PATHS so tokenguard's blanket POST sweep cannot
# turn a diagnostic into a paid route.
@router.api_route("/selftest", methods=["GET", "POST", "HEAD"])
async def search_selftest():
    """FREE. Per-backend reachability and parser yield for a fixed query.

    Paid routes cannot be exercised without paying, so without this there is no way to
    tell a backend that is unreachable from one whose parser silently returns nothing —
    and these engines answer differently from a datacenter IP than from a desktop, so it
    cannot be checked offline either. Returns counts and timings only, never a result,
    so it gives away nothing that /search is paid for.
    """
    import time
    from urllib.parse import quote_plus

    out = {}
    for name, tmpl, parse in SEARCH_ENGINES:
        t0 = time.monotonic()
        try:
            body, _ = await _fetch_text(tmpl.format(q=quote_plus("open source license")),
                                        3_000_000, timeout=20.0, ua=_SEARCH_UA)
            n = len(parse(body, 10))
            out[name] = {"ok": n > 0, "bytes": len(body), "parsed": n,
                         "ms": int((time.monotonic() - t0) * 1000)}
        except Exception as e:
            out[name] = {"ok": False, "error": f"{type(e).__name__}",
                         "ms": int((time.monotonic() - t0) * 1000)}
    return {"backends": out, "usable": sum(1 for v in out.values() if v.get("ok")),
            "checked_at": datetime.utcnow().isoformat() + "Z"}


@router.post("/crawl")
async def crawl_site(req: CrawlRequest):
    start = (req.url or "").strip()
    if not start.startswith(("http://", "https://")):
        raise HTTPException(400, "valid http/https URL required")
    max_pages = max(1, min(int(req.max_pages or 5), 10))

    from urllib.parse import urljoin, urldefrag, urlparse
    from lxml import html as lh

    origin_host = urlparse(start).hostname or ""
    seen = {urldefrag(start)[0]}
    queue = [(urldefrag(start)[0], 0)]
    pages, failures = [], []

    while queue and len(pages) < max_pages:
        current, depth = queue.pop(0)
        try:
            raw, final = await _fetch_text(current, 2_000_000)
        except Exception as e:
            failures.append({"url": current, "error": f"{type(e).__name__}: {e}"})
            continue

        markdown, title = _to_markdown(raw, bool(req.include_links))
        if markdown:
            pages.append({"url": final, "title": title, "markdown": markdown,
                          "word_count": len(markdown.split()), "depth": depth})
        else:
            failures.append({"url": final, "error": "could not extract main content"})

        if len(pages) + len(queue) >= max_pages:
            continue
        try:  # enqueue same-domain children
            doc = lh.fromstring(raw)
            for a in doc.xpath("//a[@href]"):
                link = urldefrag(urljoin(final, a.get("href")))[0]
                if not link.startswith(("http://", "https://")) or link in seen:
                    continue
                if (urlparse(link).hostname or "") != origin_host:
                    continue
                seen.add(link)
                queue.append((link, depth + 1))
                if len(seen) > max_pages * 20:
                    break
        except Exception:
            pass

    if not pages:
        raise HTTPException(502, f"no page could be crawled from {start}")
    return {"start_url": start, "pages_fetched": len(pages), "ok": len(pages),
            "failed": failures[:10], "pages": pages,
            "fetched_at": datetime.utcnow().isoformat() + "Z"}


# GET/POST/HEAD: this is a free diagnostic and the crawler fleet POSTs it. Registered
# GET-only it answered 405, which tells a prober the path is not there at all. Its
# full path is also in mcp_http.FREE_PATHS so tokenguard's blanket POST sweep cannot
# turn a diagnostic into a paid route.
@router.api_route("/sitemap/selftest", methods=["GET", "POST", "HEAD"])
async def sitemap_selftest():
    """FREE diagnostic: can this host actually read sitemaps from the public internet?

    /sitemap is behind the paywall, so we cannot exercise it ourselves without paying —
    which is exactly how a regression stayed invisible: Cloudflare-fronted origins were
    answering our datacenter IP with a refusal, and the route reported that as "this site
    has no sitemap". Local testing cannot reproduce it because the block is IP-based.

    Deliberately parameterless: it probes a fixed list of well-known public sites and
    returns counts and status only, never URLs. That keeps it useless as an open fetch
    proxy while still revealing datacenter-IP reachability. GET, so the POST-only paywall
    sweep at the bottom of main.py leaves it free.
    """
    import asyncio

    probes = {
        "no-cdn": "https://www.djangoproject.com",     # known-good control
        "cloudflare": "https://www.cloudflare.com",    # the origin class that regressed
        "no-sitemap": "https://example.com",           # must stay a truthful 404
    }

    async def one(site):
        # Hard per-probe ceiling: site_map's own timeouts (15s robots + 20s per sitemap,
        # times an index expansion) can add up past the hosting proxy's limit, and a
        # diagnostic that times out is worse than none. Run all three concurrently.
        try:
            # Measured 1.7-6s per probe; 25s is headroom for a slow origin, not a budget.
            r = await asyncio.wait_for(site_map(SitemapRequest(url=site, max_urls=5)), 25)
            return {"ok": True, "count": r["count"], "sitemaps": len(r["sitemaps"])}
        except asyncio.TimeoutError:
            return {"ok": False, "error": "probe exceeded 25s"}
        except HTTPException as e:
            detail = e.detail if isinstance(e.detail, dict) else {"error": str(e.detail)[:200]}
            return {"ok": False, "status": e.status_code,
                    "blocked": detail.get("blocked"), "error": detail.get("error")}
        except Exception as e:  # pragma: no cover
            return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}

    results = await asyncio.gather(*(one(s) for s in probes.values()))
    out = dict(zip(probes.keys(), results))
    healthy = out.get("no-cdn", {}).get("ok") and out.get("cloudflare", {}).get("ok")
    return {"healthy": bool(healthy), "probes": out,
            "checked_at": datetime.utcnow().isoformat() + "Z"}


@router.post("/sitemap")
async def site_map(req: SitemapRequest):
    raw_url = (req.url or "").strip()
    if not raw_url:
        raise HTTPException(400, "url is required")
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url
    max_urls = max(1, min(int(req.max_urls or 500), 2000))

    from urllib.parse import urlparse
    from lxml import etree
    p = urlparse(raw_url)
    site = f"{p.scheme}://{p.netloc}"

    # Cloudflare-fronted origins (python.org, cloudflare.com) 403 the default
    # "compatible; clean-read/1.0" UA from a datacenter IP, which used to surface as a
    # misleading "no sitemap found" 404 — the buyer paid and was told the site has no
    # sitemap when really we were blocked. Ask as a browser; sitemaps are public.
    SITEMAP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

    # 1. robots.txt Sitemap: lines, then the conventional locations.
    candidates = []
    blocked: list = []

    async def _get(url: str, cap: int, timeout: float):
        """Fetch, recording upstream refusals so they can be reported rather than
        silently collapsing into 'no sitemap'."""
        try:
            return await _fetch_text(url, cap, timeout=timeout, ua=SITEMAP_UA)
        except Exception as ex:
            status = getattr(getattr(ex, "response", None), "status_code", None)
            if status in (401, 403, 405, 406, 429) or status is None:
                blocked.append({"url": url, "status": status,
                                "error": type(ex).__name__})
            raise

    try:
        robots, _ = await _get(site + "/robots.txt", 500_000, 15.0)
        for line in robots.splitlines():
            if line.lower().startswith("sitemap:"):
                loc = line.split(":", 1)[1].strip()
                if loc.startswith("http") and loc not in candidates:
                    candidates.append(loc)
    except Exception:
        pass
    for guess in (site + "/sitemap.xml", site + "/sitemap_index.xml"):
        if guess not in candidates:
            candidates.append(guess)

    urls, used, index_expansions = [], [], 0

    async def load(loc: str, depth: int = 0):
        nonlocal index_expansions
        if len(urls) >= max_urls or depth > 2:
            return
        try:
            body, final = await _get(loc, 5_000_000, 20.0)
        except Exception:
            return
        try:
            root = etree.fromstring(body.encode("utf-8", "replace"),
                                    etree.XMLParser(recover=True, resolve_entities=False))
        except Exception:
            return
        if root is None:
            return
        used.append(final)
        tag = etree.QName(root).localname if root.tag is not etree.Comment else ""

        # Match on local names instead of a hardcoded namespace URI. Plenty of real
        # sitemaps declare no namespace, or the http vs https form of the schema URL;
        # a fixed `{sitemaps.org/schemas/sitemap/0.9}` prefix silently yields 0 URLs on
        # those, i.e. "this site has no sitemap" for a site that plainly does. Same
        # failure mode already burned us in the OFAC XML parser.
        def _find(el, name):
            return [e for e in el.iter() if isinstance(e.tag, str)
                    and etree.QName(e).localname == name]

        def _child_text(el, name):
            for e in el:
                if isinstance(e.tag, str) and etree.QName(e).localname == name and e.text:
                    return e.text.strip()
            return None

        if tag == "sitemapindex":
            children = [t for t in (_child_text(e, "loc") for e in _find(root, "sitemap")) if t]
            for child in children[:20]:
                index_expansions += 1
                await load(child, depth + 1)
            return
        for u in _find(root, "url"):
            loc_text = _child_text(u, "loc")
            if loc_text:
                urls.append({"loc": loc_text, "lastmod": _child_text(u, "lastmod")})
                if len(urls) >= max_urls:
                    return

    for c in candidates:
        await load(c)
        if len(urls) >= max_urls:
            break

    if not urls:
        # Tell the buyer which of the two it is. 404 means "this site has no sitemap";
        # 502 means "the origin refused us" — a paid call must not report the second
        # as the first.
        if blocked:
            raise HTTPException(502, {
                "error": f"origin refused our requests for {site}; no sitemap could be read",
                "blocked": blocked[:6],
                "hint": "the site is likely behind a bot filter that rejects datacenter IPs",
            })
        raise HTTPException(404, f"no sitemap URLs found for {site} (tried {candidates})")
    return {"site": site, "sitemaps": used, "sitemap_index_expansions": index_expansions,
            "count": len(urls), "urls": urls,
            "fetched_at": datetime.utcnow().isoformat() + "Z"}


@router.post("/rss")
async def parse_feed(req: RssRequest):
    raw_url = (req.url or "").strip()
    if not raw_url:
        raise HTTPException(400, "url is required")
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url
    max_items = max(1, min(int(req.max_items or 50), 200))

    from lxml import etree, html as lh
    from urllib.parse import urljoin

    body, final = await _fetch_text(raw_url, 5_000_000, timeout=20.0)

    def as_xml(text: str):
        try:
            root = etree.fromstring(text.encode("utf-8", "replace"),
                                    etree.XMLParser(recover=True, resolve_entities=False))
        except Exception:
            return None
        if root is None:
            return None
        name = etree.QName(root).localname.lower() if isinstance(root.tag, str) else ""
        return root if name in ("rss", "feed", "rdf") else None

    root = as_xml(body)
    if root is None:  # looked like a site page → auto-discover its feed link
        try:
            doc = lh.fromstring(body)
            links = doc.xpath("//link[@type='application/rss+xml' or @type='application/atom+xml']")
            hrefs = [urljoin(final, l.get("href")) for l in links if l.get("href")]
        except Exception:
            hrefs = []
        for h in hrefs[:3]:
            try:
                body2, final2 = await _fetch_text(h, 5_000_000, timeout=20.0)
            except Exception:
                continue
            root = as_xml(body2)
            if root is not None:
                final = final2
                break
    if root is None:
        raise HTTPException(422, "not an RSS/Atom feed and no feed link could be discovered")

    ATOM = "http://www.w3.org/2005/Atom"

    def txt(el):
        return " ".join(el.text_content().split()) if hasattr(el, "text_content") else (
            " ".join(el.text.split()) if el is not None and el.text else None)

    kind = etree.QName(root).localname.lower()
    items, feed_title = [], None
    if kind == "feed":  # Atom
        t = root.find(f"{{{ATOM}}}title")
        feed_title = txt(t)
        for e in root.findall(f"{{{ATOM}}}entry")[:max_items]:
            link_el = e.find(f"{{{ATOM}}}link")
            summary = e.find(f"{{{ATOM}}}summary")
            if summary is None:
                summary = e.find(f"{{{ATOM}}}content")
            items.append({
                "title": txt(e.find(f"{{{ATOM}}}title")),
                "link": link_el.get("href") if link_el is not None else None,
                "published": txt(e.find(f"{{{ATOM}}}updated")) or txt(e.find(f"{{{ATOM}}}published")),
                "summary": (txt(summary) or "")[:2000] or None,
            })
        fmt = "atom"
    else:  # RSS 2.0 / RDF — namespace-agnostic local-name search
        feed_title = txt(root.find(".//channel/title")) or txt(root.find(".//title"))
        entries = root.findall(".//item") or root.findall(".//{*}item")
        for e in entries[:max_items]:
            def sub(name):
                el = e.find(name)
                return el if el is not None else e.find("{*}" + name)
            items.append({
                "title": txt(sub("title")),
                "link": txt(sub("link")) or (sub("guid") is not None and txt(sub("guid"))) or None,
                "published": txt(sub("pubDate")) or txt(sub("date")),
                "summary": (txt(sub("description")) or "")[:2000] or None,
            })
        fmt = "rss"

    if not items:
        raise HTTPException(422, "feed parsed but contained no items")
    return {"feed_url": final, "title": feed_title, "format": fmt,
            "count": len(items), "items": items,
            "fetched_at": datetime.utcnow().isoformat() + "Z"}




# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# x402 route specs
#
# Returned as plain data, not RouteConfig objects: each Space imports the x402 SDK
# inside its own try/except and builds the config there, so a version skew in this
# module can never abort a Space's paywall init (that except path silently serves
# every paid route for free).
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def route_specs(prefix: str = "", cheap: str = "$0.005", mid: str = "$0.01", bulk: str = "$0.02"):
    """(path, price, description, input_example, input_schema, output_example) per route."""
    p = prefix.rstrip("/")
    return [
        (p + "/search", mid,
         "What does the open web say about this query? Ranked title/url/snippet results for agents, "
         "served through an automatic multi-engine failover chain so a single call still answers when "
         "any one backend is blocked, rate-limited or timing out from a datacenter IP",
         {"query": "x402 protocol spec"},
         {"properties": {"query": {"type": "string", "description": "Search query"},
                         "max_results": {"type": "integer", "description": "1-25 results (default 10)"}},
          "required": ["query"]},
         {"query": "x402 protocol spec", "engine": "duckduckgo", "count": 10,
          "results": [{"rank": 1, "title": "x402 spec", "url": "https://example.com/spec",
                       "snippet": "The x402 protocol defines…"}]}),
        (p + "/read", cheap,
         "Fetch a URL and return its main content as clean Markdown (boilerplate stripped)",
         {"url": "https://example.com/article"},
         {"properties": {"url": {"type": "string", "format": "uri", "description": "Page to fetch and clean"},
                         "include_links": {"type": "boolean", "description": "Keep hyperlinks (default true)"}},
          "required": ["url"]},
         {"url": "https://example.com/article", "title": "Article title",
          "markdown": "# Article title\n\nMain content…", "word_count": 1234}),
        (p + "/crawl", bulk,
         "Crawl a site from a start URL (same-domain, breadth-first) and return each page as clean Markdown",
         {"url": "https://example.com/docs", "max_pages": 5},
         {"properties": {"url": {"type": "string", "format": "uri", "description": "Start URL"},
                         "max_pages": {"type": "integer", "description": "1-10 pages (default 5)"},
                         "include_links": {"type": "boolean", "description": "Keep hyperlinks (default true)"}},
          "required": ["url"]},
         {"start_url": "https://example.com/docs", "pages_fetched": 5, "ok": 5,
          "pages": [{"url": "https://example.com/docs", "title": "Docs", "markdown": "# Docs…",
                     "word_count": 800, "depth": 0}]}),
        (p + "/sitemap", cheap,
         "Enumerate a site's URLs from robots.txt + sitemap.xml (sitemap-index aware) — map a domain before crawling it",
         {"url": "https://example.com"},
         {"properties": {"url": {"type": "string", "description": "Site URL or bare domain"},
                         "max_urls": {"type": "integer", "description": "Cap on returned URLs (default 500, max 2000)"}},
          "required": ["url"]},
         {"site": "https://example.com", "sitemaps": ["https://example.com/sitemap.xml"],
          "count": 120, "urls": [{"loc": "https://example.com/a", "lastmod": "2026-07-01"}]}),
        (p + "/rss", cheap,
         "Parse an RSS/Atom feed into structured items (title, link, published, summary) — or auto-discover the feed from a site URL",
         {"url": "https://example.com/feed.xml"},
         {"properties": {"url": {"type": "string", "description": "Feed URL, or a site URL to auto-discover its feed"},
                         "max_items": {"type": "integer", "description": "Cap on items (default 50)"}},
          "required": ["url"]},
         {"feed_url": "https://example.com/feed.xml", "title": "Example Blog", "format": "rss",
          "count": 2, "items": [{"title": "Post", "link": "https://example.com/post",
                                 "published": "2026-07-20T10:00:00Z", "summary": "…"}]}),
    ]
