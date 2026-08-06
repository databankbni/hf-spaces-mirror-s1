import os
import shutil
import uuid
import string
import random
import zipfile
import io
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Form, Query
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
import aiofiles
from apscheduler.schedulers.background import BackgroundScheduler

# ------------------- Configuration -------------------
BASE_DIR = Path("/tmp/file_sharer")
UPLOAD_DIR = BASE_DIR / "uploads"
CHUNK_DIR = BASE_DIR / "chunks"
SQLITE_DB = BASE_DIR / "database.db"

BASE_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)
CHUNK_DIR.mkdir(exist_ok=True)

CHUNK_SIZE = 5 * 1024 * 1024          # 5 MB per chunk
MAX_FILE_SIZE = 50 * 1024 * 1024 * 1024  # 50 GB per file

# ------------------- Database (SQLite) -------------------
import sqlite3

def init_db():
    conn = sqlite3.connect(str(SQLITE_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS uploads (
            id TEXT PRIMARY KEY,
            short_code TEXT UNIQUE,
            delete_token TEXT UNIQUE,
            total_size INTEGER DEFAULT 0,
            file_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP DEFAULT (datetime('now', '+7 days')),
            is_complete INTEGER DEFAULT 0,
            is_deleted INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_id TEXT,
            original_name TEXT,
            stored_name TEXT,
            size INTEGER,
            FOREIGN KEY(upload_id) REFERENCES uploads(id)
        )
    """)
    conn.commit()
    conn.close()

def get_conn():
    conn = sqlite3.connect(str(SQLITE_DB))
    conn.row_factory = sqlite3.Row
    return conn

def generate_short_code(length=6):
    chars = string.ascii_lowercase + string.digits
    while True:
        code = ''.join(random.choices(chars, k=length))
        if not get_conn().execute("SELECT 1 FROM uploads WHERE short_code=?", (code,)).fetchone():
            return code

# ------------------- Helper functions -------------------
async def cleanup_expired():
    conn = get_conn()
    expired = conn.execute(
        "SELECT id FROM uploads WHERE expires_at < datetime('now') AND is_deleted=0"
    ).fetchall()
    for row in expired:
        await delete_upload(row['id'], conn=conn, manual=False)
    conn.close()

async def delete_upload(upload_id: str, conn=None, manual: bool = True):
    if conn is None:
        conn = get_conn()
        own_conn = True
    else:
        own_conn = False
    try:
        upload_path = UPLOAD_DIR / upload_id
        chunk_path = CHUNK_DIR / upload_id
        for path in (upload_path, chunk_path):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        conn.execute("UPDATE uploads SET is_deleted=1 WHERE id=?", (upload_id,))
        conn.execute("DELETE FROM files WHERE upload_id=?", (upload_id,))
        conn.commit()
    finally:
        if own_conn:
            conn.close()

# ------------------- FastAPI with lifespan -------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(cleanup_expired, 'interval', hours=1)
    scheduler.start()
    app.state.scheduler = scheduler
    yield
    scheduler.shutdown()

app = FastAPI(title="Free File Sharing", lifespan=lifespan)

# ------------------- Beautiful error page -------------------
def error_html(message: str, status_code: int = 404) -> str:
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Error {status_code}</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                margin: 0;
                padding: 20px;
            }}
            .error-card {{
                background: white;
                border-radius: 20px;
                padding: 40px;
                text-align: center;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                max-width: 400px;
            }}
            h1 {{
                font-size: 5em;
                color: #ff5252;
                margin: 0;
            }}
            p {{
                color: #555;
                font-size: 1.1em;
                margin: 20px 0;
            }}
            a {{
                color: #667eea;
                text-decoration: none;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <div class="error-card">
            <h1>{status_code}</h1>
            <p>{message}</p>
            <a href="/">← Back to main page</a>
        </div>
    </body>
    </html>
    """

# ------------------- Main upload page -------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Free File Sharing</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    min-height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 20px;
  }
  .container { width: 100%; max-width: 560px; }
  .card {
    background: white;
    border-radius: 20px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.3);
    padding: 40px 30px;
  }
  h1 { text-align: center; color: #333; margin-bottom: 15px; font-size: 2em; }
  .logo {
    margin: 0 auto 20px;
    width: 80px; height: 80px;
    background: linear-gradient(135deg, #667eea, #764ba2);
    border-radius: 20px;
    display: flex; align-items: center; justify-content: center;
    font-size: 2.5em; color: white;
    box-shadow: 0 5px 15px rgba(0,0,0,0.2);
  }
  .drop-zone {
    border: 2px dashed #ccc; border-radius: 15px; padding: 30px;
    text-align: center; background: #f9f9ff; margin: 25px 0;
    transition: all 0.3s; cursor: pointer;
  }
  .drop-zone.dragover { border-color: #667eea; background: #eef0ff; transform: scale(1.02); }
  .drop-zone p { color: #555; font-size: 0.95em; }
  .drop-zone label { color: #667eea; font-weight: bold; text-decoration: underline; cursor: pointer; }
  .progress-container { margin: 20px 0; }
  .progress-bar-wrapper { background: #e0e0e0; border-radius: 20px; overflow: hidden; height: 25px; margin: 10px 0; }
  .progress-fill { width: 0%; height: 100%; background: linear-gradient(90deg, #667eea, #764ba2); border-radius: 20px; transition: width 0.2s; }
  .progress-text { display: flex; justify-content: space-between; font-size: 0.9em; color: #555; margin-bottom: 5px; }
  .time-remaining { text-align: center; font-size: 0.9em; color: #555; }
  .btn {
    display: inline-block; padding: 12px 25px; border: none; border-radius: 30px;
    font-weight: bold; cursor: pointer; transition: all 0.2s; background: #f0f0f0; color: #333;
  }
  .btn-primary { background: linear-gradient(135deg, #667eea, #764ba2); color: white; box-shadow: 0 4px 10px rgba(102,126,234,0.4); }
  .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 6px 15px rgba(102,126,234,0.6); }
  .btn-danger { background: #ff5252; color: white; }
  .btn-danger:hover { background: #ff1744; }
  .result-box { background: #f0fff0; border-radius: 15px; padding: 20px; margin: 20px 0; border: 1px solid #b8e6b8; text-align: center; }
  .share-link {
    display: flex; align-items: center; justify-content: space-between;
    background: white; border-radius: 30px; padding: 8px 20px; margin: 10px 0; border: 1px solid #ccc;
  }
  .share-link a { color: #333; text-decoration: none; font-weight: 500; word-break: break-all; }
  .copy-btn { background: none; border: none; color: #667eea; cursor: pointer; font-size: 1.2em; margin-left: 10px; }
  .copy-btn:hover { color: #764ba2; }
  .hidden { display: none; }
  .error-message { color: #ff5252; text-align: center; margin-top: 10px; }
  .success-message { color: #2e7d32; text-align: center; margin-top: 10px; }
  #qrcode { margin-top: 15px; display: inline-block; }
  @media (max-width: 600px) {
    .card { padding: 25px 20px; }
    h1 { font-size: 1.5em; }
    .logo { width: 60px; height: 60px; font-size: 2em; }
  }
</style>
</head>
<body>
<div class="container">
  <div class="card">
    <div class="logo">📦</div>
    <h1>File Sharing</h1>
    <p style="text-align:center; color:#666;">Free, no registration, up to 50 GB</p>

    <div class="drop-zone" id="drop-zone">
      <p>📂 Drag & drop files or folders here</p>
      <p>or <label for="file-input">choose files</label></p>
      <input type="file" id="file-input" multiple hidden />
    </div>

    <div id="progress-container" class="progress-container hidden">
      <div class="progress-text">
        <span id="progress-label">Uploading... 0%</span>
        <span id="progress-percent">0%</span>
      </div>
      <div class="progress-bar-wrapper">
        <div id="progress-fill" class="progress-fill" style="width:0%"></div>
      </div>
      <div id="time-remaining" class="time-remaining"></div>
      <button id="cancel-btn" class="btn" style="margin-top:10px;">Cancel</button>
    </div>

    <div id="result" class="result-box hidden">
      <p style="color:#2e7d32; font-weight:bold;">✅ Link ready:</p>
      <div class="share-link">
        <a id="share-link" href="#" target="_blank"></a>
        <button class="copy-btn" id="copy-btn" title="Copy link">📋</button>
      </div>
      <div id="qrcode"></div>
      <p style="margin-top:15px; font-size:0.9em; color:#555;">Files available for 7 days</p>
      <button id="delete-btn" class="btn btn-danger" style="margin-top:10px;">🗑 Delete now</button>
    </div>

    <div id="message"></div>
  </div>
</div>

<script>
let currentUploadId = null;
let deleteToken = null;
let abortController = null;
let uploadStartTime = null;

const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const progressContainer = document.getElementById('progress-container');
const progressFill = document.getElementById('progress-fill');
const progressPercent = document.getElementById('progress-percent');
const progressLabel = document.getElementById('progress-label');
const timeRemaining = document.getElementById('time-remaining');
const cancelBtn = document.getElementById('cancel-btn');
const resultDiv = document.getElementById('result');
const shareLink = document.getElementById('share-link');
const copyBtn = document.getElementById('copy-btn');
const deleteBtn = document.getElementById('delete-btn');
const messageDiv = document.getElementById('message');
const qrDiv = document.getElementById('qrcode');

dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  const items = e.dataTransfer.items;
  if (items) handleItems(items);
});
dropZone.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', (e) => {
  if (e.target.files.length > 0) handleFileList(e.target.files);
});

async function handleItems(items) {
  let files = [];
  for (let i = 0; i < items.length; i++) {
    const item = items[i].webkitGetAsEntry();
    if (item) await traverseEntry(item, '', files);
  }
  if (files.length > 0) handleFileList(files);
}

function traverseEntry(entry, path, files) {
  return new Promise((resolve) => {
    if (entry.isFile) {
      entry.file((file) => {
        file.relativePath = path + file.name;
        files.push(file);
        resolve();
      });
    } else if (entry.isDirectory) {
      const dirReader = entry.createReader();
      dirReader.readEntries(async (entries) => {
        for (const ent of entries) {
          await traverseEntry(ent, path + entry.name + '/', files);
        }
        resolve();
      });
    }
  });
}

function handleFileList(fileList) {
  const files = Array.from(fileList);
  if (files.length === 0) return;
  if (files.length === 1) {
    uploadSingleFile(files[0]);
  } else {
    uploadAsZip(files);
  }
}

async function uploadSingleFile(file) {
  if (file.size > 50 * 1024 * 1024 * 1024) {
    showError(`File "${file.name}" is too large (>50 GB)`);
    return;
  }
  const initRes = await fetch('/upload/init', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ file_count: 1, total_size: file.size })
  });
  if (!initRes.ok) { showError('Initialization error'); return; }
  const { upload_id, short_code, delete_token } = await initRes.json();
  prepareUI(upload_id, short_code, delete_token);
  await uploadFileInChunks(file, file.relativePath || file.name, file.size);
  await finishUpload();
}

async function uploadAsZip(files) {
  const zip = new JSZip();
  let totalSize = 0;
  for (const file of files) {
    if (file.size > 50 * 1024 * 1024 * 1024) {
      showError(`File "${file.name}" is too large (>50 GB)`);
      return;
    }
    totalSize += file.size;
    zip.file(file.relativePath || file.name, file);
  }
  let zipBlob;
  try {
    zipBlob = await zip.generateAsync({type: "blob"});
  } catch (e) {
    showError('Error creating archive');
    return;
  }
  const initRes = await fetch('/upload/init', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ file_count: 1, total_size: zipBlob.size })
  });
  if (!initRes.ok) { showError('Initialization error'); return; }
  const { upload_id, short_code, delete_token } = await initRes.json();
  prepareUI(upload_id, short_code, delete_token);
  const zipFile = new File([zipBlob], "archive.zip", {type: "application/zip"});
  await uploadFileInChunks(zipFile, "archive.zip", zipBlob.size);
  await finishUpload();
}

function prepareUI(upload_id, short_code, delete_token) {
  currentUploadId = upload_id;
  deleteToken = delete_token;
  shareLink.href = '/' + short_code;
  shareLink.textContent = window.location.origin + '/' + short_code;
  resultDiv.classList.remove('hidden');
  progressContainer.classList.remove('hidden');
  progressFill.style.width = '0%';
  progressPercent.textContent = '0%';
  progressLabel.textContent = 'Uploading... 0%';
  timeRemaining.textContent = 'Time remaining: calculating...';
  qrDiv.innerHTML = '';
  new QRCode(qrDiv, {
    text: shareLink.textContent,
    width: 128,
    height: 128,
  });
}

function formatSpeed(bytesPerSec) {
  if (bytesPerSec === 0) return '0 KB/s';
  if (bytesPerSec < 1024) return bytesPerSec.toFixed(0) + ' B/s';
  const kb = bytesPerSec / 1024;
  if (kb < 1024) return kb.toFixed(1) + ' KB/s';
  const mb = kb / 1024;
  return mb.toFixed(1) + ' MB/s';
}

function formatTime(seconds) {
  if (!isFinite(seconds) || seconds < 0) return '...';
  if (seconds < 60) return Math.round(seconds) + 's';
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  if (mins < 60) return mins + 'm ' + secs + 's';
  const hours = Math.floor(mins / 60);
  const remainingMins = mins % 60;
  return hours + 'h ' + remainingMins + 'm';
}

async function uploadFileInChunks(file, fileName, fileSize) {
  const chunkCount = Math.ceil(fileSize / (5 * 1024 * 1024));
  abortController = new AbortController();
  let uploaded = 0;
  uploadStartTime = Date.now();
  try {
    for (let i = 0; i < chunkCount; i++) {
      if (abortController.signal.aborted) throw new Error('Cancelled');
      const start = i * 5 * 1024 * 1024;
      const end = Math.min(start + 5 * 1024 * 1024, fileSize);
      const blob = file.slice(start, end);
      const formData = new FormData();
      formData.append('chunk', blob, fileName);
      formData.append('file_name', fileName);
      formData.append('file_size', fileSize);
      formData.append('chunk_index', i);
      formData.append('total_chunks', chunkCount);

      const res = await fetch(`/upload/${currentUploadId}/${i}`, {
        method: 'PUT',
        body: formData,
        signal: abortController.signal
      });
      if (!res.ok) throw new Error('Error');
      uploaded += (end - start);
      const percent = Math.round((uploaded / fileSize) * 100);
      const elapsed = (Date.now() - uploadStartTime) / 1000;
      const speed = uploaded / (elapsed || 1);
      const remaining = (fileSize - uploaded) / (speed || 1);
      progressFill.style.width = percent + '%';
      progressPercent.textContent = percent + '%';
      progressLabel.textContent = `Uploaded ${percent}% · ${formatSpeed(speed)}`;
      timeRemaining.textContent = `Time remaining: ${formatTime(remaining)}`;
    }
  } catch (err) {
    if (err.message !== 'Cancelled') showError(err.message);
    progressContainer.classList.add('hidden');
    abortController = null;
    throw err;
  }
  abortController = null;
}

async function finishUpload() {
  try {
    await fetch(`/upload/${currentUploadId}/complete`, {method: 'POST'});
    progressContainer.classList.add('hidden');
    showSuccess('Upload complete!');
  } catch (e) {
    showError('Error completing upload');
  }
}

cancelBtn.addEventListener('click', () => {
  if (abortController) {
    abortController.abort();
    showError('Upload cancelled');
    progressContainer.classList.add('hidden');
    abortController = null;
  }
});

deleteBtn.addEventListener('click', async () => {
  if (!deleteToken) return;
  if (confirm('Are you sure you want to delete all files?')) {
    const res = await fetch('/delete/' + deleteToken, {method: 'DELETE'});
    if (res.ok) {
      resultDiv.classList.add('hidden');
      showSuccess('Files deleted');
    } else {
      showError('Deletion error');
    }
  }
});

copyBtn.addEventListener('click', () => {
  const link = shareLink.textContent;
  navigator.clipboard.writeText(link).then(() => {
    copyBtn.textContent = '✅';
    setTimeout(() => { copyBtn.textContent = '📋'; }, 2000);
  }).catch(() => {
    alert('Could not copy');
  });
});

function showMessage(msg, isError = false) {
  messageDiv.innerHTML = `<p class="${isError ? 'error-message' : 'success-message'}">${msg}</p>`;
}
function showError(msg) { showMessage(msg, true); }
function showSuccess(msg) { showMessage(msg, false); }
</script>
</body>
</html>
""")

# ------------------- Download page (like Mega) -------------------
def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024*1024:
        return f"{size_bytes/1024:.1f} KB"
    elif size_bytes < 1024*1024*1024:
        return f"{size_bytes/(1024*1024):.1f} MB"
    else:
        return f"{size_bytes/(1024*1024*1024):.2f} GB"

@app.get("/{short_code}")
async def download_page(short_code: str, request: Request, direct: bool = Query(False)):
    conn = get_conn()
    upload = conn.execute(
        "SELECT id, is_complete, is_deleted, created_at, expires_at FROM uploads WHERE short_code=?",
        (short_code,)
    ).fetchone()
    if not upload or upload['is_deleted']:
        conn.close()
        return HTMLResponse(status_code=404, content=error_html("Link not found or files have been deleted."))
    if not upload['is_complete']:
        conn.close()
        return HTMLResponse("<h3>Files are still uploading, please try later</h3>", status_code=202)

    files = conn.execute("SELECT original_name, size FROM files WHERE upload_id=?", (upload['id'],)).fetchall()
    conn.close()

    # Если запрошена прямая загрузка (параметр ?direct или путь /dl/...)
    if direct:
        return await serve_direct_download(upload['id'], short_code, files)

    # Иначе показываем красивую страницу
    total_size = sum(f['size'] for f in files)
    file_names = [f['original_name'] for f in files]
    display_name = file_names[0] if len(files) == 1 else f"{len(files)} files"
    created = upload['created_at']
    expires = upload['expires_at']
    
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Download - {display_name}</title>
        <script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                padding: 20px;
                margin: 0;
            }}
            .download-card {{
                background: white;
                border-radius: 20px;
                padding: 30px;
                max-width: 500px;
                width: 100%;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                text-align: center;
            }}
            .file-icon {{
                font-size: 4em;
                margin-bottom: 15px;
            }}
            h2 {{
                color: #333;
                word-break: break-all;
                margin-bottom: 15px;
            }}
            .info {{
                color: #555;
                font-size: 0.95em;
                margin: 10px 0;
            }}
            .btn-download {{
                display: inline-block;
                padding: 15px 40px;
                background: linear-gradient(135deg, #667eea, #764ba2);
                color: white;
                border: none;
                border-radius: 30px;
                font-weight: bold;
                font-size: 1.1em;
                cursor: pointer;
                text-decoration: none;
                transition: transform 0.2s, box-shadow 0.2s;
                box-shadow: 0 4px 10px rgba(102,126,234,0.4);
                margin: 15px 0;
            }}
            .btn-download:hover {{
                transform: translateY(-2px);
                box-shadow: 0 6px 15px rgba(102,126,234,0.6);
            }}
            .qr-section {{
                margin-top: 20px;
                position: relative;
            }}
            .qr-container {{
                display: inline-block;
                cursor: pointer;
                position: relative;
            }}
            .qr-hint {{
                position: absolute;
                bottom: 100%;
                left: 50%;
                transform: translateX(-50%);
                background: #333;
                color: white;
                padding: 5px 12px;
                border-radius: 20px;
                font-size: 0.8em;
                white-space: nowrap;
                opacity: 0;
                transition: opacity 0.3s;
                pointer-events: none;
            }}
            .qr-container:hover .qr-hint {{
                opacity: 1;
            }}
            .direct-link {{
                margin-top: 10px;
                font-size: 0.9em;
                color: #666;
            }}
            .direct-link a {{
                color: #667eea;
                text-decoration: none;
            }}
            .back-link {{
                margin-top: 20px;
                display: block;
                color: #667eea;
                text-decoration: none;
            }}
        </style>
    </head>
    <body>
        <div class="download-card">
            <div class="file-icon">📁</div>
            <h2>{display_name}</h2>
            <div class="info">Size: {format_size(total_size)}</div>
            <div class="info">Uploaded: {created}</div>
            <div class="info">Expires: {expires}</div>
            <a href="/dl/{short_code}" class="btn-download" id="downloadBtn">⬇ Download ({format_size(total_size)})</a>
            <div class="qr-section">
                <div class="qr-container" id="qrContainer">
                    <div id="qrcode"></div>
                    <div class="qr-hint">Click to switch to direct link</div>
                </div>
            </div>
            <div class="direct-link">
                Direct: <a href="/dl/{short_code}" id="directLink">/dl/{short_code}</a>
            </div>
            <a href="/" class="back-link">← Upload more files</a>
        </div>
        <script>
            const pageUrl = window.location.href.split('?')[0];
            const directUrl = pageUrl.replace(/\/[^\/]+$/, '/dl/{short_code}');
            let showingDirect = false;
            const qrDiv = document.getElementById('qrcode');
            const qrContainer = document.getElementById('qrContainer');
            const directLink = document.getElementById('directLink');
            
            function makeQR(url) {{
                qrDiv.innerHTML = '';
                new QRCode(qrDiv, {{
                    text: url,
                    width: 128,
                    height: 128,
                }});
            }}
            
            makeQR(pageUrl);
            
            qrContainer.addEventListener('click', () => {{
                showingDirect = !showingDirect;
                if (showingDirect) {{
                    makeQR(directUrl);
                    directLink.textContent = directUrl;
                }} else {{
                    makeQR(pageUrl);
                    directLink.textContent = '/dl/{short_code}';
                }}
            }});
        </script>
    </body>
    </html>
    """
    return HTMLResponse(html)

@app.get("/dl/{short_code}")
async def direct_download(short_code: str, request: Request):
    conn = get_conn()
    upload = conn.execute(
        "SELECT id, is_complete, is_deleted FROM uploads WHERE short_code=?",
        (short_code,)
    ).fetchone()
    if not upload or upload['is_deleted'] or not upload['is_complete']:
        conn.close()
        return HTMLResponse(status_code=404, content=error_html("File not found."))
    
    files = conn.execute("SELECT original_name, size FROM files WHERE upload_id=?", (upload['id'],)).fetchall()
    conn.close()
    return await serve_direct_download(upload['id'], short_code, files)

async def serve_direct_download(upload_id: str, short_code: str, files):
    upload_dir = UPLOAD_DIR / upload_id
    if not upload_dir.exists():
        return HTMLResponse(status_code=404, content=error_html("Files missing."))

    if len(files) == 1:
        file_path = upload_dir / files[0]['original_name']
        if not file_path.exists():
            return HTMLResponse(status_code=404, content=error_html("File missing."))
        return FileResponse(file_path, filename=files[0]['original_name'])
    else:
        zip_filename = f"files_{short_code}.zip"
        async def zip_stream():
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for f in files:
                    file_path = upload_dir / f['original_name']
                    if file_path.exists():
                        zf.write(file_path, f['original_name'])
            zip_buffer.seek(0)
            while True:
                data = zip_buffer.read(8192)
                if not data:
                    break
                yield data
        return StreamingResponse(zip_stream(), media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="{zip_filename}"'
        })

# ------------------- Upload endpoints (unchanged) -------------------
@app.post("/upload/init")
async def init_upload(data: dict):
    file_count = data.get("file_count", 1)
    upload_id = str(uuid.uuid4())
    short_code = generate_short_code()
    delete_token = str(uuid.uuid4())
    conn = get_conn()
    conn.execute(
        "INSERT INTO uploads (id, short_code, delete_token, file_count, created_at, expires_at) VALUES (?,?,?,?, datetime('now'), datetime('now', '+7 days'))",
        (upload_id, short_code, delete_token, file_count)
    )
    conn.commit()
    conn.close()
    (CHUNK_DIR / upload_id).mkdir(exist_ok=True)
    return {"upload_id": upload_id, "short_code": short_code, "delete_token": delete_token}

@app.put("/upload/{upload_id}/{chunk_index}")
async def upload_chunk(
    upload_id: str,
    chunk_index: int,
    chunk: UploadFile = File(...),
    file_name: str = Form(...),
    file_size: int = Form(...),
    total_chunks: int = Form(...)
):
    conn = get_conn()
    upload = conn.execute("SELECT id FROM uploads WHERE id=? AND is_complete=0 AND is_deleted=0", (upload_id,)).fetchone()
    conn.close()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found or already completed")

    chunk_dir = CHUNK_DIR / upload_id
    chunk_path = chunk_dir / f"{file_name}.part{chunk_index}"
    async with aiofiles.open(chunk_path, 'wb') as out_file:
        content = await chunk.read()
        await out_file.write(content)

    if chunk_index == 0:
        conn = get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO files (upload_id, original_name, stored_name, size) VALUES (?,?,?,?)",
            (upload_id, file_name, file_name, file_size)
        )
        conn.commit()
        conn.close()
    return {"status": "chunk_uploaded"}

@app.post("/upload/{upload_id}/complete")
async def complete_upload(upload_id: str):
    conn = get_conn()
    upload = conn.execute("SELECT id, short_code FROM uploads WHERE id=? AND is_complete=0 AND is_deleted=0", (upload_id,)).fetchone()
    if not upload:
        conn.close()
        raise HTTPException(status_code=404, detail="Upload not found")

    chunk_dir = CHUNK_DIR / upload_id
    target_dir = UPLOAD_DIR / upload_id
    target_dir.mkdir(exist_ok=True)

    chunks = {}
    for chunk_file in chunk_dir.iterdir():
        parts = chunk_file.name.rsplit('.part', 1)
        if len(parts) != 2:
            continue
        orig_name = parts[0]
        idx = int(parts[1])
        chunks.setdefault(orig_name, {})[idx] = chunk_file

    for orig_name, parts_dict in chunks.items():
        sorted_indices = sorted(parts_dict.keys())
        target_path = target_dir / orig_name
        async with aiofiles.open(target_path, 'wb') as outfile:
            for i in sorted_indices:
                part_path = parts_dict[i]
                async with aiofiles.open(part_path, 'rb') as infile:
                    while True:
                        data = await infile.read(1024*1024)
                        if not data:
                            break
                        await outfile.write(data)
        for part_path in parts_dict.values():
            part_path.unlink(missing_ok=True)

    conn.execute("UPDATE uploads SET is_complete=1 WHERE id=?", (upload_id,))
    conn.commit()
    conn.close()
    shutil.rmtree(chunk_dir, ignore_errors=True)
    return {"status": "completed", "short_code": upload['short_code']}

@app.delete("/delete/{delete_token}")
async def delete_by_token(delete_token: str):
    conn = get_conn()
    upload = conn.execute("SELECT id FROM uploads WHERE delete_token=? AND is_deleted=0", (delete_token,)).fetchone()
    conn.close()
    if not upload:
        raise HTTPException(status_code=404, detail="Invalid token or files already deleted")
    await delete_upload(upload['id'])
    return {"status": "deleted"}