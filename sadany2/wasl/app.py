"""
Wasl alignment service.

Serves both the API and the frontend from one origin — no CORS, and no
artifact-CSP problem, because the page and the endpoint share a host.

Endpoints
    GET  /            the reader
    GET  /health      readiness, and whether the model is warm
    POST /align       audio + expected words -> per-word diagnosis
    POST /choose      audio + candidate words -> which one was said
"""
from __future__ import annotations

import asyncio, os, shutil, subprocess, tempfile, time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from align import Aligner
import limits

STATIC = os.path.join(os.path.dirname(__file__), "static")
state: dict = {"aligner": None, "loaded_at": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = time.time()
    state["aligner"] = Aligner()          # pulls weights on first boot, then cached
    state["loaded_at"] = round(time.time() - t, 1)
    yield
    state.clear()


app = FastAPI(title="Wasl alignment", lifespan=lifespan)

# The reader may be served from this Space or from a static host such as Vercel.
# Tighten ALLOW_ORIGINS to your own domains once the pilot URL is settled.
@app.middleware("http")
async def rate_limit(request, call_next):
    path = request.url.path
    if path in limits.EXEMPT_PATHS or path.startswith("/static"):
        return await call_next(request)
    ip = limits.client_ip(request)
    ok, retry, reason = limits.check_rate(ip)
    if not ok:
        limits.note("rate_limited")
        return JSONResponse(
            {"error": "rate limited", "limit": reason, "retry_after_seconds": retry},
            status_code=429, headers={"Retry-After": str(retry)})
    limits.forget_stale()
    return await call_next(request)


ALLOW_ORIGINS = os.environ.get("ALLOW_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def to_wav(upload: UploadFile) -> str:
    """Browsers hand us webm/opus or mp4; ffmpeg gives us 16k mono wav."""
    if not shutil.which("ffmpeg"):
        raise HTTPException(500, "ffmpeg missing from the image")
    raw = upload.file.read(limits.MAX_UPLOAD_BYTES + 1)
    if len(raw) > limits.MAX_UPLOAD_BYTES:
        limits.note("too_large")
        raise HTTPException(413, f"clip over {limits.MAX_UPLOAD_BYTES // 1048576}MB")
    src = tempfile.NamedTemporaryFile(delete=False, suffix="_in")
    src.write(raw); src.close()
    dst = src.name + ".wav"
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", src.name, "-ac", "1", "-ar", "16000", dst],
        capture_output=True)
    os.unlink(src.name)
    if p.returncode != 0 or not os.path.exists(dst):
        raise HTTPException(400, f"could not decode audio: {p.stderr.decode()[:200]}")
    return dst


@app.get("/health")
def health():
    a = state.get("aligner")
    return {"ok": a is not None, "model": getattr(a, "device", None) and str(a.device),
            "load_seconds": state.get("loaded_at"), **limits.stats()}


@app.post("/align")
async def align(audio: UploadFile = File(...), words: str = Form(...)):
    a = state.get("aligner")
    if a is None:
        raise HTTPException(503, "model still loading")
    expected = [w for w in words.split() if w.strip()]
    if not expected:
        raise HTTPException(400, "no expected words supplied")
    path = to_wav(audio)
    try:
        t = time.time()
        wav = a.load_audio(path)
        if wav.numel() < 1600:
            return JSONResponse({"silent": True, "reason": "under 100ms of audio"})
        try:
            async with limits.Gate():
                out = a.align(wav, expected)
        except asyncio.TimeoutError:
            raise HTTPException(503, "server busy — try again in a moment")
        out["audio_seconds"] = round(wav.numel() / 16000, 2)
        out["compute_seconds"] = round(time.time() - t, 2)
        limits.note("served")
        return out
    finally:
        os.unlink(path)


@app.post("/choose")
async def choose(audio: UploadFile = File(...), candidates: str = Form(...)):
    a = state.get("aligner")
    if a is None:
        raise HTTPException(503, "model still loading")
    cands = [w for w in candidates.split() if w.strip()]
    if len(cands) < 2:
        raise HTTPException(400, "need at least two candidates")
    path = to_wav(audio)
    try:
        t = time.time()
        wav = a.load_audio(path)
        if wav.numel() < 1600:
            return JSONResponse({"silent": True})
        try:
            async with limits.Gate():
                out = a.best_of(wav, cands)
        except asyncio.TimeoutError:
            raise HTTPException(503, "server busy — try again in a moment")
        out["compute_seconds"] = round(time.time() - t, 2)
        limits.note("served")
        return out
    finally:
        os.unlink(path)


@app.get("/")
def index():
    p = os.path.join(STATIC, "index.html")
    if not os.path.exists(p):
        return JSONResponse({"error": "static/index.html not deployed"}, 404)
    return FileResponse(p)


app.mount("/static", StaticFiles(directory=STATIC), name="static")
