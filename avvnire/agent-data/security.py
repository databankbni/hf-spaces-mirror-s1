#!/usr/bin/env python3
"""Security module: rate limiting, anti-crawling, security headers."""
import time, threading, hashlib, os, re
from collections import defaultdict, deque

# ── Rate Limiting ─────────────────────────────────────────────
# IP -> deque of timestamps
_rate_buckets = defaultdict(deque)
_rate_lock = threading.Lock()

# Limits: (max_requests, window_seconds)
RATE_LIMITS = {
    "/api/agent/shell/exec":      (10, 60),   # 10/min
    "/api/agent/search":           (20, 60),   # 20/min
    "/api/space/rebuild":          (3, 300),   # 3/5min
    "/api/space/restart":          (3, 300),   # 3/5min
    "/api/history/clear":          (5, 300),   # 5/5min
    "_default":                    (60, 60),   # 60/min default
}

def _get_client_ip(handler):
    """Extract client IP from handler."""
    # Check X-Forwarded-For (HF proxy)
    fwd = handler.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return handler.client_address[0] if handler.client_address else "unknown"

def check_rate_limit(handler, path):
    """Returns (allowed, retry_after_seconds)."""
    ip = _get_client_ip(handler)
    limit_config = RATE_LIMITS.get(path, RATE_LIMITS["_default"])
    max_req, window = limit_config
    
    now = time.time()
    key = f"{ip}:{path}"
    
    with _rate_lock:
        bucket = _rate_buckets[key]
        # Remove old entries
        while bucket and bucket[0] < now - window:
            bucket.popleft()
        
        if len(bucket) >= max_req:
            retry = int(window - (now - bucket[0]))
            return False, max(retry, 1)
        
        bucket.append(now)
    
    return True, 0

# ── Anti-Crawling ─────────────────────────────────────────────
BAD_UA_PATTERNS = [
    r"bot", r"crawler", r"spider", r"scraper", r"curl", r"wget",
    r"python-requests", r"httpclient", r"java/", r"okhttp",
    r"go-http-client", r"php/curl", r"scrapy", r"mechanize",
    r"headless", r"phantomjs", r"selenium", r"puppeteer",
]

_bad_ua_re = re.compile("|".join(BAD_UA_PATTERNS), re.IGNORECASE)

def is_crawler(user_agent):
    """Check if User-Agent looks like a crawler."""
    if not user_agent:
        return True  # No UA = block
    return bool(_bad_ua_re.search(user_agent))

def check_anti_crawl(handler, path):
    """Returns (allowed, reason)."""
    # API endpoints: stricter check
    if path.startswith("/api/"):
        ua = handler.headers.get("User-Agent", "")
        if is_crawler(ua):
            return False, "Bot UA detected on API endpoint"
    
    # HTML pages: allow search engines to index but block scrapers
    # (Don't block Googlebot/Bingbot on public pages)
    return True, ""

# ── Security Headers ──────────────────────────────────────────
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}

def add_security_headers(handler):
    """Add security headers to response. Call before end_headers."""
    for k, v in SECURITY_HEADERS.items():
        handler.send_header(k, v)

# ── Shell Command Hardening ───────────────────────────────────
# Strict whitelist: only safe read-only commands
SHELL_WHITELIST_STRICT = [
    "ls", "cat", "head", "tail", "grep", "find", "wc",
    "stat", "file", "du", "df", "free", "uptime",
    "ps", "whoami", "date", "echo", "env",
    "python3 -c", "python3 --version",
    "git log", "git status", "git show",
    "pip list", "pip show",
]

def is_shell_safe(cmd):
    """Strict shell command validation."""
    cmd_stripped = cmd.strip()
    if not cmd_stripped:
        return False
    
    # Block dangerous patterns
    danger_patterns = [
        r"rm\s+-rf", r"mkfs", r"dd\s+if=", r">\s*/dev/",
        r"\bsudo\b", r"\bsu\b", r"chmod\s+777", r"chown",
        r"nc\s+-", r"bash\s+-i", r"sh\s+-c",
        r"eval\s", r"exec\s", r"subprocess",
        r"__import__", r"open\s*\(\s*['\"]/",
        r"wget\s+http", r"curl\s+.*\|\s*sh",
        r"base64\s+-d\s.*\|", r"pip\s+install",
        r"apt\s+install", r"yum\s+install",
    ]
    for pat in danger_patterns:
        if re.search(pat, cmd_stripped, re.IGNORECASE):
            return False
    
    # Check against whitelist (prefix match)
    for allowed in SHELL_WHITELIST_STRICT:
        if cmd_stripped.startswith(allowed):
            return True
    
    # Allow base64 decode for file writes (our own upload mechanism)
    if "base64 -d" in cmd_stripped and "python3 -c" in cmd_stripped:
        return True
    
    return False

# ── Request Logging ───────────────────────────────────────────
_request_log = deque(maxlen=200)

def log_request(ip, method, path, status, ua=""):
    """Log request for audit."""
    _request_log.append({
        "time": time.time(),
        "ip": ip,
        "method": method,
        "path": path[:100],
        "status": status,
        "ua": ua[:80],
    })

def get_recent_requests(limit=50):
    """Get recent requests for admin panel."""
    return list(_request_log)[-limit:]

# ── Robots.txt ────────────────────────────────────────────────
ROBOTS_TXT = """User-agent: *
Disallow: /api/
Allow: /$
Allow: /ziwei.html
Crawl-delay: 10

User-agent: *
Disallow: /admin
Disallow: /api/agent/
Disallow: /api/space/
"""

def get_robots_txt():
    return ROBOTS_TXT
