import os
import sys

import uuid
import queue
import threading
import contextlib
import tempfile
import shutil
from typing import Optional, List
from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

# Ensure the local modules can be imported
sys.path.append(os.path.dirname(__file__))
from env_config import get_config
from onboard_client import OnboardingState, build_workflow

app = FastAPI(title="Saras Onboarding API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job dict: job_id -> queue.Queue
job_queues = {}

class QueueWriter:
    def __init__(self, q: queue.Queue, original_stdout):
        self.q = q
        self.original_stdout = original_stdout
        
    def write(self, msg):
        if msg and msg.strip('\n'):
            self.q.put(msg)
        # also print to server terminal
        self.original_stdout.write(msg)
        
    def flush(self):
        self.original_stdout.flush()
        
    def fileno(self):
        return self.original_stdout.fileno()
        
    def getattr(self, attr):
        return getattr(self.original_stdout, attr)
        
    def isatty(self):
        return self.original_stdout.isatty()

def worker_thread(job_id: str, state: dict):
    # Playwright's sync API strictly requires an active Asyncio Event Loop to exist
    # Since we are inside a custom background thread, we must initialize an event loop manually.
    import asyncio
    import sys
    # Essential for Windows: default Selector loops in threads cannot spawn subprocesses
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
    asyncio.set_event_loop(asyncio.new_event_loop())

    q = job_queues[job_id]
    workflow = build_workflow()
    
    with contextlib.redirect_stdout(QueueWriter(q, sys.stdout)):
        print(f"\n" + "=" * 60)
        print(f"  Starting Onboarding Workflow [{state['env'].upper()}] from Web UI")
        print("=" * 60)
        
        try:
            workflow.invoke(state)
        except Exception as e:
            print(f"\nCRITICAL ERROR: {e}")
        finally:
            # Prevent Server Storage Leaks
            if state.get("logic_dir"):
                try:
                    shutil.rmtree(os.path.dirname(state["logic_dir"]))
                except Exception:
                    pass
            elif state.get("yaml_dir"):
                try:
                    shutil.rmtree(os.path.dirname(state["yaml_dir"]))
                except Exception:
                    pass
            
        print("\n\n=== PIPELINE FINISHED ===")
    
    # Send a poison pill to close the SSE stream natively
    q.put(None)


from fastapi import Request

@app.post("/api/onboard")
async def start_onboarding(request: Request):
    form = await request.form()
    
    env = form.get("env", "dev").lower()
    first_name = form.get("first_name", "")
    last_name = form.get("last_name", "")
    email = form.get("email", "")
    company_name = form.get("company_name", "")
    product_type = form.get("product_type", "")
    revenue = form.get("revenue", "")
    password = form.get("password", "")
    project_id = form.get("project_id", "")
    dataset = form.get("dataset", "")
    
    logic_files = form.getlist("logic_files")
    yaml_files = form.getlist("yaml_files")

    job_id = str(uuid.uuid4())
    job_queues[job_id] = queue.Queue()
    
    # 1. Create temporary directories for the uploaded files
    temp_dir = tempfile.mkdtemp(prefix=f"saras_job_{job_id}_")
    logic_dir = os.path.join(temp_dir, "logic_files")
    yaml_dir = os.path.join(temp_dir, "yaml_files")
    
    # Filter out empty strings which getlist might return if no files are appended
    logic_uploads = [f for f in logic_files if hasattr(f, "filename") and f.filename]
    yaml_uploads = [f for f in yaml_files if hasattr(f, "filename") and f.filename]
    
    if logic_uploads:
        os.makedirs(logic_dir, exist_ok=True)
        for f in logic_uploads:
            with open(os.path.join(logic_dir, f.filename), "wb") as w:
                w.write(await f.read())
    else:
        logic_dir = None
        
    if yaml_uploads:
        os.makedirs(yaml_dir, exist_ok=True)
        for f in yaml_uploads:
            with open(os.path.join(yaml_dir, f.filename), "wb") as w:
                w.write(await f.read())
    else:
        yaml_dir = None

    # 2. Prepare LangGraph State
    initial_state = OnboardingState(
        env=env.lower(),
        first_name=first_name,
        last_name=last_name,
        email=email,
        company_name=company_name,
        product_type=product_type,
        revenue=revenue,
        password=password,
        project_id=project_id,
        dataset=dataset,
        logic_dir=logic_dir,
        yaml_dir=yaml_dir,
        super_admin_token=None,
        user_id=None,
        company_id=None,
        auth_token=None,
        user_token=None,
        errors=[],
    )

    # 3. Spawn background execution
    # Playwright requires its own thread because it blocks async event loops heavily
    t = threading.Thread(target=worker_thread, args=(job_id, initial_state))
    t.start()

    return {"job_id": job_id, "message": "Onboarding started"}


@app.get("/api/logs/{job_id}")
async def stream_logs(job_id: str):
    if job_id not in job_queues:
        raise HTTPException(status_code=404, detail="Job ID not found")
        
    q = job_queues[job_id]

    import asyncio
    async def event_generator():
        # Keep-Alive tracking for Cloud Proxies
        empty_loops = 0
        
        while True:
            try:
                # Use non-blocking get so we don't block the ASGI loop
                msg = q.get_nowait()
                if msg is None:
                    # Cleanup server memory
                    del job_queues[job_id]
                    yield "data: [PROCESS_COMPLETE]\n\n"
                    break
                    
                # Format exactly as SSE expects: "data: <content>\n\n"
                safe_msg = msg.replace('\n', ' ')
                yield f"data: {safe_msg}\n\n"
                empty_loops = 0  # Reset on successful transmission
                
            except queue.Empty:
                await asyncio.sleep(0.1)
                empty_loops += 1
                
                # If 15 seconds have passed with absolutely no logs, 
                # inject a physical heartbeat padding chunk so Nginx/Cloudflare
                # doesn't terminate the SSE connection due to read timeouts! (every 150 loops of 0.1s)
                if empty_loops >= 150:
                    yield ": keep-alive heartbeat\n\n"
                    empty_loops = 0

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
