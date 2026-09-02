"""Task 4 — corpus fetcher for NurtureDE.

Reads data/sources.yaml, downloads each URL to data/raw/{id}.html, extracts
visible text, and writes a SHA-256 of that text back into sources.yaml
(comment-safe, in place). Designed for cheap incremental re-runs.

Design choices (see DAY1_LOG.md):
  - Dependency-free extraction via stdlib html.parser. Good enough for a stable
    content hash and a client-side-rendering ("suspicious") heuristic. Higher
    quality extraction is a Day-2 concern.
  - content_hash / last_verified_date are written back by targeted in-place line
    edits keyed on `id`, so the file's comments and formatting are preserved
    (pyyaml.dump would discard them).
  - robots.txt is re-checked here too; a disallowed URL is skipped, never fetched.

Usage:
  py src/fetch.py                     # process every source (skip cached)
  py src/fetch.py --only ID[,ID...]   # process just these ids (add new ones)
  py src/fetch.py --update ID[,ID...] # re-download + re-hash these ids
  py src/fetch.py --force             # re-download + re-hash everything
  py src/fetch.py --remove ID[,ID...] # delete raw+processed artifacts, clear hash
  py src/fetch.py --dry-run           # show what would happen, touch nothing
"""

import argparse
import hashlib
import os
import re
import sys
import time
from html.parser import HTMLParser
from urllib.robotparser import RobotFileParser
from urllib.parse import urlsplit
import urllib.request
import urllib.error

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_PATH = os.path.join(ROOT, "data", "sources.yaml")
RAW_DIR = os.path.join(ROOT, "data", "raw")
PROCESSED_DIR = os.path.join(ROOT, "data", "processed")

USER_AGENT = (
    "NurtureDE-Research/0.1 "
    "(personal portfolio research project; "
    "contact: shwetaswain13november@gmail.com)"
)

MIN_DELAY_SECONDS = 2.0
REQUEST_TIMEOUT = 25
# Below this many chars of visible text, a page is almost certainly a
# cookie-consent / SPA shell rather than real content -> flag for manual capture.
SUSPICIOUS_TEXT_CHARS = 600
TODAY = time.strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- #
# HTML -> visible text (stdlib only)
# --------------------------------------------------------------------------- #
class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._chunks = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._chunks.append(text)

    def text(self):
        return re.sub(r"\s+", " ", " ".join(self._chunks)).strip()


def extract_text(html):
    p = _TextExtractor()
    try:
        p.feed(html)
    except Exception:  # noqa: BLE001 — malformed HTML must not crash the run
        pass
    return p.text()


def decode_bytes(raw, content_type):
    """Decode HTML bytes using the charset from headers, then <meta>, else utf-8."""
    charset = None
    if content_type:
        m = re.search(r"charset=([\w-]+)", content_type, re.I)
        if m:
            charset = m.group(1)
    if not charset:
        head = raw[:2048].decode("ascii", "replace")
        m = re.search(r'charset=["\']?([\w-]+)', head, re.I)
        if m:
            charset = m.group(1)
    for enc in [charset, "utf-8", "latin-1"]:
        if not enc:
            continue
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# robots.txt (cached per domain)
# --------------------------------------------------------------------------- #
_robots_cache = {}


def _http_get(url, timeout=REQUEST_TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)


def robots_for(domain):
    if domain in _robots_cache:
        return _robots_cache[domain]
    rp = RobotFileParser()
    try:
        txt = _http_get("https://%s/robots.txt" % domain).read().decode("utf-8", "replace")
        rp.parse(txt.splitlines())
    except Exception:  # noqa: BLE001 — no robots => default allow
        rp = None
    _robots_cache[domain] = rp
    return rp


def robots_allows(url):
    domain = urlsplit(url).netloc
    rp = robots_for(domain)
    if rp is None:
        return True, None
    allowed = rp.can_fetch(USER_AGENT, url)
    delay = None
    try:
        delay = rp.crawl_delay(USER_AGENT)
    except Exception:  # noqa: BLE001
        delay = None
    return allowed, delay


