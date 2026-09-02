import os
import re
import json
import urllib.request
import urllib.parse
from langchain.tools import tool

WEB_SEARCH_TIMEOUT_SECONDS = float(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "8"))
WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "1").strip().lower() not in {"0", "false", "no"}

import html as html_parser


def wikipedia_search(query: str) -> str:
    """Fetch a short Wikipedia summary for research grounding."""
    if not WEB_SEARCH_ENABLED:
        return "Search disabled."
    try:
        # Prefer a concise topic from the user question
        topic = re.sub(r"(write|research|paper|about|explain|tell me|what is|what are)", " ", query, flags=re.I)
        topic = re.sub(r"\s+", " ", topic).strip()[:120] or query[:120]
        summary_url = (
            "https://en.wikipedia.org/api/rest_v1/page/summary/"
            + urllib.parse.quote(topic.replace(" ", "_"))
        )
        req = urllib.request.Request(
            summary_url,
            headers={"User-Agent": "HealthCareAI/1.0 (educational; contact: local)"},
        )
        with urllib.request.urlopen(req, timeout=WEB_SEARCH_TIMEOUT_SECONDS) as r:
            data = json.loads(r.read().decode("utf-8"))
        title = data.get("title") or topic
        extract = data.get("extract") or ""
        page_url = (data.get("content_urls") or {}).get("desktop", {}).get("page") or ""
        if extract:
            return f"**{title}**\n{extract[:1200]}\nSource: {page_url}"
    except Exception as e:
        print(f"Wikipedia summary failed: {e}")

    # Fallback: OpenSearch API
    try:
        open_url = (
            "https://en.wikipedia.org/w/api.php?action=opensearch&limit=3&namespace=0&format=json&search="
            + urllib.parse.quote(query[:120])
        )
        req = urllib.request.Request(
            open_url,
            headers={"User-Agent": "HealthCareAI/1.0 (educational; contact: local)"},
        )
        with urllib.request.urlopen(req, timeout=WEB_SEARCH_TIMEOUT_SECONDS) as r:
            data = json.loads(r.read().decode("utf-8"))
        titles = data[1] if len(data) > 1 else []
        descs = data[2] if len(data) > 2 else []
        links = data[3] if len(data) > 3 else []
        rows = []
        for i in range(min(len(titles), 3)):
            desc = descs[i] if i < len(descs) else ""
            link = links[i] if i < len(links) else ""
            rows.append(f"{i+1}. **{titles[i]}** — {desc}\n   Link: {link}")
        return "\n".join(rows) if rows else "No Wikipedia results."
    except Exception as e:
        print(f"Wikipedia opensearch failed: {e}")
        return "Wikipedia search failed."


def web_search(query: str) -> str:
    if not WEB_SEARCH_ENABLED:
        return "Search disabled."
    
    # Try DuckDuckGo first with clean parsing
    try:
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=WEB_SEARCH_TIMEOUT_SECONDS) as r:
            html_content = r.read().decode("utf-8")
        
        links_and_titles = re.findall(r'<a[^>]*class="[^\"]*result__a[^\"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html_content, flags=re.DOTALL)
        snippets = re.findall(r'<a[^>]*class="[^\"]*result__snippet[^\"]*"[^>]*>(.*?)</a>', html_content, flags=re.DOTALL)
        
        if links_and_titles and snippets:
            results = []
            for i in range(min(len(links_and_titles), len(snippets), 4)):
                raw_url, raw_title = links_and_titles[i]
                snippet = snippets[i]
                
                # Parse actual URL
                actual_url = raw_url
                if "uddg=" in raw_url:
                    url_parsed = urllib.parse.urlparse(raw_url)
                    query_dict = urllib.parse.parse_qs(url_parsed.query)
                    if "uddg" in query_dict:
                        actual_url = query_dict["uddg"][0]
                elif raw_url.startswith("//"):
                    actual_url = "https:" + raw_url
                    
                title = re.sub(r'<[^>]+>', '', raw_title).strip()
                title = html_parser.unescape(title)
                clean_snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                clean_snippet = html_parser.unescape(clean_snippet)
                
                results.append(f"{i+1}. **{title}**\n   - **Link:** {actual_url}\n   - **Snippet:** {clean_snippet}")
            
            if results:
                return "\n\n".join(results)
    except Exception as e:
        print(f"DuckDuckGo clean parse failed: {e}")
        
    # Fallback to Bing with raw parsing
    sources = [
        "https://www.bing.com/search?q="
    ]
    for source in sources:
        try:
            url = source + urllib.parse.quote(query)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=WEB_SEARCH_TIMEOUT_SECONDS) as r:
                html_content = r.read().decode("utf-8")
            html_content = re.sub(r"<style[^>]*>.*?</style>", "", html_content, flags=re.DOTALL)
            html_content = re.sub(r"<script[^>]*>.*?</script>", "", html_content, flags=re.DOTALL)
            html_content = re.sub(r"<[^>]+>", "", html_content)
            html_content = re.sub(r"\s+", " ", html_content).strip()
            if len(html_content) > 100:
                return html_content[:2000]
        except:
            continue
            
    return "Search failed. No internet or search providers available."

@tool
def search_web(query: str) -> str:
    """Search the web for health information."""
    return web_search(query)

@tool
def fetch_website(url: str) -> str:
    """Fetch content from trusted medical websites like WHO CDC NIH."""
    trusted = ["who.int","cdc.gov","nih.gov","pubmed.ncbi.nlm.nih.gov","mayoclinic.org","webmd.com","wikipedia.org","en.wikipedia.org"]
    if not any(site in url for site in trusted):
        return "Only trusted medical websites allowed."
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8")
        html = re.sub(r"<[^>]+>", "", html)
        html = re.sub(r"\s+", " ", html).strip()
        return html[:3000]
    except Exception as e:
        return f"Failed: {e}"

@tool
def save_file(filename: str, content: str) -> str:
    """Save research or lifestyle findings to a file."""
    os.makedirs("artifacts", exist_ok=True)
    if "." not in filename:
        filename = filename + ".txt"
    path = os.path.join("artifacts", filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Saved to {path}"

@tool
def load_file(filename: str) -> str:
    """Load a previously saved file."""
    path = os.path.join("artifacts", filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return "File not found."

@tool
def show_files() -> str:
    """Show all saved files."""
    if not os.path.exists("artifacts"):
        return "No files saved yet."
    files = os.listdir("artifacts")
    return str(files) if files else "No files saved yet."

all_tools = [search_web, fetch_website, save_file, load_file, show_files]
research_tools = [search_web, fetch_website, save_file, load_file, show_files]
lifestyle_tools = [search_web, save_file, load_file, show_files]
