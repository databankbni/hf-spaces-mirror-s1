from fastapi import APIRouter, Query

from src.storage import storage_backend


router = APIRouter()


@router.get("/admin/competitor_signals")
def admin_competitor_signals(product_id: int, limit: int = Query(default=100, ge=1, le=1000)) -> dict:
    return storage_backend.get_competitor_signals(product_id=product_id, limit=limit)


@router.get("/admin/ab_summary")
def admin_ab_summary(experiment: str) -> dict:
    return storage_backend.get_ab_summary(experiment)


@router.get("/admin/ab_outcomes")
def admin_ab_outcomes(experiment: str, limit: int = Query(default=200, ge=1, le=500)) -> dict:
    return storage_backend.get_ab_outcomes(experiment, limit)