# --------------------------------------------------------------------------- #
# Comment-safe writeback of scalar fields, keyed by `id`
# --------------------------------------------------------------------------- #
_ID_RE = re.compile(r"^\s*-\s+id:\s+(\S+)\s*$")


def _yaml_scalar(value):
    if value is None:
        return "null"
    # Quote strings so hex hashes / dates are never misread as numbers.
    return '"%s"' % value


def set_fields_for_id(lines, sid, updates):
    """In `lines`, within the block for `- id: sid`, set each field in
    `updates` (dict field->value). Returns True if any line changed."""
    start = None
    for i, ln in enumerate(lines):
        m = _ID_RE.match(ln)
        if m and m.group(1) == sid:
            start = i
            break
    if start is None:
        return False
    # Block ends at the next `- id:` line (or EOF).
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if _ID_RE.match(lines[j]):
            end = j
            break
    changed = False
    for field, value in updates.items():
        pat = re.compile(r"^(\s*)%s:\s.*$" % re.escape(field))
        for k in range(start, end):
            m = pat.match(lines[k])
            if m:
                new_line = "%s%s: %s" % (m.group(1), field, _yaml_scalar(value))
                if lines[k].rstrip("\n") != new_line:
                    lines[k] = new_line + "\n"
                    changed = True
                break
    return changed


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def load_sources():
    with open(SOURCES_PATH, encoding="utf-8") as f:
        raw_lines = f.readlines()
    data = yaml.safe_load("".join(raw_lines))
    return data["sources"], raw_lines


def save_lines(raw_lines):
    tmp = SOURCES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.writelines(raw_lines)
    os.replace(tmp, SOURCES_PATH)


def parse_args():
    ap = argparse.ArgumentParser(description="NurtureDE corpus fetcher")
    ap.add_argument("--only", help="comma-separated ids to process (add/refresh)")
    ap.add_argument("--update", help="comma-separated ids to force re-download")
    ap.add_argument("--remove", help="comma-separated ids to delete artifacts for")
    ap.add_argument("--force", action="store_true", help="re-download everything")
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    return ap.parse_args()


def _csv(s):
    return {x.strip() for x in s.split(",") if x.strip()} if s else set()


def do_remove(sources, raw_lines, ids, dry):
    by_id = {s["id"]: s for s in sources}
    for sid in ids:
        if sid not in by_id:
            print("  [remove] unknown id: %s" % sid)
            continue
        for path in (os.path.join(RAW_DIR, sid + ".html"),
                     os.path.join(PROCESSED_DIR, sid + ".txt")):
            if os.path.exists(path):
                print("  [remove] %s %s" % ("would delete" if dry else "deleted", path))
                if not dry:
                    os.remove(path)
        if not dry:
            set_fields_for_id(raw_lines, sid, {"content_hash": None, "last_verified_date": None})
    if not dry:
        save_lines(raw_lines)


