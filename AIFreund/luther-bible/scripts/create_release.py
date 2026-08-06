"""
scripts/create_release.py — Create a GitHub release and upload the ChromaDB.

What it does:
  1. Compresses bible_chroma_db/ → bible_chroma_db.tar.gz
  2. Creates a GitHub release tagged v{VERSION}
  3. Uploads the archive as a release asset

Requirements:
  - GITHUB_TOKEN env var: a Personal Access Token with repo scope
    Create one at: https://github.com/settings/tokens/new
    Required scopes: Contents (read + write) — that's it.

Usage:
  set GITHUB_TOKEN=ghp_...
  python scripts/create_release.py

The script is idempotent: if the release already exists it skips creation
and goes straight to uploading the asset.
"""

import json
import os
import sys
import tarfile
import urllib.request
import urllib.error
from pathlib import Path

# Allow running as a script without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from luther_mcp import __version__

OWNER = "happyherp"
REPO = "luther-mcp"
VERSION = f"v{__version__}"
ASSET_NAME = "bible_chroma_db.tar.gz"

API_BASE = f"https://api.github.com/repos/{OWNER}/{REPO}"
UPLOAD_BASE = f"https://uploads.github.com/repos/{OWNER}/{REPO}"

# Resolve paths relative to the repo root (one level up from scripts/)
REPO_ROOT = Path(__file__).parent.parent
CHROMA_DIR = REPO_ROOT / "bible_chroma_db"
ARCHIVE_PATH = REPO_ROOT / ASSET_NAME


def github_request(url: str, method: str = "GET", data=None, token: str = "") -> dict:
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"GitHub API error {e.code}: {body}", file=sys.stderr)
        raise


def compress(source_dir: Path, dest: Path) -> None:
    print(f"Compressing {source_dir} → {dest.name} ...")
    total = sum(1 for _ in source_dir.rglob("*") if _.is_file())
    done = 0
    with tarfile.open(dest, "w:gz") as tar:
        for path in source_dir.rglob("*"):
            tar.add(path, arcname=Path("bible_chroma_db") / path.relative_to(source_dir))
            if path.is_file():
                done += 1
                print(f"\r  {done}/{total} files", end="", flush=True)
    size_mb = dest.stat().st_size / 1_048_576
    print(f"\r  Done. Archive size: {size_mb:.0f} MB")


def get_or_create_release(token: str) -> tuple[int, str]:
    """Returns (release_id, upload_url). Creates release if it doesn't exist."""
    # Check if release already exists
    try:
        rel = github_request(f"{API_BASE}/releases/tags/{VERSION}", token=token)
        print(f"Release {VERSION} already exists (id={rel['id']}). Skipping creation.")
        return rel["id"], rel["upload_url"].split("{")[0]
    except urllib.error.HTTPError:
        pass

    print(f"Creating release {VERSION} ...")
    rel = github_request(
        f"{API_BASE}/releases",
        method="POST",
        data={
            "tag_name": VERSION,
            "name": f"{VERSION} — pre-built ChromaDB",
            "body": (
                "Pre-built ChromaDB vector index for all three translations "
                "(GerBoLut, KJV, NHEB). ~93,000 verses, intfloat/multilingual-e5-small embeddings.\n\n"
                "Download automatically with:\n"
                "```\npython -m luther_mcp download\n```"
            ),
            "draft": False,
            "prerelease": False,
        },
        token=token,
    )
    print(f"Release created: {rel['html_url']}")
    return rel["id"], rel["upload_url"].split("{")[0]


def upload_asset(release_id: int, upload_url: str, archive: Path, token: str) -> None:
    import http.client
    import ssl
    from urllib.parse import urlparse

    size = archive.stat().st_size
    size_mb = size / 1_048_576
    print(f"Uploading {archive.name} ({size_mb:.0f} MB) ...")
    print("  This may take several minutes depending on your connection.")

    # Stream the file rather than loading it all into memory — a 300+ MB body
    # sent via urllib.read_bytes() causes an SSL EOF on GitHub's side.
    parsed = urlparse(f"{upload_url}?name={ASSET_NAME}")
    conn = http.client.HTTPSConnection(
        parsed.netloc,
        context=ssl.create_default_context(),
        timeout=600,
    )
    with open(archive, "rb") as f:
        conn.request(
            "POST",
            parsed.path + "?" + parsed.query,
            body=f,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
                "Content-Length": str(size),
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response = conn.getresponse()
        asset = json.loads(response.read())
    print(f"Upload complete: {asset['browser_download_url']}")


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print(
            "Error: GITHUB_TOKEN not set.\n"
            "Create a token at https://github.com/settings/tokens/new\n"
            "Required scope: Contents (read + write)",
            file=sys.stderr,
        )
        sys.exit(1)

    if not CHROMA_DIR.exists():
        print(f"Error: {CHROMA_DIR} not found. Run the indexer first.", file=sys.stderr)
        sys.exit(1)

    # Step 1: compress
    if ARCHIVE_PATH.exists():
        print(f"{ASSET_NAME} already exists, skipping compression. Delete it to recompress.")
    else:
        compress(CHROMA_DIR, ARCHIVE_PATH)

    # Step 2: create release
    release_id, upload_url = get_or_create_release(token)

    # Step 3: delete any existing asset (e.g. from a failed previous upload)
    assets = github_request(f"{API_BASE}/releases/{release_id}/assets", token=token)
    for asset in assets:
        if asset["name"] == ASSET_NAME:
            print(f"Deleting existing asset (id={asset['id']}) before re-upload ...")
            github_request(f"{API_BASE}/releases/assets/{asset['id']}", method="DELETE", token=token)

    # Step 4: upload
    upload_asset(release_id, upload_url, ARCHIVE_PATH, token)

    # Clean up archive
    ARCHIVE_PATH.unlink()
    print("Archive deleted locally. All done.")
    print(f"\nUsers can now run: python -m luther_mcp download")


if __name__ == "__main__":
    main()
