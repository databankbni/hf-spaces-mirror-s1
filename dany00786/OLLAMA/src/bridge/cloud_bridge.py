'''python
"""FastAPI bridge that forwards requests to a local Ollama instance.
It mirrors the endpoints defined in the original Hugging Face Space
but runs locally, making the service reusable across projects.
"""

import os
import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uvicorn
import ollama
import asyncio
import logging
from pathlib import Path

# Ensure the local Ollama endpoint is used
os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434"

# Basic logging configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Ollama Bridge", version="0.1.0")

# CORS – allow local dev and any Vercel deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production you may want to tighten this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple health check
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": json.dumps({}), "ollama": "running"}

# Proxy endpoints – they just call the ``ollama`` python client

@app.post("/api/generate")
async def api_generate(request: Request):
    body = await request.json()
    model = body.get("model", "qwen2:0.5b")
    try:
        response = ollama.generate(**body)
        return response
    except Exception as e:
        logger.error(f"Generate failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def api_chat(request: Request):
    body = await request.json()
    model = body.get("model", "qwen2:0.5b")
    try:
        response = ollama.chat(**body)
        return response
    except Exception as e:
        logger.error(f"Chat failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/embeddings")
async def api_embeddings(request: Request):
    body = await request.json()
    try:
        response = ollama.embeddings(**body)
        return response
    except Exception as e:
        logger.error(f"Embeddings failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tags")
async def api_tags():
    try:
        return ollama.list()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/pull")
async def api_pull(request: Request):
    body = await request.json()
    try:
        return ollama.pull(**body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Streaming research endpoint – identical to the corrected version from the Space
from typing import Any
from pydantic import BaseModel

class ResearchRequest(BaseModel):
    query: str
    use_database: bool = False
    model: Optional[str] = "qwen2:0.5b"

@app.post("/api/research/stream")
async def create_research_stream(request: ResearchRequest):
    """Execute research with real‑time progress updates."""
    queue: asyncio.Queue = asyncio.Queue()

    def progress_callback(msg: str):
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.call_soon_threadsafe(queue.put_nowait, f"data: {json.dumps({'status': msg})}\n\n")
        else:
            asyncio.run(queue.put(f"data: {json.dumps({'status': msg})}\n\n"))

    async def heartbeat():
        try:
            while True:
                await asyncio.sleep(15)
                await queue.put(": heartbeat\n\n")
        except asyncio.CancelledError:
            pass

    async def event_generator():
        hb_task = asyncio.create_task(heartbeat())
        try:
            model = request.model or "qwen2:0.5b"
            from workflow import ResearchWorkflow  # Assuming it is importable
            workflow = ResearchWorkflow(
                db_connection=None,  # Bridge does not manage a DB by default
                model_name=model,
            )
            loop = asyncio.get_event_loop()
            task = loop.run_in_executor(None, workflow.execute, request.query, progress_callback)
            while not task.done() or not queue.empty():
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield msg
                except asyncio.TimeoutError:
                    continue
            result = task.result()
            response_data = {
                "query": result["query"],
                "status": result["status"],
                "findings_count": len(result.get("research_findings", [])),
                "report": result.get("report"),
                "report_path": result.get("report_path"),
                "error": result.get("error"),
            }
            yield f"data: {json.dumps({'result': response_data})}\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            hb_task.cancel()

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''
