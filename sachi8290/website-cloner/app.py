import os, re, time, urllib.parse, shutil, posixpath, json
from pathlib import Path
from collections import deque
import requests
from bs4 import BeautifulSoup
import gradio as gr

try:
    from curl_cffi import requests as cffi_requests
    USE_CURL_CFFI = True
except ImportError:
    USE_CURL_CFFI = False

try:
    import cloudscraper
    USE_CLOUDSCRAPER = True
except ImportError:
    USE_CLOUDSCRAPER = False

BYPASS_METHOD = (
    "curl_cffi ✦ Chrome TLS" if USE_CURL_CFFI else
    "cloudscraper"           if USE_CLOUDSCRAPER else
    "requests (limited)"
)

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "max-age=0",
}
IMG_EXTS = {".jpg",".jpeg",".png",".gif",".webp",".svg",".bmp",".tiff",".avif",".ico"}
LAZY_ATTRS = [
    "src","data-src","data-lazy","data-original","data-lazy-src",
    "data-bg","data-background","data-thumb","data-full",
    "data-large_image","data-zoom-image","data-img-url",
    "data-slider-thumb","data-slider-src",
    "data-basesrc","data-masterfile","data-filebase",
    "data-panzoom-image","data-kenburns",
]
MIN_IMG_BYTES = 200


def normalize_domain(netloc):
    """Strip 'www.' and lowercase so www vs non-www variants are treated as the same site."""
    return netloc.lower().split(":")[0].lstrip("www.") if netloc.lower().startswith("www.") else netloc.lower().split(":")[0]


def make_session():
    if USE_CURL_CFFI:
        s = cffi_requests.Session(impersonate="chrome120")
        s.headers.update(HEADERS); return s
    if USE_CLOUDSCRAPER:
        s = cloudscraper.create_scraper(browser={"browser":"chrome","platform":"windows","mobile":False})
        s.headers.update(HEADERS); return s
    s = requests.Session()
    s.headers.update({"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",**HEADERS})
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    retry = Retry(total=3, backoff_factor=1.0, status_forcelist=[429,500,502,503,504])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://",  HTTPAdapter(max_retries=retry))
    return s

def fetch_url(url, session, retries=3, timeout=30):
    for attempt in range(retries+1):
        try:
            r = session.get(url, timeout=timeout, allow_redirects=True)
            if hasattr(r,'raise_for_status'): r.raise_for_status()
            elif r.status_code >= 400: raise Exception(f"HTTP {r.status_code}")
            return r
        except Exception as e:
            if attempt == retries: print(f"  ✗ {str(e)[:50]} → {url[:70]}")
            else: time.sleep(1.5*(attempt+1))
    return None

def save_bytes(data, path):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path,"wb") as f:
            f.write(data if isinstance(data,bytes) else data.encode("utf-8",errors="replace"))
    except: pass

def safe_filename(url, fallback="asset"):
    parsed = urllib.parse.urlparse(url)
    fname  = posixpath.basename(parsed.path)
    fname  = re.sub(r'[^a-zA-Z0-9._\-]','_',fname)
    return (fname or fallback)[:100]

def relative_path(from_file, to_file):
    try: return os.path.relpath(to_file, from_file.parent).replace("\\","/")
    except ValueError: return str(to_file)

def extract_srcset(val, base):
    result = []
    for part in val.split(","):
        part = part.strip()
        if part: result.append(urllib.parse.urljoin(base, part.split()[0]))
    return result

def extract_css_urls(css, base):
    return [urllib.parse.urljoin(base, m.group(1).strip("'\""))
            for m in re.finditer(r'url\(["\']?([^"\')\s]+)["\']?\)', css)
            if not m.group(1).strip("'\"").startswith("data:")]

def extract_all_img_urls(text, page_url):
    found = set()
    for m in re.finditer(r'(https?://[^\s"\'<>\\{}|^`\[\]]+/wp-content/uploads/[^\s"\'<>\\{}|^`\[\]]+\.(?:jpg|jpeg|png|gif|webp|svg|avif|bmp|ico))',text,re.IGNORECASE):
        found.add(m.group(1).split("?")[0])
    for m in re.finditer(r'"(https?://[^"\\]+\.(?:jpg|jpeg|png|gif|webp|avif))(?:["\?\\])',text,re.IGNORECASE):
        found.add(m.group(1))
    for m in re.finditer(r'data-[a-z\-]+=["\'](https?://[^\s"\']+\.(?:jpg|jpeg|png|gif|webp|svg|avif))["\']',text,re.IGNORECASE):
        found.add(m.group(1))
    for m in re.finditer(r'["\'](/wp-content/uploads/[^\s"\'<>]+\.(?:jpg|jpeg|png|gif|webp|svg|avif|ico))["\']',text,re.IGNORECASE):
        found.add(urllib.parse.urljoin(page_url, m.group(1)))
    for m in re.finditer(r'background(?:-image)?\s*:\s*url\(["\']?(https?://[^"\')\s]+)["\']?\)',text,re.IGNORECASE):
        u = m.group(1)
        if Path(urllib.parse.urlparse(u).path).suffix.lower() in IMG_EXTS: found.add(u)
    for m in re.finditer(r'(https?:\\u002F\\u002F[^"\'\\]+\\u002Fwp-content[^"\'\\]+\.(?:jpg|jpeg|png|gif|webp))',text,re.IGNORECASE):
        try: found.add(m.group(1).encode().decode("unicode_escape").split("?")[0])
        except: pass
    for m in re.finditer(r'(https?%3A%2F%2F[^\s"\'&<>]+\.(?:jpg|jpeg|png|gif|webp|avif))(?:["\s&]|$)',text,re.IGNORECASE):
        found.add(urllib.parse.unquote(m.group(1)))
    for m in re.finditer(r'"srcset"\s*:\s*"([^"]+)"',text):
        raw = m.group(1).replace("\\n","\n").replace("\\t","")
        for part in raw.split(","):
            p = part.strip().split()[0] if part.strip() else ""
            if p.startswith("http"): found.add(p)
    for m in re.finditer(r'["\']src["\']\s*:\s*["\'](https?://[^"\']+\.(?:jpg|jpeg|png|gif|webp|avif))["\']',text,re.IGNORECASE):
        found.add(m.group(1))
    for m in re.finditer(r'(https?://[^\s"\'<>{}|^`\[\]\\]+\.(?:jpg|jpeg|png|gif|webp|avif))(?:\?[^\s"\'<>]*)?',text,re.IGNORECASE):
        u = m.group(1)
        if "1x1" not in u and "pixel" not in u.lower() and "track" not in u.lower(): found.add(u)
    return found

