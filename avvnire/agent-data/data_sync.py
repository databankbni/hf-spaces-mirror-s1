#!/usr/bin/env python3
"""Enhanced data persistence: full backup/restore with integrity check."""
import os, json, time, threading, sqlite3, ssl, urllib.request, hashlib

HERMES_HOME = os.environ.get("HERMES_HOME", "/opt/data")
REPO_ID = "avvnire/agent-data"

# ── 全量同步文件清单 ──────────────────────────────────────────
# (repo_path, local_path, critical)
SYNC_FILES = [
    # 动态数据 (频繁变更)
    ("data/chat_sessions.db",       os.path.join(HERMES_HOME, "chat_sessions.db"),       True),
    ("data/authorized_openids.txt",  os.path.join(HERMES_HOME, "authorized_openids.txt"), True),
    ("data/known_good_commit.txt",   os.path.join(HERMES_HOME, "known_good_commit.txt"),  False),
    # 配置文件 (偶尔变更)
    ("soul.json",    "/app/soul.json",    False),
    ("profile.json", "/app/profile.json", False),
    ("config.yaml",  "/app/config.yaml",  False),
    # 前端应用 (版本更新时变更)
    ("ziwei.html",          "/app/ziwei.html",          False),
    ("service-worker.js",   "/app/service-worker.js",   False),
    ("app.js",              "/app/app.js",              False),
    ("template.html",       "/app/template.html",       False),
    # 资源文件
    ("assets/cover.jpg",    "/app/assets/cover.jpg",    False),
    ("assets/qr.png",       "/app/assets/qr.png",       False),
]

_sync_lock = threading.Lock()
_last_sync = 0

def _hf_api():
    from huggingface_hub import HfApi
    os.environ.setdefault("HF_ENDPOINT", "https://huggingface.co")
    return HfApi(token=os.environ.get("HF_TOKEN", ""))

def _file_hash(path):
    """SHA256 of a file for integrity check."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except:
        return None

def download_data():
    """On startup: download ALL dynamic data from repo."""
    api = _hf_api()
    restored = []
    for repo_path, local_path, critical in SYNC_FILES:
        try:
            # Skip if local file exists and is non-empty for non-critical
            if os.path.exists(local_path) and os.path.getsize(local_path) > 0 and not critical:
                continue
            # Download to a temp dir first
            tmp_dir = "/tmp/hf_restore"
            os.makedirs(tmp_dir, exist_ok=True)
            api.hf_hub_download(
                repo_id=REPO_ID, filename=repo_path,
                repo_type="space",
                token=os.environ.get("HF_TOKEN", ""),
                local_dir=tmp_dir,
            )
            # Move to correct location
            import shutil
            tmp_file = os.path.join(tmp_dir, repo_path)
            if os.path.exists(tmp_file):
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                shutil.copy2(tmp_file, local_path)
                restored.append(repo_path)
                print(f"[SYNC] Restored {repo_path} -> {local_path}")
        except Exception as e:
            if critical:
                print(f"[SYNC] CRITICAL restore fail {repo_path}: {e}")
            # Non-critical: silent
    # Write manifest of restored files
    manifest = {"restored": restored, "time": time.time(), "hashes": {}}
    for _, local_path, _ in SYNC_FILES:
        if os.path.exists(local_path):
            manifest["hashes"][os.path.basename(local_path)] = _file_hash(local_path)
    manifest_path = os.path.join(HERMES_HOME, ".sync_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"[SYNC] Restore complete: {len(restored)} files")
    return restored

def upload_data(files_only=None):
    """Upload dynamic data to repo. If files_only given, only sync those."""
    global _last_sync
    api = _hf_api()
    uploaded = []
    for repo_path, local_path, critical in SYNC_FILES:
        if files_only and repo_path not in files_only and local_path not in files_only:
            continue
        if not os.path.exists(local_path):
            continue
        try:
            api.upload_file(
                path_or_fileobj=local_path,
                path_in_repo=repo_path,
                repo_id=REPO_ID, repo_type="space",
            )
            uploaded.append(repo_path)
        except Exception as e:
            print(f"[SYNC] Upload fail {repo_path}: {e}")
    _last_sync = time.time()
    if uploaded:
        print(f"[SYNC] Uploaded {len(uploaded)} files: {', '.join(uploaded[:5])}")
    return uploaded

def immediate_sync(local_path=None):
    """Call after critical DB writes. Syncs immediately in background."""
    def _do():
        with _sync_lock:
            # Always sync DB + the specified file
            files = ["data/chat_sessions.db"]
            if local_path:
                for repo_p, local_p, _ in SYNC_FILES:
                    if local_p == local_path or local_path.endswith(os.path.basename(local_p)):
                        files.append(repo_p)
                        break
            upload_data(files_only=files)
    t = threading.Thread(target=_do, daemon=True, name="immediate_sync")
    t.start()

def backup_snapshot():
    """Create a full backup snapshot in repo (all files)."""
    print("[SYNC] Starting full backup snapshot...")
    uploaded = upload_data()
    # Update known_good_commit
    commit_file = os.path.join(HERMES_HOME, "known_good_commit.txt")
    try:
        from huggingface_hub import HfApi
        api = HfApi(token=os.environ.get("HF_TOKEN", ""))
        info = api.repo_info(repo_id=REPO_ID, repo_type="space")
        sha = info.sha[:12]
        with open(commit_file, "w") as f:
            f.write(sha + "\n")
        api.upload_file(
            path_or_fileobj=commit_file,
            path_in_repo="data/known_good_commit.txt",
            repo_id=REPO_ID, repo_type="space",
        )
        print(f"[SYNC] Backup snapshot complete. Commit: {sha}")
    except Exception as e:
        print(f"[SYNC] Backup snapshot error: {e}")
    return uploaded

def _sync_loop():
    """Background sync every 3 minutes (reduced from 5 for less data loss)."""
    while True:
        time.sleep(180)
        try:
            upload_data()
        except Exception as e:
            print(f"[SYNC] Loop error: {e}")

def _backup_loop():
    """Full backup every 30 minutes."""
    while True:
        time.sleep(1800)
        try:
            backup_snapshot()
        except Exception as e:
            print(f"[SYNC] Backup loop error: {e}")

def start_sync():
    """Start background sync: download first, then periodic upload + backup."""
    download_data()
    t1 = threading.Thread(target=_sync_loop, daemon=True, name="data_sync")
    t1.start()
    t2 = threading.Thread(target=_backup_loop, daemon=True, name="data_backup")
    t2.start()
    print("[SYNC] Data sync started (3min upload + 30min backup)")

def verify_integrity():
    """Check if all critical files exist and are non-empty."""
    issues = []
    for repo_path, local_path, critical in SYNC_FILES:
        if critical:
            if not os.path.exists(local_path):
                issues.append(f"MISSING: {local_path}")
            elif os.path.getsize(local_path) == 0:
                issues.append(f"EMPTY: {local_path}")
    return issues
