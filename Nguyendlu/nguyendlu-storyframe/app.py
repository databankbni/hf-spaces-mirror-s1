import os
import uuid
import shutil
import subprocess
import threading
import time
from typing import List, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from PIL import Image
import ssl
ssl._create_default_https_context = ssl._create_unverified_context
os.environ["PYTHONHTTPSVERIFY"] = "0"

app = FastAPI(title="Storyframe Space API", description="API Backend for Storyframe integration")

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_OUTPUT_DIR = "/app/outputs"
TASKS_DIR = os.path.join(BASE_OUTPUT_DIR, "tasks")
os.makedirs(TASKS_DIR, exist_ok=True)

# In-memory task status storage
# Structure: { task_id: { "status": "processing"|"completed"|"failed", "video_name": str, "error": str, "created_at": float } }
tasks_db = {}
latest_task_id = None

class ProcessRequest(BaseModel):
    video_url: str
    caption_mode: str = "off"
    speed: str = "auto"

def get_video_dir(task_id: str) -> Optional[str]:
    runs_dir = os.path.join(TASKS_DIR, task_id, "run")
    if not os.path.exists(runs_dir):
        return None
    subdirs = [d for d in os.listdir(runs_dir) if os.path.isdir(os.path.join(runs_dir, d)) and not d.startswith("_")]
    if not subdirs:
        return None
    return os.path.join(runs_dir, subdirs[0])

def run_storyframe_pipeline(task_id: str, video_path_or_url: str, caption_mode: str, speed: str):
    task_dir = os.path.join(TASKS_DIR, task_id)
    run_output_dir = os.path.join(task_dir, "run")
    log_file_path = os.path.join(task_dir, "process.log")
    
    os.makedirs(run_output_dir, exist_ok=True)
    
    # Command list
    cmd = [
        "storyframe", "run", video_path_or_url,
        "--output-root", run_output_dir,
        "--caption-mode", caption_mode,
        "--speed", speed,
        "--asr-model", "base"
    ]
    
    # Run the process and write stdout/stderr to log file
    try:
        with open(log_file_path, "w", encoding="utf-8") as log_file:
            log_file.write(f"Starting Storyframe task {task_id}...\n")
            log_file.write(f"Command: {' '.join(cmd)}\n\n")
            log_file.flush()
            
            process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                env=os.environ.copy()
            )
            process.wait()
            
        if process.returncode == 0:
            # Find the video name directory
            video_dir = get_video_dir(task_id)
            if video_dir:
                video_name = os.path.basename(video_dir)
                tasks_db[task_id]["status"] = "completed"
                tasks_db[task_id]["video_name"] = video_name
            else:
                tasks_db[task_id]["status"] = "failed"
                tasks_db[task_id]["error"] = "Could not locate output directory."
        else:
            tasks_db[task_id]["status"] = "failed"
            tasks_db[task_id]["error"] = f"Storyframe process exited with code {process.returncode}."
            
    except Exception as e:
        tasks_db[task_id]["status"] = "failed"
        tasks_db[task_id]["error"] = str(e)
        with open(log_file_path, "a", encoding="utf-8") as log_file:
            log_file.write(f"\nExecution error: {str(e)}\n")

@app.post("/api/process")
def process_video(request: ProcessRequest, background_tasks: BackgroundTasks):
    global latest_task_id
    task_id = str(uuid.uuid4())
    latest_task_id = task_id
    tasks_db[task_id] = {
        "status": "processing",
        "video_name": "",
        "error": "",
        "created_at": time.time()
    }
    
    # Start task in background
    background_tasks.add_task(
        run_storyframe_pipeline,
        task_id,
        request.video_url,
        request.caption_mode,
        request.speed
    )
    
    return {"success": True, "task_id": task_id}

