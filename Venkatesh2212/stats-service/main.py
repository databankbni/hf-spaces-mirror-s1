import time
import uuid
from typing import List

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

EMAIL = "24f3000308@ds.study.iitm.ac.in"

ALLOWED_ORIGIN = "https://dash-av0kng.example.com"

app = FastAPI()

@app.middleware("http")
async def add_tracing_headers(request: Request, call_next):
    start = time.perf_counter()
    request_id = str(uuid.uuid4())
    response = await call_next(request)
    duration = time.perf_counter() - start
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = f"{duration:.6f}"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


def parse_values(values: str) -> List[int]:
    if values is None or values.strip() == "":
        raise HTTPException(status_code=400, detail="values parameter is required")
    parts = [p.strip() for p in values.split(",") if p.strip() != ""]
    if not parts:
        raise HTTPException(status_code=400, detail="values must contain at least one integer")
    try:
        return [int(p) for p in parts]
    except ValueError:
        raise HTTPException(status_code=400, detail="values must be comma-separated integers")


@app.get("/stats")
async def stats(values: str = Query(...)):
    nums = parse_values(values)
    count = len(nums)
    total = sum(nums)
    mean = total / count
    return {
        "email": EMAIL,
        "count": count,
        "sum": total,
        "min": min(nums),
        "max": max(nums),
        "mean": mean,
    }


@app.get("/")
async def root():
    return {"status": "ok"}