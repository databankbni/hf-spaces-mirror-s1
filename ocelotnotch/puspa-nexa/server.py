import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Cookie
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI

# ========== Config via env ==========
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
WORKFLOW_ID = os.environ.get("CHATKIT_WORKFLOW_ID", "").strip()
WORKFLOW_VERSION = os.environ.get("CHATKIT_WORKFLOW_VERSION", "").strip()  # optional
DEBUG = os.environ.get("DEBUG", "").strip().lower() in ("1", "true", "yes", "y", "on")

# Cookie settings
COOKIE_NAME = os.environ.get("PUSPA_COOKIE_NAME", "puspa_uid").strip() or "puspa_uid"
# On HF/Cloud Run traffic is HTTPS, so secure cookie is OK.
# For local HTTP testing you can set COOKIE_SECURE=0.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1").strip().lower() not in ("0", "false", "no", "off")

# Paths
STATIC_DIR = Path(os.environ.get("STATIC_DIR", "static"))
IMAGES_DIR = Path(os.environ.get("IMAGES_DIR", "images"))

# ========== Hard checks ==========
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY belum diset (set di Secrets).")
if not WORKFLOW_ID:
    raise RuntimeError("CHATKIT_WORKFLOW_ID belum diset (wf_...).")

client = OpenAI(api_key=OPENAI_API_KEY)
app = FastAPI()


@app.post("/api/chatkit/session")
def create_chatkit_session(puspa_uid: str | None = Cookie(default=None)):
    """
    Mint ChatKit client_secret untuk user anonim.
    - Jika cookie sudah ada -> user konsisten.
    - Jika belum -> buat anon ID baru, lalu set cookie.
    """
    try:
        user_id = puspa_uid or f"anon_{uuid.uuid4().hex}"

        workflow = {"id": WORKFLOW_ID}
        if WORKFLOW_VERSION:
            workflow["version"] = str(WORKFLOW_VERSION)

        sess = client.beta.chatkit.sessions.create(
            user=user_id,
            workflow=workflow,
            expires_after={"anchor": "created_at", "seconds": 600},  # 10 menit
            chatkit_configuration={
                "file_upload": {"enabled": False},
                # history enabled/disabled tergantung kebutuhan kamu; biarkan default aman.
            },
        )

        resp = JSONResponse(
            {
                "client_secret": sess.client_secret,
                "session_id": sess.id,
                "workflow_id": WORKFLOW_ID,
                "workflow_version": str(WORKFLOW_VERSION) if WORKFLOW_VERSION else "",
            }
        )

        # Set cookie hanya saat user pertama kali datang
        if not puspa_uid:
            resp.set_cookie(
                key=COOKIE_NAME,
                value=user_id,
                httponly=True,
                samesite="lax",
                secure=COOKIE_SECURE,
                max_age=60 * 60 * 24 * 30,  # 30 hari
            )
        return resp

    except Exception as e:
        # Jangan bocorkan secret; cukup error message yang relevan
        raise HTTPException(status_code=500, detail=f"Failed to create chat session: {e}")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "debug": DEBUG,
        "static_dir_exists": STATIC_DIR.exists(),
        "images_dir_exists": IMAGES_DIR.exists(),
        "workflow_version_set": bool(WORKFLOW_VERSION),
    }


# ===== Serve static assets =====
# Fail early kalau folder tidak ada (biar ketahuan saat deploy, bukan saat user akses)
if not STATIC_DIR.exists():
    raise RuntimeError(f"Static directory not found: {STATIC_DIR.resolve()}")
if not IMAGES_DIR.exists():
    # images opsional, tapi index.html kamu pakai images; jadi lebih baik fail early juga
    raise RuntimeError(f"Images directory not found: {IMAGES_DIR.resolve()}")

app.mount("/images", StaticFiles(directory=str(IMAGES_DIR), html=True), name="images")
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
