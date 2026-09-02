from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import ALLOWED_ORIGINS
from app.face_recognition.routes import router as face_router
from app.resume.routes import router as resume_router
from app.job_recommendation import router as job_router
from app.sentiment_analysis.routes import router as reputation_router

app = FastAPI(title="CareerTrust AI Services")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount service routers at root so original paths remain unchanged
app.include_router(face_router)
app.include_router(resume_router)
app.include_router(job_router)
app.include_router(reputation_router)

# root health
@app.get("/")
def root():
    return {
        "ok": True,
        "services": [
            "face-embedding",
            "parse-resume",
            "job-recommendation",
            "review-sentiment",
        ],
    }
