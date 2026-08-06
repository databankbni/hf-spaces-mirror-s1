"""Unified Backend for AI Research and Ollama Cloud Bridge (FIXED VERSION)."""

import os
import sys
import logging
import json
import asyncio
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
import uvicorn
import ollama

# Force local Ollama connection for internal agents
os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434"

# Add Research Agent to path (if exists)
BASE_DIR = Path(__file__).parent
RESEARCH_AGENT_DIR = BASE_DIR / "research_agent"
if RESEARCH_AGENT_DIR.exists():
    sys.path.append(str(RESEARCH_AGENT_DIR))

# Mock ResearchWorkflow if not available for demonstration
try:
    from workflow import ResearchWorkflow
except ImportError:
    class ResearchWorkflow:
        def __init__(self, **kwargs): pass
        def execute(self, query, callback):
            callback(f"Starting research on: {query}")
            import time
            time.sleep(1)
            callback("Searching web...")
            time.sleep(1)
            callback("Analyzing data...")
            return {"query": query, "status": "completed", "report": "Sample report content."}

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Research & Ollama Bridge", version="1.1.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ResearchRequest(BaseModel):
    query: str
    use_database: bool = False
    model: Optional[str] = "qwen2:0.5b"

class PromptRequest(BaseModel):
    prompt: str

@app.get("/")
def read_root():
    return {"status": "Running", "version": "1.1.1"}

@app.post("/api/chat")
async def api_chat(request: Request):
    try:
        body = await request.json()
        if "model" not in body: body["model"] = "qwen2:0.5b"
        return ollama.chat(**body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/research/stream")
async def create_research_stream(request: ResearchRequest):
    queue = asyncio.Queue()

    def progress_callback(msg: str):
        # This is safe to call from a thread because we use call_soon_threadsafe if needed, 
        # or we can just use the loop from where the generator is running.
        # However, for simplicity in this bridge, we handle it inside the generator loop.
        pass

    async def event_generator():
        # Better: use a local list to capture progress in the thread and pipe to queue
        progress_msgs = []
        def thread_callback(msg):
            progress_msgs.append(msg)

        try:
            model = request.model or "qwen2:0.5b"
            workflow = ResearchWorkflow(model_name=model)
            
            loop = asyncio.get_event_loop()
            # Run the heavy workflow in a thread
            task = loop.run_in_executor(None, workflow.execute, request.query, thread_callback)
            
            while not task.done():
                while progress_msgs:
                    msg = progress_msgs.pop(0)
                    yield f"data: {json.dumps({'status': msg})}\n\n"
                await asyncio.sleep(0.5)
            
            result = task.result()
            yield f"data: {json.dumps({'result': result})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)
