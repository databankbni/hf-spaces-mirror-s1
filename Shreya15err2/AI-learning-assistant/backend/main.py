import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.upload import router as upload_router
from api.ask import router as ask_router
from api.documents import router as documents_router
from api.quiz import router as quiz_router
from api.flashcards import router as flashcards_router
from api.summary import router as summary_router
from api.studyplan import router as studyplan_router
from api.auth import router as auth_router

app = FastAPI(
    title="AI Learning Assistant",
    description="Production-ready AI learning platform",
    version="2.0.0",
)

# Allow React app (and potential local environments) to access the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router, prefix="/api", tags=["upload"])
app.include_router(ask_router, prefix="/api", tags=["ask"])
app.include_router(documents_router, prefix="/api", tags=["documents"])
app.include_router(quiz_router, prefix="/api", tags=["quiz"])
app.include_router(flashcards_router, prefix="/api", tags=["flashcards"])
app.include_router(summary_router, prefix="/api", tags=["summary"])
app.include_router(studyplan_router, prefix="/api", tags=["studyplan"])
app.include_router(auth_router, prefix="/api", tags=["auth"])


# Serve static frontend in production
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # Allow API routes to pass through
        if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("openapi.json"):
            return None
        
        # Check if the requested file exists
        file_path = os.path.join(frontend_dist, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
            
        # Fallback to index.html for React Router
        return FileResponse(os.path.join(frontend_dist, "index.html"))

@app.get("/")
def root():
    if os.path.isdir(frontend_dist) and os.path.isfile(os.path.join(frontend_dist, "index.html")):
        return FileResponse(os.path.join(frontend_dist, "index.html"))
    return {
        "message": "AI Learning Assistant v2.0 Running (API only)",
        "docs": "/docs",
        "status": "healthy"
    }


@app.get("/health")
def health():
    return {"status": "ok"}

