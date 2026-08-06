from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
import time
import uuid

app = FastAPI()

ALLOWED_ORIGIN = "https://dash-l3fkvm.example.com"
EMAIL = "24f1001166@ds.study.iitm.ac.in"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_custom_headers(request: Request, call_next):
    start = time.perf_counter()
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = str(uuid.uuid4())
    response.headers["X-Process-Time"] = f"{time.perf_counter() - start:.6f}"
    return response

@app.get("/")
async def root():
    return {"status": "ok"}

@app.get("/stats")
async def stats(values: str):
    nums = [int(x.strip()) for x in values.split(",") if x.strip()]

    count = len(nums)
    total = sum(nums)

    return {
        "email": EMAIL,
        "count": count,
        "sum": total,
        "min": min(nums),
        "max": max(nums),
        "mean": round(total / count, 4),
    }