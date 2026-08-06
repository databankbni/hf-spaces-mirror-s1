from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import os
import logging
import asyncio

from services.chat_extractor import ChatExtractor
from services.analyzer import ChatAnalyzer
from services.clipper import VideoClipper

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("main")

app = FastAPI(title="Twitch & Kick VOD Hype Clipper", version="1.0.0")

extractor = ChatExtractor()
clipper = VideoClipper(output_dir="./clips")

active_jobs: Dict[str, Dict[str, Any]] = {}

# Ensure directories exist
os.makedirs("./clips", exist_ok=True)
os.makedirs("./static", exist_ok=True)

# Mount clips directory for direct video playback in browser
app.mount("/clips", StaticFiles(directory="./clips"), name="clips")

class AnalyzeRequest(BaseModel):
    url: str = Field(..., description="Twitch or Kick VOD URL (or 'demo' for synthetic test)")
    interval: int = Field(15, description="Time window in seconds for chat bucketing")
    top_n: int = Field(5, description="Number of highlight peaks to identify")
    before_sec: int = Field(30, description="Seconds to include before peak")
    after_sec: int = Field(15, description="Seconds to include after peak")
    duration_mode: str = Field("short", description="Clip duration mode: short, medium, long, or viral_bunch")
    enable_ai_speech: bool = Field(True, description="Enable AI Speech-to-Text and narrative analysis")

class ClipRequest(BaseModel):
    url: str = Field(..., description="VOD URL")
    start_time: float = Field(..., description="Start timestamp in seconds")
    end_time: float = Field(..., description="End timestamp in seconds")
    title: str = Field("Hype Clip", description="Title for clip filename")
    aspect_ratio: str = Field("16:9", description="Video aspect ratio")
    job_id: str = Field("", description="Job ID for tracking progress")

@app.post("/api/analyze")
async def analyze_stream(req: AnalyzeRequest):
    try:
        logger.info(f"Analyzing stream: {req.url} (mode: {req.duration_mode}, ai_speech: {req.enable_ai_speech})")
        messages = extractor.extract_chat(req.url)
        analyzer = ChatAnalyzer(interval_seconds=req.interval)
        result = analyzer.analyze(
            messages=messages,
            url=req.url,
            top_n=req.top_n,
            before_peak_sec=req.before_sec,
            after_peak_sec=req.after_sec,
            duration_mode=req.duration_mode,
            enable_ai_speech=req.enable_ai_speech
        )
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Error analyzing stream: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/clip")
async def create_clip(req: ClipRequest):
    try:
        logger.info(f"Creating clip for {req.url} ({req.start_time}-{req.end_time}, job: {req.job_id})")
        if req.job_id:
            active_jobs[req.job_id] = {"status": "clipping", "progress": 5, "message": "Starting clip slice..."}
        
        def update_prog(pct, msg):
            if req.job_id:
                active_jobs[req.job_id] = {"status": "clipping", "progress": pct, "message": msg}
        
        result = await asyncio.to_thread(
            clipper.clip_section,
            url=req.url,
            start_time=req.start_time,
            end_time=req.end_time,
            title=req.title,
            aspect_ratio=req.aspect_ratio,
            progress_callback=update_prog
        )
        if result.get("status") == "error":
            if req.job_id:
                active_jobs[req.job_id] = {"status": "error", "progress": 0, "message": result.get("error")}
            raise HTTPException(status_code=500, detail=result.get("error"))
        
        if req.job_id:
            active_jobs[req.job_id] = {"status": "completed", "progress": 100, "message": "Clip ready!"}
        return {"status": "success", "clip": result}
    except Exception as e:
        if req.job_id:
            active_jobs[req.job_id] = {"status": "error", "progress": 0, "message": str(e)}
        logger.error(f"Error creating clip: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/clip/status/{job_id}")
async def get_clip_status(job_id: str):
    return active_jobs.get(job_id, {"status": "unknown", "progress": 0, "message": ""})

@app.get("/api/clips")
async def list_clips():
    try:
        clips = []
        if os.path.exists("./clips"):
            for fname in os.listdir("./clips"):
                if fname.endswith(".mp4"):
                    fpath = os.path.join("./clips", fname)
                    stat = os.stat(fpath)
                    clips.append({
                        "filename": fname,
                        "url": f"/clips/{fname}",
                        "size_mb": round(stat.st_size / (1024 * 1024), 2),
                        "created_at": int(stat.st_ctime)
                    })
        clips.sort(key=lambda x: x["created_at"], reverse=True)
        return {"status": "success", "clips": clips}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/clips/{filename}")
async def delete_clip(filename: str):
    try:
        fpath = os.path.join("./clips", os.path.basename(filename))
        if os.path.exists(fpath):
            # On Windows, browser video tags or ffmpeg may briefly hold file locks (WinError 32).
            # Retry deletion up to 5 times with short delays.
            for attempt in range(5):
                try:
                    os.remove(fpath)
                    break
                except (PermissionError, OSError) as pe:
                    if attempt == 4:
                        raise pe
                    await asyncio.sleep(0.5)
            return {"status": "success", "message": f"Deleted {filename}"}
        raise HTTPException(status_code=404, detail="Clip not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Serve static frontend files (must be mounted last so API routes take precedence)
app.mount("/", StaticFiles(directory="./static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