def wp_rest_api_images(base_url, session):
    all_urls = []
    for page in range(1,11):
        api_url = f"{base_url}/wp-json/wp/v2/media?per_page=100&page={page}&_fields=source_url,media_details"
        r = fetch_url(api_url, session)
        if not r: break
        try: items = json.loads(r.text)
        except: break
        if not items or not isinstance(items,list): break
        for item in items:
            src = item.get("source_url","")
            if src: all_urls.append(src)
            sizes = (item.get("media_details") or {}).get("sizes",{})
            for sz in sizes.values():
                su = sz.get("source_url","")
                if su and su != src: all_urls.append(su)
        if len(items) < 100: break
    return all_urls

def sitemap_images(base_url, session):
    found = []
    for smap in [f"{base_url}/sitemap.xml",f"{base_url}/sitemap_index.xml",f"{base_url}/image-sitemap.xml",f"{base_url}/wp-sitemap.xml"]:
        r = fetch_url(smap, session)
        if not r: continue
        ct = r.headers.get("content-type","")
        if "xml" not in ct and "html" not in ct: continue
        for m in re.finditer(r'<image:loc>(https?://[^<]+)</image:loc>',r.text): found.append(m.group(1).strip())
        for m in re.finditer(r'<loc>(https?://[^<]+\.(?:jpg|jpeg|png|gif|webp|avif))</loc>',r.text,re.IGNORECASE): found.append(m.group(1).strip())
        if found: break
    return found


