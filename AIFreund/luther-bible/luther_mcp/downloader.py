"""
downloader.py — Downloads pre-built ChromaDB from GitHub Releases.

Usage:
    python -m luther_mcp download [--force]
"""

import json
import os
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

OWNER = "happyherp"
REPO = "luther-mcp"
ASSET_NAME = "bible_chroma_db.tar.gz"


def get_download_url() -> str:
    """Resolve the asset URL from the latest GitHub release."""
    api_url = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"
    req = urllib.request.Request(
        api_url,
        headers={"Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req) as resp:
        release = json.loads(resp.read())
    for asset in release.get("assets", []):
        if asset["name"] == ASSET_NAME:
            return asset["browser_download_url"]
    raise RuntimeError(
        f"{ASSET_NAME} not found in latest release ({release.get('tag_name', '?')}). "
        "Has the release been published? Run: python scripts/create_release.py"
    )


def main():
    force = "--force" in sys.argv

    chroma_path = os.environ.get("CHROMA_PATH", "./bible_chroma_db")
    dest = Path(chroma_path)

    if dest.exists():
        if not force:
            print(f"ChromaDB already exists at {dest.resolve()}.")
            print("Use --force to overwrite.")
            return
        print(f"Removing existing ChromaDB at {dest.resolve()} ...")
        shutil.rmtree(dest)

    archive = dest.parent / ASSET_NAME

    print("Resolving latest release ...")
    try:
        url = get_download_url()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Downloading pre-built ChromaDB (~700 MB) ...")
    print(f"Source: {url}")

    def _progress(count, block_size, total_size):
        if total_size > 0:
            pct = min(count * block_size * 100 // total_size, 100)
            mb_done = count * block_size / 1_048_576
            mb_total = total_size / 1_048_576
            print(f"\r  {pct}%  ({mb_done:.0f} / {mb_total:.0f} MB)", end="", flush=True)

    try:
        urllib.request.urlretrieve(url, archive, reporthook=_progress)
    except Exception as e:
        print(f"\nDownload failed: {e}", file=sys.stderr)
        if archive.exists():
            archive.unlink()
        sys.exit(1)

    print(f"\nExtracting to {dest.parent.resolve()} ...")
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(dest.parent)
    except Exception as e:
        print(f"Extraction failed: {e}", file=sys.stderr)
        archive.unlink()
        sys.exit(1)

    archive.unlink()
    print(f"Done. ChromaDB is at: {dest.resolve()}")
    print("You can now start the server: python -m luther_mcp")
