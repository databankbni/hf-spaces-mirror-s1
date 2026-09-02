#!/usr/bin/env python3
"""DuckDuckGo Lite search module."""
import urllib.request, urllib.parse, ssl, re

def search_duckduckgo(query, max_results=5):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    data = urllib.parse.urlencode({'q': query}).encode()
    req = urllib.request.Request(
        'https://lite.duckduckgo.com/lite/',
        data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded',
                 'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        html = resp.read().decode('utf-8', errors='replace')
    results = []
    links = re.findall(r'<a rel="nofollow" href="([^"]+)"[^>]*>([^<]*)</a>', html)
    snippets = re.findall(r"<td class='result-snippet'>(.*?)</td>", html, re.DOTALL)
    for i, (url, title) in enumerate(links[:max_results]):
        snippet = ''
        if i < len(snippets):
            snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()
        results.append({'title': title.strip(), 'url': url, 'snippet': snippet})
    return results