# ══════════════════════════════════════════════════════
#  TOOL 1
# ══════════════════════════════════════════════════════
def clone_website(url_input, progress=gr.Progress()):
    raw_url = url_input.strip()
    if not raw_url: return None, "⚠️ Please enter a URL."
    if not raw_url.startswith("http"): raw_url = "https://" + raw_url
    base_domain = urllib.parse.urlparse(raw_url).netloc
    base_domain_norm = normalize_domain(base_domain)
    origin      = f"{urllib.parse.urlparse(raw_url).scheme}://{base_domain}"
    domain_name = base_domain.replace("www.","").split(".")[0]
    out_dir  = Path(f"/tmp/{domain_name}_clone")
    zip_base = f"/tmp/{domain_name}_clone"
    zip_path = zip_base + ".zip"
    if out_dir.exists(): shutil.rmtree(out_dir)
    if os.path.exists(zip_path): os.remove(zip_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = make_session()
    visited = set(); asset_done = {}; js_img_queue = []; queue = deque([raw_url])
    logs = [f"🛡 {BYPASS_METHOD}"]
    img_n = img_fail = page_n = 0; folder_map = {}

    def _img_n_get(): return img_n
    def _img_n_inc(): nonlocal img_n; img_n += 1
    def _img_fail_inc(): nonlocal img_fail; img_fail += 1

    def download_img(abs_u, folder):
        img_local = folder/"images"/safe_filename(abs_u,f"img_{_img_n_get()}.jpg")
        c = 1
        while img_local.exists():
            s,e = os.path.splitext(img_local.name); img_local = folder/"images"/f"{s}_{c}{e}"; c+=1
        r2 = fetch_url(abs_u, session)
        if r2 and len(r2.content) >= MIN_IMG_BYTES:
            save_bytes(r2.content, img_local); _img_n_inc(); return img_local
        else: _img_fail_inc(); return None

    def get_asset(abs_url):
        if abs_url in asset_done: return asset_done[abs_url]
        p   = urllib.parse.urlparse(abs_url)
        sub = re.sub(r'[^a-zA-Z0-9._/\-]','_',(p.netloc+p.path).lstrip("/"))
        local = out_dir/"_assets"/sub; asset_done[abs_url] = local
        r = fetch_url(abs_url, session)
        if r:
            ct = r.headers.get("content-type","")
            if "css" in ct or abs_url.endswith(".css"): save_bytes(rewrite_css(r.text,abs_url), local)
            elif "javascript" in ct or "ecmascript" in ct or abs_url.endswith(".js"):
                save_bytes(r.content, local)
                for u in extract_all_img_urls(r.text, abs_url):
                    if u not in asset_done: js_img_queue.append(u)
            else: save_bytes(r.content, local)
        return local

    def rewrite_css(css_text, css_url):
        def rep(m):
            raw = m.group(1).strip("'\"")
            if raw.startswith("data:") or raw.startswith("#"): return m.group(0)
            local = get_asset(urllib.parse.urljoin(css_url, raw))
            return "url('"+str(local)+"')"
        return re.sub(r'url\(["\']?([^"\')\s]+)["\']?\)', rep, css_text)

    def process_page(page_url, folder):
        r = fetch_url(page_url, session)
        if not r: logs.append(f"  ✗ No response → {page_url}"); return None
        ct = r.headers.get("content-type","")
        if "html" not in ct.lower() and "text" not in ct.lower(): logs.append(f"  ✗ Non-HTML ({ct!r})"); return None
        sample = r.content[:300].decode("utf-8",errors="replace").strip().lower()
        if "<html" not in sample and "<!doctype" not in sample and not sample.startswith("<!"):
            logs.append("  ✗ Response doesn't look like HTML"); return None
        raw_html = r.text; soup = BeautifulSoup(r.content,"html.parser")
        for tag in soup.find_all("link", rel=lambda x: x and "stylesheet" in x):
            href = tag.get("href","")
            if not href or href.startswith("data:"): continue
            local = get_asset(urllib.parse.urljoin(page_url,href)); tag["href"] = relative_path(folder/"index.html",local)
        for tag in soup.find_all("script", src=True):
            src = tag.get("src","")
            if not src or src.startswith("data:"): continue
            local = get_asset(urllib.parse.urljoin(page_url,src)); tag["src"] = relative_path(folder/"index.html",local)
        for tag in soup.find_all(["img","source","video","audio","rs-slide","rs-bgvideo"]):
            for attr in LAZY_ATTRS:
                val = tag.get(attr,"")
                if not val or val.startswith("data:"): continue
                abs_u = urllib.parse.urljoin(page_url,val)
                if Path(urllib.parse.urlparse(abs_u).path).suffix.lower() in IMG_EXTS:
                    il = download_img(abs_u,folder)
                    if il: tag[attr] = relative_path(folder/"index.html",il)
            for attr in ["srcset","data-srcset"]:
                val = tag.get(attr,"")
                if not val: continue
                new_parts = []
                for part in val.split(","):
                    part = part.strip()
                    if not part: continue
                    pieces = part.split(); abs_u = urllib.parse.urljoin(page_url,pieces[0])
                    if Path(urllib.parse.urlparse(abs_u).path).suffix.lower() in IMG_EXTS:
                        il = download_img(abs_u,folder)
                        if il: pieces[0] = relative_path(folder/"index.html",il)
                    new_parts.append(" ".join(pieces))
                tag[attr] = ", ".join(new_parts)
        for tag in soup.find_all(style=True):
            sv = tag.get("style","")
            def irep(m):
                raw = m.group(1).strip("'\"")
                if raw.startswith("data:") or raw.startswith("#"): return m.group(0)
                abs_u = urllib.parse.urljoin(page_url,raw)
                if Path(urllib.parse.urlparse(abs_u).path).suffix.lower() in IMG_EXTS:
                    il = download_img(abs_u,folder)
                    if il: return "url('"+relative_path(folder/"index.html",il)+"')"
                return m.group(0)
            tag["style"] = re.sub(r'url\(["\']?([^"\')\s]+)["\']?\)', irep, sv)
        for tag in soup.find_all("style"): tag.string = rewrite_css(tag.get_text(), page_url)
        extra_imgs = extract_all_img_urls(raw_html, page_url)
        logs.append(f"  📄 HTML regex → {len(extra_imgs)} URLs found")
        new_cnt = 0
        for abs_u in extra_imgs:
            if abs_u not in asset_done: new_cnt+=1; download_img(abs_u,folder)
        logs.append(f"  📥 {new_cnt} new downloaded (total: {img_n})")
        links = []
        for tag in soup.find_all("a",href=True):
            href = tag["href"]
            if href.startswith(("#","tel:","mailto:","javascript:")): continue
            abs_a = urllib.parse.urljoin(page_url,href).split("#")[0].split("?")[0].rstrip("/")
            if normalize_domain(urllib.parse.urlparse(abs_a).netloc) == base_domain_norm and abs_a not in visited:
                links.append(abs_a)
        return soup, links

    progress(0.05, desc="🗃 WordPress REST API scan...")
    try: api_urls = wp_rest_api_images(origin,session); logs.append(f"🗃 WP REST API → {len(api_urls)} media items found")
    except Exception as e: api_urls = []; logs.append(f"🗃 WP REST API → failed ({e})")
    progress(0.08, desc="🗺 Sitemap scan...")
    try: smap_urls = sitemap_images(origin,session); logs.append(f"🗺 Sitemap → {len(smap_urls)} image URLs")
    except Exception as e: smap_urls = []; logs.append(f"🗺 Sitemap → failed ({e})")
    pre_scan_urls = list(set(api_urls+smap_urls))

    while queue:
        url = queue.popleft().split("#")[0].split("?")[0].rstrip("/") or raw_url
        if url in visited: continue
        visited.add(url); page_n+=1
        progress(min(0.93,0.10+0.83*page_n/max(page_n+len(queue),1)),
                 desc=f"📄 {page_n} pages | 🖼 {img_n} imgs | Queue {len(queue)} | {url[:45]}...")
        pp = urllib.parse.urlparse(url); path_part = pp.path.strip("/")
        fname = "home" if not path_part else re.sub(r'_+','_',re.sub(r'[^a-zA-Z0-9_\-]','_',path_part)).strip("_")[:80] or "page"
        folder = out_dir/fname; i = 2
        while folder.exists() and any(v==folder for v in folder_map.values()):
            folder = out_dir/f"{fname}_{i}"; i+=1
        folder.mkdir(parents=True,exist_ok=True); folder_map[url] = folder
        if page_n==1 and pre_scan_urls:
            logs.append(f"  ⬇ Downloading {len(pre_scan_urls)} pre-scan images...")
            for u in pre_scan_urls:
                if u not in asset_done: download_img(u,folder)
            logs.append(f"  ✓ Pre-scan done (total imgs: {img_n})")
        result = process_page(url, folder)
        if result is None: logs.append(f"✗ {url}"); continue
        soup, links = result
        save_bytes(str(soup).encode("utf-8"), folder/"index.html")
        logs.append(f"✓ [{page_n}] {folder.name}/  imgs={img_n}")
        for link in links:
            if link not in visited: queue.append(link)
        time.sleep(0.25)

    if js_img_queue:
        js_folder = list(folder_map.values())[0] if folder_map else out_dir/"home"
        js_folder.mkdir(parents=True,exist_ok=True)
        logs.append(f"🔧 JS scan queue: {len(js_img_queue)} URLs")
        js_done = 0
        for u in js_img_queue:
            if u not in asset_done:
                il = download_img(u,js_folder)
                if il: js_done+=1
        logs.append(f"  ✓ JS images: {js_done} downloaded")

    progress(0.95, desc="🔗 Fixing internal links...")
    for pu,fld in folder_map.items():
        hf = fld/"index.html"
        if not hf.exists(): continue
        content = open(hf,"rb").read().decode("utf-8",errors="replace")
        for lu,lf in folder_map.items():
            if lu in content:
                rel = relative_path(hf,lf/"index.html")
                content = content.replace(f'href="{lu}"',f'href="{rel}"').replace(f"href='{lu}'",f"href='{rel}'")
        save_bytes(content.encode("utf-8"),hf)

    lines = [f"Website: {raw_url}",f"Pages: {page_n}",f"Images saved: {img_n}",
             f"Failed/skipped: {img_fail}",f"Bypass: {BYPASS_METHOD}","","Folders","="*40]
    for u,fld in folder_map.items():
        ic = len(list((fld/"images").glob("*"))) if (fld/"images").exists() else 0
        lines.append(f"  {fld.name}/  ({ic} imgs)  ← {u}")
    save_bytes("\n".join(lines).encode(), out_dir/"SUMMARY.txt")
    progress(0.97, desc="📦 Creating ZIP...")
    shutil.make_archive(zip_base,"zip",out_dir)
    size_mb = os.path.getsize(zip_path)/(1024*1024)
    return zip_path, (
        f"✅ Clone complete!\n🛡 {BYPASS_METHOD}\n"
        f"📄 Pages: {page_n}  |  🖼 Images: {img_n}  |  ❌ Failed: {img_fail}\n"
        f"📁 Folders: {len(folder_map)}  |  📦 ZIP: {size_mb:.1f} MB\n\n"
        +"\n".join(f"  📂 {v.name}/  ({len(list((v/'images').glob('*'))) if (v/'images').exists() else 0} imgs)" for v in list(folder_map.values())[:30])
        +"\n\n── Log ──\n"+"\n".join(logs[-70:])
    )


# ══════════════════════════════════════════════════════
#  TOOL 2
# ══════════════════════════════════════════════════════
def download_website_images(url_input, progress=gr.Progress()):
    raw_url = url_input.strip()
    if not raw_url: return None,"⚠️ Please enter a URL."
    if not raw_url.startswith("http"): raw_url = "https://"+raw_url
    base_domain = urllib.parse.urlparse(raw_url).netloc
    base_domain_norm = normalize_domain(base_domain)
    origin      = f"{urllib.parse.urlparse(raw_url).scheme}://{base_domain}"
    domain_name = base_domain.replace("www.","").split(".")[0]
    out_dir  = Path(f"/tmp/{domain_name}_images")
    zip_base = f"/tmp/{domain_name}_images"; zip_path = zip_base+".zip"
    if out_dir.exists(): shutil.rmtree(out_dir)
    if os.path.exists(zip_path): os.remove(zip_path)
    out_dir.mkdir(parents=True,exist_ok=True)
    session = make_session(); img_urls = set()
    progress(0.03, desc="🗃 WordPress REST API...")
    try:
        for u in wp_rest_api_images(origin,session): img_urls.add(u)
    except: pass
    progress(0.06, desc="🗺 Sitemap scan...")
    try:
        for u in sitemap_images(origin,session): img_urls.add(u)
    except: pass
    visited = set(); queue = deque([raw_url]); page_n = 0
    while queue:
        url = queue.popleft().split("#")[0].split("?")[0].rstrip("/") or raw_url
        if url in visited: continue
        visited.add(url); page_n+=1
        progress(0.08+0.77*min(1,page_n/max(page_n+len(queue),1)),
                 desc=f"Scanning page {page_n} | {len(img_urls)} URLs so far...")
        r = fetch_url(url, session)
        if not r: continue
        ct = r.headers.get("content-type","")
        if "html" not in ct.lower() and "text" not in ct.lower(): continue
        soup = BeautifulSoup(r.content,"html.parser")
        for u in extract_all_img_urls(r.text,url): img_urls.add(u)
        for tag in soup.find_all(["img","source","video"]):
            for attr in LAZY_ATTRS+["srcset","data-srcset"]:
                val = tag.get(attr,"")
                if not val or val.startswith("data:"): continue
                urls = extract_srcset(val,url) if "srcset" in attr else [urllib.parse.urljoin(url,val)]
                for u in urls:
                    if Path(urllib.parse.urlparse(u).path).suffix.lower() in IMG_EXTS: img_urls.add(u)
        for a in soup.find_all("a",href=True):
            abs_a = urllib.parse.urljoin(url,a["href"]).split("#")[0].split("?")[0].rstrip("/")
            if normalize_domain(urllib.parse.urlparse(abs_a).netloc) == base_domain_norm and abs_a not in visited:
                queue.append(abs_a)
        time.sleep(0.2)
    total = len(img_urls); saved = 0; logs = [f"Found {total} URLs across {page_n} pages"]
    for i, img_url in enumerate(sorted(img_urls)):
        progress(0.85+0.13*(i/max(total,1)), desc=f"Downloading {i+1}/{total}...")
        r = fetch_url(img_url, session)
        if not r or len(r.content)<MIN_IMG_BYTES: logs.append(f"✗ skip {img_url[:60]}"); continue
        fname = safe_filename(img_url,f"img_{i:04d}.jpg")
        fpath = out_dir/fname; c=1
        while fpath.exists():
            s,e = os.path.splitext(fname); fpath = out_dir/f"{s}_{c}{e}"; c+=1
        save_bytes(r.content,fpath); saved+=1; logs.append(f"✓ {fname}  ({len(r.content)//1024} KB)")
    progress(0.99, desc="Creating ZIP...")
    shutil.make_archive(zip_base,"zip",out_dir)
    size_mb = os.path.getsize(zip_path)/(1024*1024)
    return zip_path,(f"✅ Done!\n🛡 {BYPASS_METHOD}\n🖼 {saved}/{total} images  |  📄 {page_n} pages  |  📦 {size_mb:.1f} MB\n\n"+"\n".join(logs[-40:]))


# ══════════════════════════════════════════════════════
#  TOOL 3
# ══════════════════════════════════════════════════════
def find_gmb_photos(maps_url_input, progress=gr.Progress()):
    raw_input = maps_url_input.strip()
    if not raw_input: return [],"⚠️ Please enter a Google Maps URL or Place ID.",gr.update(visible=False)
    if not raw_input.startswith("http"): raw_url = f"https://www.google.com/maps/place/?q=place_id:{raw_input}"
    else: raw_url = raw_input
    progress(0.1, desc="Fetching Google Maps page...")
    session = make_session(); found = set()
    decoded = urllib.parse.unquote(raw_url)
    for pat in [r'(https://lh[0-9]\.googleusercontent\.com/[A-Za-z0-9_\-/]+=?[A-Za-z0-9\-]*)',r'(https://lh[0-9]\.ggpht\.com/[A-Za-z0-9_\-/=?&]+)']:
        for m in re.finditer(pat,decoded):
            u = re.sub(r'=w\d+-h\d+[^\s"\']*','=w800-h600-k-no',m.group(1))
            if len(u)>40: found.add(u)
    urls_to_try = [raw_url]
    place_path = re.search(r'(/maps/place/[^/@?&]+)',raw_url)
    if place_path: urls_to_try.append(f"https://www.google.com{place_path.group(1)}/photos")
    for i,fetch_u in enumerate(urls_to_try):
        progress(0.1+0.3*i, desc=f"Fetching page {i+1}...")
        r = fetch_url(fetch_u, session)
        if not r: continue
        text = r.text
        for pat in [r'(https://lh[0-9]\.googleusercontent\.com/p/[A-Za-z0-9_\-]+=?[A-Za-z0-9\-]*)',r'(https://lh[0-9]\.googleusercontent\.com/[A-Za-z0-9_\-/]+=s[0-9]+[^\s"\'\\<]*)',r'(https://lh[0-9]\.googleusercontent\.com/[A-Za-z0-9_\-/]+=w[0-9]+[^\s"\'\\<]*)',r'"url":"(https://lh[0-9][^"]+)"']:
            for m in re.finditer(pat,text):
                u = m.group(1).replace("\\u003d","=").replace("\\u0026","&")
                u = re.sub(r'=w\d+-h\d+[^\s"\'\\<]*','=w800-h600-k-no',u); u = re.sub(r'=s\d+','=s800',u)
                if len(u)>40: found.add(u)
        for enc in re.finditer(r'(https?%3A%2F%2Flh[^"\'&\s]{30,})',text):
            u = urllib.parse.unquote(enc.group(1)); u = re.sub(r'=w\d+-h\d+[^\s"\']*','=w800-h600-k-no',u)
            if len(u)>40: found.add(u)
    deduped = {}
    for u in found:
        base = re.sub(r'=[whs][0-9].*$','',u)
        if base not in deduped: deduped[base]=u
    found = list(deduped.values())
    if not found: return [],"⚠️ No photos found.",gr.update(visible=False)
    progress(0.7, desc=f"Loading {len(found)} previews...")
    preview_imgs = []
    for i,url in enumerate(found):
        r = fetch_url(url,session)
        if r and len(r.content)>2048: preview_imgs.append(r.content)
        progress(0.7+0.28*(i/max(len(found),1)),desc=f"Preview {i+1}/{len(found)}...")
    url_list = "\n".join(found)
    return preview_imgs,f"✅ Found {len(preview_imgs)} photos!",gr.update(visible=True,value=url_list)

def download_selected_gmb(url_state, progress=gr.Progress()):
    if not url_state or not url_state.strip(): return None,"⚠️ No photos. Please search first."
    photo_urls = [u.strip() for u in url_state.strip().split("\n") if u.strip()]
    if not photo_urls: return None,"⚠️ No photos found."
    session = make_session(); out_dir = Path("/tmp/gmb_photos_download")
    zip_base = str(out_dir); zip_path = zip_base+".zip"
    if out_dir.exists(): shutil.rmtree(out_dir)
    if os.path.exists(zip_path): os.remove(zip_path)
    out_dir.mkdir(parents=True,exist_ok=True)
    logs=[]; saved=0
    for i,url in enumerate(photo_urls):
        hires = re.sub(r'=w\d+-h\d+[^\s"\']*','=w1920-h1080-k-no',url); hires = re.sub(r'=s\d+','=s1600',hires)
        progress(i/max(len(photo_urls),1),desc=f"Downloading {i+1}/{len(photo_urls)}...")
        r = fetch_url(hires,session)
        if not r or len(r.content)<2048: r = fetch_url(url,session)
        if not r or len(r.content)<2048: continue
        ct = r.headers.get("content-type","image/jpeg")
        ext = ".jpg" if "jpeg" in ct else ".png" if "png" in ct else ".webp" if "webp" in ct else ".jpg"
        fpath = out_dir/f"photo_{i+1:03d}{ext}"; save_bytes(r.content,fpath); saved+=1
        logs.append(f"✓ photo_{i+1:03d}{ext}  ({len(r.content)//1024} KB)")
    progress(0.97,desc="Creating ZIP...")
    shutil.make_archive(zip_base,"zip",out_dir)
    size_mb = os.path.getsize(zip_path)/(1024*1024)
    return zip_path,f"✅ {saved}/{len(photo_urls)} photos  |  📦 {size_mb:.1f} MB\n\n"+"\n".join(logs[:50])


# ══════════════════════════════════════════════════════
#  CSS — White / Editorial Theme with Animations
# ══════════════════════════════════════════════════════

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Bricolage+Grotesque:opsz,wght@10..48,300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(18px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes shimmer {
  0%   { background-position: -600px 0; }
  100% { background-position:  600px 0; }
}
@keyframes pulseRing {
  0%,100% { box-shadow: 0 0 0 0 rgba(234,88,12,0.35); }
  50%      { box-shadow: 0 0 0 8px rgba(234,88,12,0); }
}
@keyframes slideIn {
  from { opacity: 0; transform: translateX(-12px); }
  to   { opacity: 1; transform: translateX(0); }
}
@keyframes floatY {
  0%,100% { transform: translateY(0px); }
  50%      { transform: translateY(-5px); }
}
@keyframes gradientFlow {
  0%   { background-position: 0% 50%; }
  50%  { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}
@keyframes scaleIn {
  from { opacity: 0; transform: scale(0.94); }
  to   { opacity: 1; transform: scale(1); }
}
@keyframes dotPulse {
  0%,100% { opacity: 1; }
  50%      { opacity: 0.3; }
}
*, *::before, *::after { box-sizing: border-box; }
:root {
  --white:   #ffffff;
  --off:     #fafaf8;
  --cream:   #f5f3ef;
  --border:  #e8e4de;
  --border2: #d4cfc6;
  --text:    #1a1814;
  --muted:   #7a7368;
  --muted2:  #b0a99e;
  --amber:   #ea580c;
  --amber2:  #f97316;
  --amber-soft: rgba(234,88,12,0.08);
  --amber-glow: rgba(234,88,12,0.2);
  --teal:    #0d9488;
  --teal-soft: rgba(13,148,136,0.08);
  --violet:  #7c3aed;
  --violet-soft: rgba(124,58,237,0.08);
  --green:   #16a34a;
  --green-soft: rgba(22,163,74,0.08);
  --radius:  16px;
  --radius-sm: 10px;
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
  --shadow:  0 4px 16px rgba(0,0,0,0.07), 0 1px 4px rgba(0,0,0,0.05);
  --shadow-lg: 0 12px 40px rgba(0,0,0,0.10), 0 4px 12px rgba(0,0,0,0.06);
}
html, body, .gradio-container, #root {
  background: var(--off) !important;
  font-family: 'Bricolage Grotesque', sans-serif !important;
  color: var(--text) !important;
  min-height: 100vh;
}
footer { display: none !important; }
.svelte-pbdop0 { display: none !important; }
.gradio-container { padding: 0 !important; max-width: 100% !important; }
/* ── TABS ── */
.tabs {
  background: var(--white) !important;
  border-bottom: 1px solid var(--border) !important;
  padding: 0 36px !important;
  margin: 0 !important;
  box-shadow: var(--shadow-sm) !important;
}
.tab-nav {
  background: transparent !important;
  border: none !important;
  padding: 0 !important;
  gap: 0 !important;
}
.tab-nav button {
  font-family: 'Bricolage Grotesque', sans-serif !important;
  font-size: 13.5px !important;
  font-weight: 600 !important;
  color: var(--muted) !important;
  background: transparent !important;
  border: none !important;
  border-bottom: 2.5px solid transparent !important;
  padding: 16px 22px !important;
  transition: all 0.25s cubic-bezier(0.4,0,0.2,1) !important;
  border-radius: 0 !important;
  letter-spacing: -0.01em !important;
  position: relative !important;
}
.tab-nav button::after {
  content: '';
  position: absolute;
  bottom: -1px; left: 50%; right: 50%;
  height: 2.5px;
  background: var(--amber);
  transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
  border-radius: 2px 2px 0 0;
}
.tab-nav button:hover { color: var(--text) !important; }
.tab-nav button:hover::after { left: 20%; right: 20%; }
.tab-nav button.selected {
  color: var(--amber) !important;
  border-bottom-color: transparent !important;
}
.tab-nav button.selected::after { left: 0 !important; right: 0 !important; }
.tabitem {
  background: var(--off) !important;
  padding: 28px 36px !important;
  border: none !important;
  animation: fadeUp 0.4s cubic-bezier(0.4,0,0.2,1) !important;
}
/* ── BLOCKS ── */
.block, .gr-box, .form, .gap {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  gap: 14px !important;
}
/* ── INPUT ── */
.gr-text-input, input[type="text"], .gr-input {
  background: var(--white) !important;
  border: 1.5px solid var(--border) !important;
  border-radius: var(--radius-sm) !important;
  color: var(--text) !important;
  font-family: 'JetBrains Mono', monospace !important;
  font-size: 13px !important;
  padding: 12px 16px !important;
  box-shadow: var(--shadow-sm) !important;
  transition: border-color 0.2s, box-shadow 0.2s !important;
}
input[type="text"]:focus {
  border-color: var(--amber) !important;
  box-shadow: 0 0 0 3px var(--amber-glow), var(--shadow-sm) !important;
  outline: none !important;
}
/* ── LABELS ── */
label > span, .gr-form label, label {
  font-family: 'Bricolage Grotesque', sans-serif !important;
  font-size: 11px !important;
  font-weight: 700 !important;
  letter-spacing: 0.08em !important;
  text-transform: uppercase !important;
  color: var(--muted) !important;
}
/* ── TEXTAREA (log) ── */
textarea {
  background: #1a1814 !important;
  border: 1.5px solid var(--border) !important;
  border-radius: var(--radius-sm) !important;
  color: #86efac !important;
  font-family: 'JetBrains Mono', monospace !important;
  font-size: 11.5px !important;
  line-height: 1.9 !important;
  box-shadow: inset 0 2px 8px rgba(0,0,0,0.15) !important;
}
/* ── BUTTONS ── */
.primary {
  background: var(--amber) !important;
  border: none !important;
  border-radius: var(--radius-sm) !important;
  color: #fff !important;
  font-family: 'Bricolage Grotesque', sans-serif !important;
  font-size: 14px !important;
  font-weight: 700 !important;
  letter-spacing: -0.01em !important;
  padding: 14px 28px !important;
  box-shadow: 0 2px 8px var(--amber-glow), var(--shadow-sm) !important;
  transition: all 0.2s cubic-bezier(0.4,0,0.2,1) !important;
  cursor: pointer !important;
  animation: pulseRing 3s ease-in-out infinite !important;
  position: relative !important;
  overflow: hidden !important;
}
.primary::before {
  content: '';
  position: absolute;
  top: 0; left: -100%;
  width: 100%; height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
  transition: left 0.5s ease;
}
.primary:hover::before { left: 100%; }
.primary:hover {
  background: #c2410c !important;
  box-shadow: 0 6px 20px var(--amber-glow), var(--shadow) !important;
  transform: translateY(-2px) !important;
}
.primary:active { transform: translateY(0) !important; }
.secondary {
  background: var(--white) !important;
  border: 1.5px solid var(--border) !important;
  border-radius: var(--radius-sm) !important;
  color: var(--text) !important;
  font-family: 'Bricolage Grotesque', sans-serif !important;
  font-size: 13px !important;
  font-weight: 600 !important;
  box-shadow: var(--shadow-sm) !important;
  transition: all 0.2s !important;
}
.secondary:hover {
  border-color: var(--amber) !important;
  color: var(--amber) !important;
  box-shadow: 0 2px 10px var(--amber-glow) !important;
  transform: translateY(-1px) !important;
}
/* ── FILE ── */
.file-preview {
  background: var(--white) !important;
  border: 1.5px solid var(--border) !important;
  border-radius: var(--radius-sm) !important;
  box-shadow: var(--shadow-sm) !important;
}
.file-name { color: var(--text) !important; font-family: 'JetBrains Mono', monospace !important; font-size: 12px !important; }
/* ── GALLERY ── */
.gallery { background: transparent !important; }
.gallery img {
  border-radius: 10px !important;
  transition: transform 0.3s, box-shadow 0.3s !important;
}
.gallery img:hover {
  transform: scale(1.04) !important;
  box-shadow: var(--shadow-lg) !important;
}
/* ── MARKDOWN ── */
.md p, .md li { color: var(--muted) !important; font-size: 13px !important; line-height: 1.7 !important; }
.md strong { color: var(--text) !important; font-weight: 700 !important; }
.md code {
  background: var(--cream) !important;
  border: 1px solid var(--border) !important;
  color: var(--amber) !important;
  border-radius: 5px !important;
  padding: 1px 6px !important;
  font-family: 'JetBrains Mono', monospace !important;
  font-size: 11.5px !important;
}
/* ── SCROLLBAR ── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: var(--cream); }
::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--amber); }
/* ── PROGRESS ── */
progress { accent-color: var(--amber) !important; }
/* ── FEATURE CARD HOVER ── */
.feat-card {
  transition: transform 0.25s cubic-bezier(0.4,0,0.2,1),
              box-shadow 0.25s cubic-bezier(0.4,0,0.2,1) !important;
}
.feat-card:hover {
  transform: translateY(-3px) !important;
  box-shadow: var(--shadow-lg) !important;
}
"""

# ── HTML Blocks ──────────────────────────────────────

HEADER_HTML = f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Bricolage+Grotesque:opsz,wght@10..48,600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
  @keyframes meshMove {{
    0%,100% {{ background-position: 0% 50%; }}
    50%      {{ background-position: 100% 50%; }}
  }}
  @keyframes fadeUp {{
    from {{ opacity:0; transform:translateY(16px); }}
    to   {{ opacity:1; transform:translateY(0); }}
  }}
  @keyframes tagBlink {{
    0%,100% {{ opacity:1; }} 50% {{ opacity:0.5; }}
  }}
  @keyframes float {{
    0%,100% {{ transform:translateY(0); }} 50% {{ transform:translateY(-4px); }}
  }}
  .wt-header {{
    background: linear-gradient(135deg,#fff9f5 0%,#fff 40%,#f0fdf8 70%,#fdf4ff 100%);
    background-size: 300% 300%;
    animation: meshMove 8s ease-in-out infinite;
    border-bottom: 1px solid #e8e4de;
    padding: 28px 36px 24px;
    position: relative;
    overflow: hidden;
  }}
  .wt-header::before {{
    content:'';
    position:absolute; inset:0;
    background: radial-gradient(ellipse at 20% 50%,rgba(234,88,12,0.06) 0%,transparent 60%),
                radial-gradient(ellipse at 80% 20%,rgba(124,58,237,0.05) 0%,transparent 55%),
                radial-gradient(ellipse at 60% 80%,rgba(13,148,136,0.05) 0%,transparent 50%);
    pointer-events:none;
  }}
  .wt-header-inner {{
    display:flex; align-items:center; justify-content:space-between;
    flex-wrap:wrap; gap:16px; position:relative; z-index:1;
    animation: fadeUp 0.6s ease;
  }}
  .wt-logo {{
    display:flex; align-items:center; gap:16px;
  }}
  .wt-icon {{
    width:54px; height:54px;
    background: #ea580c;
    border-radius:15px;
    display:flex; align-items:center; justify-content:center;
    font-size:24px;
    box-shadow: 0 4px 20px rgba(234,88,12,0.28), 0 1px 4px rgba(0,0,0,0.08);
    animation: float 4s ease-in-out infinite;
    flex-shrink:0;
  }}
  .wt-title {{
    font-family:'Instrument Serif',serif;
    font-size:30px; font-weight:400;
    color:#1a1814; line-height:1;
    letter-spacing:-0.02em;
  }}
  .wt-title em {{
    font-style:italic; color:#ea580c;
  }}
  .wt-subtitle {{
    margin-top:6px;
    font-family:'Bricolage Grotesque',sans-serif;
    font-size:12px; font-weight:600;
    color:#7a7368; letter-spacing:0.04em;
    text-transform:uppercase;
  }}
  .wt-badge {{
    display:inline-flex; align-items:center; gap:5px;
    background:#fff8f5; border:1.5px solid rgba(234,88,12,0.25);
    color:#ea580c; font-family:'JetBrains Mono',monospace;
    font-size:10.5px; font-weight:500;
    padding:4px 12px; border-radius:20px;
    animation: tagBlink 2.5s ease-in-out infinite;
  }}
  .wt-badge::before {{
    content:''; width:6px; height:6px;
    background:#ea580c; border-radius:50%;
    box-shadow:0 0 6px rgba(234,88,12,0.5);
  }}
  .wt-pills {{
    display:flex; gap:10px; flex-wrap:wrap;
  }}
  .wt-pill {{
    display:flex; align-items:center; gap:8px;
    background:#fff; border:1px solid #e8e4de;
    border-radius:12px; padding:10px 16px;
    box-shadow:0 1px 4px rgba(0,0,0,0.04);
    transition: transform 0.2s, box-shadow 0.2s;
  }}
  .wt-pill:hover {{
    transform:translateY(-2px);
    box-shadow:0 4px 14px rgba(0,0,0,0.08);
  }}
  .wt-pill-icon {{
    width:32px; height:32px; border-radius:9px;
    display:flex; align-items:center; justify-content:center;
    font-size:14px;
  }}
  .wt-pill-text {{ font-family:'Bricolage Grotesque',sans-serif; }}
  .wt-pill-label {{ font-size:12px; font-weight:700; color:#1a1814; line-height:1.2; }}
  .wt-pill-sub   {{ font-size:10.5px; color:#7a7368; margin-top:1px; }}
  .wt-decoration {{
    position:absolute; right:36px; top:50%; transform:translateY(-50%);
    width:180px; height:180px; opacity:0.045;
    font-size:160px; line-height:1;
    font-family:'Instrument Serif',serif;
    color:#ea580c; pointer-events:none; z-index:0;
    user-select:none;
  }}
</style>
<div class="wt-header">
  <div class="wt-decoration">⚡</div>
  <div class="wt-header-inner">
    <div class="wt-logo">
      <div class="wt-icon">⚡</div>
      <div>
        <div class="wt-title">Web <em>Tools</em></div>
        <div class="wt-subtitle">Site Cloner · Image Scraper · GMB Photos</div>
        <div style="margin-top:8px;"><span class="wt-badge">⊙ {BYPASS_METHOD}</span></div>
      </div>
    </div>
    <div class="wt-pills">
      <div class="wt-pill">
        <div class="wt-pill-icon" style="background:rgba(59,130,246,0.1);">🛡</div>
        <div class="wt-pill-text">
          <div class="wt-pill-label">Stealth Mode</div>
          <div class="wt-pill-sub">Bypass Cloudflare</div>
        </div>
      </div>
      <div class="wt-pill">
        <div class="wt-pill-icon" style="background:rgba(234,88,12,0.1);">⚡</div>
        <div class="wt-pill-text">
          <div class="wt-pill-label">Fast & Offline</div>
          <div class="wt-pill-sub">100% Local</div>
        </div>
      </div>
    </div>
  </div>
</div>
"""

FEATURES_HTML = """
<style>
  @keyframes cardIn {
    from { opacity:0; transform:translateY(20px); }
    to   { opacity:1; transform:translateY(0); }
  }
  .fcard { animation: cardIn 0.5s ease both; }
  .fcard:nth-child(1) { animation-delay:0.05s; }
  .fcard:nth-child(2) { animation-delay:0.12s; }
  .fcard:nth-child(3) { animation-delay:0.19s; }
  .fcard:nth-child(4) { animation-delay:0.26s; }
  .fcard:hover {
    transform: translateY(-4px) scale(1.01);
    box-shadow: 0 12px 36px rgba(0,0,0,0.09);
  }
  .fcard { transition: transform 0.25s cubic-bezier(0.4,0,0.2,1), box-shadow 0.25s; }
</style>
<div style="background:#fff;border:1.5px solid #e8e4de;border-radius:16px;padding:22px 24px;margin-bottom:14px;box-shadow:0 1px 4px rgba(0,0,0,0.04);">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;">
    <div>
      <div style="font-family:'Bricolage Grotesque',sans-serif;font-size:15px;font-weight:800;color:#1a1814;letter-spacing:-0.02em;">Clone any WordPress site — fully offline</div>
      <div style="font-family:'Bricolage Grotesque',sans-serif;font-size:12px;color:#7a7368;margin-top:3px;">All assets saved locally · Relative paths rewritten · ZIP ready</div>
    </div>
    <div style="background:#f0fdf4;border:1.5px solid #bbf7d0;color:#16a34a;font-size:10px;font-weight:800;padding:5px 12px;border-radius:7px;font-family:'Bricolage Grotesque',sans-serif;letter-spacing:0.06em;white-space:nowrap;">100% OFFLINE</div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;">
    <div class="fcard" style="background:#eff6ff;border:1.5px solid #bfdbfe;border-radius:12px;padding:16px;">
      <div style="width:36px;height:36px;background:#dbeafe;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:16px;margin-bottom:10px;">🛡</div>
      <div style="font-family:'Bricolage Grotesque',sans-serif;font-size:12.5px;font-weight:700;color:#1e3a5f;margin-bottom:5px;">curl_cffi</div>
      <div style="font-size:11px;color:#3b82f6;line-height:1.5;">Chrome TLS fingerprint bypasses Cloudflare</div>
    </div>
    <div class="fcard" style="background:#faf5ff;border:1.5px solid #e9d5ff;border-radius:12px;padding:16px;">
      <div style="width:36px;height:36px;background:#ede9fe;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:16px;margin-bottom:10px;">📦</div>
      <div style="font-family:'Bricolage Grotesque',sans-serif;font-size:12.5px;font-weight:700;color:#3b0764;margin-bottom:5px;">3 Image Sources</div>
      <div style="font-size:11px;color:#7c3aed;line-height:1.5;">WP REST API → XML Sitemap → HTML/JS regex</div>
    </div>
    <div class="fcard" style="background:#f0fdf4;border:1.5px solid #bbf7d0;border-radius:12px;padding:16px;">
      <div style="width:36px;height:36px;background:#dcfce7;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:16px;margin-bottom:10px;">⌨️</div>
      <div style="font-family:'Bricolage Grotesque',sans-serif;font-size:12.5px;font-weight:700;color:#14532d;margin-bottom:5px;">JS Files Scanned</div>
      <div style="font-size:11px;color:#16a34a;line-height:1.5;">Detects Elementor & slider hidden images</div>
    </div>
    <div class="fcard" style="background:#fff7ed;border:1.5px solid #fed7aa;border-radius:12px;padding:16px;">
      <div style="width:36px;height:36px;background:#ffedd5;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:16px;margin-bottom:10px;">📁</div>
      <div style="font-family:'Bricolage Grotesque',sans-serif;font-size:12.5px;font-weight:700;color:#7c2d12;margin-bottom:5px;">Organized Output</div>
      <div style="font-size:11px;color:#ea580c;line-height:1.5;">Each page gets its own folder with /images/</div>
    </div>
  </div>
</div>
"""

IMAGES_FEATURES_HTML = """
<style>
  @keyframes cardIn2 {
    from { opacity:0; transform:translateY(20px); }
    to   { opacity:1; transform:translateY(0); }
  }
  .fcard2 { animation: cardIn2 0.5s ease both; transition: transform 0.25s, box-shadow 0.25s; }
  .fcard2:nth-child(1) { animation-delay:0.05s; }
  .fcard2:nth-child(2) { animation-delay:0.12s; }
  .fcard2:nth-child(3) { animation-delay:0.19s; }
  .fcard2:hover { transform: translateY(-4px) scale(1.01); box-shadow: 0 12px 36px rgba(0,0,0,0.09); }
</style>
<div style="background:#fff;border:1.5px solid #e8e4de;border-radius:16px;padding:22px 24px;margin-bottom:14px;box-shadow:0 1px 4px rgba(0,0,0,0.04);">
  <div style="font-family:'Bricolage Grotesque',sans-serif;font-size:15px;font-weight:800;color:#1a1814;letter-spacing:-0.02em;margin-bottom:4px;">Download every image — maximum coverage</div>
  <div style="font-family:'Bricolage Grotesque',sans-serif;font-size:12px;color:#7a7368;margin-bottom:18px;">Combines 3 sources for near-perfect image discovery</div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;">
    <div class="fcard2" style="background:#eff6ff;border:1.5px solid #bfdbfe;border-radius:12px;padding:16px;">
      <div style="font-size:20px;margin-bottom:10px;">🗃</div>
      <div style="font-family:'Bricolage Grotesque',sans-serif;font-size:12.5px;font-weight:700;color:#1e3a5f;margin-bottom:5px;">WP REST API</div>
      <div style="font-size:11px;color:#3b82f6;line-height:1.5;">Queries all media directly from WordPress DB</div>
    </div>
    <div class="fcard2" style="background:#f0fdf4;border:1.5px solid #bbf7d0;border-radius:12px;padding:16px;">
      <div style="font-size:20px;margin-bottom:10px;">🗺</div>
      <div style="font-family:'Bricolage Grotesque',sans-serif;font-size:12.5px;font-weight:700;color:#14532d;margin-bottom:5px;">XML Sitemap</div>
      <div style="font-size:11px;color:#16a34a;line-height:1.5;">Extracts image:loc from sitemap.xml</div>
    </div>
    <div class="fcard2" style="background:#fff7ed;border:1.5px solid #fed7aa;border-radius:12px;padding:16px;">
      <div style="font-size:20px;margin-bottom:10px;">🔍</div>
      <div style="font-family:'Bricolage Grotesque',sans-serif;font-size:12.5px;font-weight:700;color:#7c2d12;margin-bottom:5px;">Full Page Crawl</div>
      <div style="font-size:11px;color:#ea580c;line-height:1.5;">HTML + JS regex scan across all pages</div>
    </div>
  </div>
</div>
"""

GMB_FEATURES_HTML = """
<div style="background:#fff;border:1.5px solid #e8e4de;border-radius:16px;padding:20px 24px;margin-bottom:14px;box-shadow:0 1px 4px rgba(0,0,0,0.04);animation:fadeUp 0.4s ease;">
  <div style="display:flex;align-items:flex-start;gap:14px;">
    <div style="width:42px;height:42px;background:#fff7ed;border-radius:11px;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;border:1.5px solid #fed7aa;">📍</div>
    <div>
      <div style="font-family:'Bricolage Grotesque',sans-serif;font-size:15px;font-weight:800;color:#1a1814;letter-spacing:-0.02em;margin-bottom:4px;">Google My Business photo downloader</div>
      <div style="font-size:12.5px;color:#7a7368;line-height:1.7;">Paste a Google Maps URL or Place ID. Preview photos in-browser, then download all as a high-res ZIP. <span style="color:#ea580c;font-weight:700;">Tip:</span> use the <code style="background:#fafaf8;border:1px solid #e8e4de;color:#ea580c;padding:1px 7px;border-radius:5px;font-family:'JetBrains Mono',monospace;font-size:11px;">/photos</code> page URL for best results.</div>
    </div>
  </div>
</div>
"""


# ══════════════════════════════════════════════════════
#  UI
# ══════════════════════════════════════════════════════
with gr.Blocks(title="⚡ Web Tools", css=CSS, theme=gr.themes.Base()) as demo:

    gr.HTML(HEADER_HTML)

    with gr.Tabs():

        # ── Tab 1: Full Clone ──────────────────────────
        with gr.TabItem("📦  Full Clone"):
            gr.HTML(FEATURES_HTML)
            t1_url = gr.Textbox(label="Website URL", placeholder="https://localgaragedoors.co")
            t1_btn = gr.Button("⬇  Clone & Download ZIP", variant="primary", size="lg")
            t1_zip = gr.File(label="Download ZIP")
            t1_log = gr.Textbox(label="Log", lines=20, interactive=False)
            t1_btn.click(fn=clone_website, inputs=[t1_url], outputs=[t1_zip, t1_log])

        # ── Tab 2: Images Only ─────────────────────────
        with gr.TabItem("🖼  Images Only"):
            gr.HTML(IMAGES_FEATURES_HTML)
            t2_url = gr.Textbox(label="Website URL", placeholder="https://localgaragedoors.co")
            t2_btn = gr.Button("⬇  Download All Images", variant="primary")
            t2_zip = gr.File(label="Download ZIP")
            t2_log = gr.Textbox(label="Log", lines=12, interactive=False)
            t2_btn.click(fn=download_website_images, inputs=[t2_url], outputs=[t2_zip, t2_log])

        # ── Tab 3: GMB Photos ──────────────────────────
        with gr.TabItem("📍  GMB Photos"):
            gr.HTML(GMB_FEATURES_HTML)
            t3_url   = gr.Textbox(label="Google Maps URL / Place ID", placeholder="https://www.google.com/maps/place/...")
            t3_btn   = gr.Button("🔍  Find Photos", variant="primary")
            t3_msg   = gr.Textbox(label="Status", interactive=False)
            t3_gal   = gr.Gallery(label="Preview", columns=4, height=420)
            t3_state = gr.Textbox(visible=False)
            t3_dl    = gr.Button("⬇  Download All as ZIP", variant="secondary", visible=False)
            t3_zip   = gr.File(label="Download ZIP")
            t3_log   = gr.Textbox(label="Log", lines=8, interactive=False)
            t3_btn.click(fn=find_gmb_photos,       inputs=[t3_url],   outputs=[t3_gal, t3_msg, t3_state])
            t3_dl.click( fn=download_selected_gmb, inputs=[t3_state], outputs=[t3_zip, t3_log])

if __name__ == "__main__":
    demo.launch()