def main():
    args = parse_args()
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    sources, raw_lines = load_sources()

    if args.remove:
        do_remove(sources, raw_lines, _csv(args.remove), args.dry_run)
        return 0

    only = _csv(args.only)
    update = _csv(args.update)
    selected = [s for s in sources if (not only or s["id"] in only)]

    counts = {"fetched": 0, "skipped": 0, "failed": 0, "suspicious": 0, "changed": 0}
    suspicious_ids, failed_ids = [], []
    did_network = False

    print("=" * 72)
    print("NurtureDE fetch — %d source(s) selected%s" %
          (len(selected), " [DRY RUN]" if args.dry_run else ""))
    print("=" * 72)

    for s in selected:
        sid, url = s["id"], s["url"]
        raw_path = os.path.join(RAW_DIR, sid + ".html")
        force = args.force or (sid in update)
        have_file = os.path.exists(raw_path)
        have_hash = bool(s.get("content_hash"))

        # 1) Cheap skip: file present, hash present, not forced.
        if have_file and have_hash and not force:
            print("  [skip]  %s (cached, hash present)" % sid)
            counts["skipped"] += 1
            continue

        # 2) File present, hash missing, not forced -> hash from disk, no network.
        if have_file and not force:
            try:
                with open(raw_path, "rb") as f:
                    raw = f.read()
                text = extract_text(decode_bytes(raw, None))
                new_hash = sha256_text(text)
                susp = len(text) < SUSPICIOUS_TEXT_CHARS
                print("  [hash]  %s (from cached file, %d chars)%s" %
                      (sid, len(text), "  <-- SUSPICIOUS" if susp else ""))
                if susp:
                    counts["suspicious"] += 1
                    suspicious_ids.append(sid)
                if not args.dry_run:
                    if set_fields_for_id(raw_lines, sid,
                                         {"content_hash": new_hash, "last_verified_date": TODAY}):
                        counts["changed"] += 1
                counts["skipped"] += 1
            except Exception as e:  # noqa: BLE001
                print("  [FAIL]  %s hashing cached file: %s" % (sid, e))
                counts["failed"] += 1
                failed_ids.append(sid)
            continue

        # 3) Need to download. Respect robots + polite delay.
        allowed, crawl_delay = robots_allows(url)
        if not allowed:
            print("  [SKIP]  %s DISALLOWED by robots.txt -> not fetched: %s" % (sid, url))
            counts["skipped"] += 1
            continue

        if args.dry_run:
            print("  [would fetch] %s -> %s" % (sid, url))
            counts["fetched"] += 1
            continue

        if did_network:
            time.sleep(max(MIN_DELAY_SECONDS, crawl_delay or 0))
        did_network = True

        try:
            resp = _http_get(url)
            raw = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            with open(raw_path, "wb") as f:
                f.write(raw)
            html = decode_bytes(raw, ctype)
            text = extract_text(html)
            new_hash = sha256_text(text)
            susp = len(text) < SUSPICIOUS_TEXT_CHARS

            old_hash = s.get("content_hash")
            content_changed = (old_hash != new_hash)

            # Write processed text only when content is new/changed (supports
            # "unchanged hash -> skip reprocessing" downstream).
            if content_changed:
                with open(os.path.join(PROCESSED_DIR, sid + ".txt"), "w",
                          encoding="utf-8") as f:
                    f.write(text)

            set_fields_for_id(raw_lines, sid,
                              {"content_hash": new_hash, "last_verified_date": TODAY})

            flag = "  <-- SUSPICIOUS (likely SPA/consent shell; capture manually)" if susp else ""
            state = "new/changed" if content_changed else "unchanged"
            print("  [ok]    %s  %d bytes, %d text chars, %s%s" %
                  (sid, len(raw), len(text), state, flag))
            counts["fetched"] += 1
            if content_changed:
                counts["changed"] += 1
            if susp:
                counts["suspicious"] += 1
                suspicious_ids.append(sid)
        except urllib.error.HTTPError as e:
            print("  [FAIL]  %s HTTP %s: %s" % (sid, e.code, url))
            counts["failed"] += 1
            failed_ids.append(sid)
        except Exception as e:  # noqa: BLE001 — one bad URL must not kill the run
            print("  [FAIL]  %s %s: %s" % (sid, type(e).__name__, e))
            counts["failed"] += 1
            failed_ids.append(sid)

    if not args.dry_run:
        save_lines(raw_lines)

    print("\n" + "=" * 72)
    print("SUMMARY: fetched=%(fetched)d  skipped=%(skipped)d  failed=%(failed)d  "
          "suspicious=%(suspicious)d  hash-changed=%(changed)d" % counts)
    if suspicious_ids:
        print("  suspicious (manual capture needed): %s" % ", ".join(suspicious_ids))
    if failed_ids:
        print("  failed: %s" % ", ".join(failed_ids))
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
