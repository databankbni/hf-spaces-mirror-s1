from fastapi import APIRouter
from app.api.v1.cases import router as cases_router
from app.api.v1.agent import router as agent_router
from app.api.v1.benchmark import router as benchmark_router
from app.api.v1.webhooks import router as webhooks_router

api_router = APIRouter()
api_router.include_router(cases_router)
api_router.include_router(agent_router)
api_router.include_router(benchmark_router)
api_router.include_router(webhooks_router)