@app.post("/api/process-file")
async def process_video_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    caption_mode: str = Form("off"),
    speed: str = Form("auto")
):
    global latest_task_id
    task_id = str(uuid.uuid4())
    latest_task_id = task_id
    task_dir = os.path.join(TASKS_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)
    
    # Save uploaded file
    file_ext = os.path.splitext(file.filename)[1]
    temp_video_path = os.path.join(task_dir, f"input_video{file_ext}")
    
    with open(temp_video_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    tasks_db[task_id] = {
        "status": "processing",
        "video_name": "",
        "error": "",
        "created_at": time.time()
    }
    
    # Start task in background
    background_tasks.add_task(
        run_storyframe_pipeline,
        task_id,
        temp_video_path,
        caption_mode,
        speed
    )
    
    return {"success": True, "task_id": task_id}

@app.get("/api/status/{task_id}")
def get_task_status(task_id: str):
    if task_id not in tasks_db:
        raise HTTPException(status_code=404, detail="Task not found")
        
    task_info = tasks_db[task_id]
    log_file_path = os.path.join(TASKS_DIR, task_id, "process.log")
    logs = ""
    
    # Read last 30 lines of logs to show progress
    if os.path.exists(log_file_path):
        try:
            with open(log_file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                logs = "".join(lines[-30:])
        except Exception:
            logs = "Reading logs failed..."

    response_data = {
        "status": task_info["status"],
        "error": task_info["error"],
        "logs": logs
    }
    
    if task_info["status"] == "completed":
        video_dir = get_video_dir(task_id)
        if video_dir:
            frames_dir = os.path.join(video_dir, "frames")
            # List all frames images
            frames = []
            if os.path.exists(frames_dir):
                frames = sorted([f for f in os.listdir(frames_dir) if f.endswith(".jpg")])
            
            response_data["video_name"] = task_info["video_name"]
            response_data["frames"] = frames
            
    return response_data

@app.get("/api/frame/{task_id}/{frame_name}")
def get_frame_image(task_id: str, frame_name: str):
    video_dir = get_video_dir(task_id)
    if not video_dir:
        raise HTTPException(status_code=404, detail="Task or outputs not found")
        
    frame_path = os.path.join(video_dir, "frames", frame_name)
    if not os.path.exists(frame_path):
        raise HTTPException(status_code=404, detail="Frame image not found")
        
    return FileResponse(frame_path, media_type="image/jpeg")

@app.post("/api/rebuild/{task_id}")
def rebuild_pdf(task_id: str, exclude_frames: List[str]):
    if task_id not in tasks_db or tasks_db[task_id]["status"] != "completed":
        raise HTTPException(status_code=400, detail="Task not completed or invalid")
        
    video_dir = get_video_dir(task_id)
    if not video_dir:
        raise HTTPException(status_code=404, detail="Output directory not found")
        
    frames_dir = os.path.join(video_dir, "frames")
    
    # 1. Remove excluded frames
    for fname in exclude_frames:
        fpath = os.path.join(frames_dir, fname)
        if os.path.exists(fpath):
            os.remove(fpath)
            
    # 2. Rebuild PDF from remaining frames using Pillow
    video_name = tasks_db[task_id]["video_name"]
    pdf_path = os.path.join(video_dir, f"{video_name}.pdf")
    
    try:
        # Get sorted remaining frames
        remaining_files = sorted([f for f in os.listdir(frames_dir) if f.endswith(".jpg")])
        if not remaining_files:
            return {"success": False, "error": "No frames left to build PDF."}
            
        images = []
        for f in remaining_files:
            img_path = os.path.join(frames_dir, f)
            images.append(Image.open(img_path).convert("RGB"))
            
        # Save as PDF
        images[0].save(pdf_path, save_all=True, append_images=images[1:])
        
        # Clean any cached zip since outputs modified
        zip_path = os.path.join(TASKS_DIR, task_id, "outputs.zip")
        if os.path.exists(zip_path):
            os.remove(zip_path)
            
        return {"success": True, "remaining_count": len(remaining_files)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/download/{task_id}/{file_type}")
def download_file(task_id: str, file_type: str):
    if task_id not in tasks_db or tasks_db[task_id]["status"] != "completed":
        raise HTTPException(status_code=400, detail="Task not ready or invalid")
        
    video_dir = get_video_dir(task_id)
    if not video_dir:
        raise HTTPException(status_code=404, detail="Outputs not found")
        
    video_name = tasks_db[task_id]["video_name"]
    
    if file_type == "pdf":
        file_path = os.path.join(video_dir, f"{video_name}.pdf")
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="PDF file not found")
        return FileResponse(file_path, filename=f"{video_name}.pdf", media_type="application/pdf")
        
    elif file_type == "mp3":
        file_path = os.path.join(video_dir, f"{video_name}.mp3")
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="MP3 file not found")
        return FileResponse(file_path, filename=f"{video_name}.mp3", media_type="audio/mpeg")
        
    elif file_type == "zip":
        zip_path = os.path.join(TASKS_DIR, task_id, "outputs.zip")
        
        # Create ZIP if it doesn't exist
        if not os.path.exists(zip_path):
            # Compress the entire video_dir folder
            shutil.make_archive(zip_path.replace(".zip", ""), 'zip', video_dir)
            
        return FileResponse(zip_path, filename=f"{video_name}_storyframe.zip", media_type="application/zip")
        
    else:
        raise HTTPException(status_code=400, detail="Invalid file type. Choose pdf, mp3, or zip")

@app.get("/api/latest-logs")
def get_latest_logs():
    if not latest_task_id:
        return {"error": "No task has run yet"}
    return get_task_status(latest_task_id)

# Background thread for periodic task folder cleanup
def cleanup_loop():
    while True:
        try:
            now = time.time()
            if os.path.exists(TASKS_DIR):
                for task_id in os.listdir(TASKS_DIR):
                    task_path = os.path.join(TASKS_DIR, task_id)
                    if os.path.isdir(task_path):
                        # Check folder creation/modification time
                        mtime = os.path.getmtime(task_path)
                        # Delete folders older than 1 hour (3600 seconds)
                        if now - mtime > 3600:
                            shutil.rmtree(task_path)
                            if task_id in tasks_db:
                                del tasks_db[task_id]
        except Exception as e:
            print(f"Cleanup error: {e}")
        time.sleep(900) # Run every 15 minutes

# Start cleanup thread in daemon mode
cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
cleanup_thread.start()
