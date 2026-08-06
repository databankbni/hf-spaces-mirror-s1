"""Download public-domain Bible translations into data/versions/.

Source: scrollmapper/bible_databases (public domain texts). Each entry maps a
local code -> (display name, language, source path under sources/). Add more
public-domain entries, re-run, then rebuild the index with build_index.py.

Also writes data/versions/manifest.json so the app knows each version's
language. Modern translations (NIV, ESV, NLT, NKJV, Amplified, GNT, ...) are
copyrighted and cannot be redistributed, so they are not included.
"""
import json
import sys
import urllib.request
from pathlib import Path

VERSIONS_DIR = Path(__file__).parent / "data" / "versions"
MANIFEST = VERSIONS_DIR / "manifest.json"
BASE = "https://raw.githubusercontent.com/scrollmapper/bible_databases/master/sources"

# local code -> {name, language, path (sources/<path>.json)}
VERSIONS = {
    "KJV": {"name": "King James Version", "language": "en", "path": "en/KJV/KJV"},
    "ASV": {"name": "American Standard Version", "language": "en", "path": "en/ASV/ASV"},
    "YLT": {"name": "Young's Literal Translation", "language": "en", "path": "en/YLT/YLT"},
    "BBE": {"name": "Bible in Basic English", "language": "en", "path": "en/BBE/BBE"},
    "SpaRV": {"name": "Reina-Valera (Español)", "language": "es", "path": "es/SpaRV/SpaRV"},
}


def download():
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    for code, meta in VERSIONS.items():
        dest = VERSIONS_DIR / f"{code}.json"
        if dest.exists():
            print(f"✓ {code} ({meta['name']}) already present")
            continue
        url = f"{BASE}/{meta['path']}.json"
        print(f"↓ {code} ({meta['name']}) ...", end=" ", flush=True)
        try:
            urllib.request.urlretrieve(url, dest)
            print(f"{dest.stat().st_size // 1024} KB")
        except Exception as e:  # noqa: BLE001
            print(f"FAILED: {e}", file=sys.stderr)

    manifest = {
        code: {"name": m["name"], "language": m["language"]}
        for code, m in VERSIONS.items()
        if (VERSIONS_DIR / f"{code}.json").exists()
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"Wrote manifest with {len(manifest)} versions")


if __name__ == "__main__":
    download()
