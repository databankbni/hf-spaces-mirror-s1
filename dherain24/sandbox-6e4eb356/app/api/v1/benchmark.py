from fastapi import APIRouter, Query
from app.benchmark.runner import (
    run_benchmark_comparison,
    BenchmarkMetrics,
    get_cached_benchmark,
)

router = APIRouter(prefix="/benchmark", tags=["Benchmark & Simulator"])

@router.post("/run", response_model=BenchmarkMetrics)
async def run_benchmark_endpoint(
    sample_size: int = Query(100, ge=10, le=1000, description="Number of synthetic cases to evaluate"),
    seed: int = Query(42, description="Random seed for deterministic reproducibility"),
):
    results = run_benchmark_comparison(sample_size=sample_size, seed=seed)
    return results

@router.get("/latest", response_model=BenchmarkMetrics)
async def get_latest_benchmark_endpoint():
    latest = get_cached_benchmark()
    if latest is None:
        latest = run_benchmark_comparison(sample_size=100, seed=42)
    return latest
