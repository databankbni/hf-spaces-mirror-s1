from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.paper_service import PaperLensService
from api.schemas import SearchRequest
from api.version import APP_NAME, __version__

app = FastAPI(title="PaperLens API")

service = PaperLensService()

app.mount("/static", StaticFiles(directory="web"), name="static")


@app.on_event("startup")
def startup():
    service.build_sample_index()


@app.get("/")
def home():
    return FileResponse(Path("web") / "index.html")


@app.get("/api/health")
def health():
    return service.stats()


@app.get("/api/version")
def version():
    return {
        "name": APP_NAME,
        "version": __version__,
        "retrieval": "FAISS + BM25 + RRF",
        "embedding_model": "BAAI/bge-small-en-v1.5",
        "reranker": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "deployment": "FastAPI Docker app on Hugging Face Spaces",
    }


@app.get("/api/papers")
def papers():
    return {
        "papers": service.papers(),
    }


@app.post("/api/search")
def search(request: SearchRequest):
    question = request.question.strip()

    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    if len(question) > 500:
        raise HTTPException(status_code=400, detail="Question must be 500 characters or fewer.")

    if request.paper_titles is not None and len(request.paper_titles) == 0:
        raise HTTPException(status_code=400, detail="Select at least one paper.")

    return service.search(
        question=question,
        paper_titles=request.paper_titles,
        search_mode=request.search_mode,
    )


@app.get("/api/benchmark")
def benchmark():
    return {
        "questions": 15,
        "top1_paper_routing": 1.0,
        "top5_paper_routing": 1.0,
        "strict_page_hit_rate": 0.867,
    }