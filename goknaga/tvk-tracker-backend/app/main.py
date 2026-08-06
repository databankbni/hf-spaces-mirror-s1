from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.routes import stats, incidents, promises, members, ingest, baselines, citizen, dmk_archive, economic, defections, cron, propaganda, diagnostics, telegram, investments, power, factcheck, fact_checks, election, export
import logging

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="TVK Tracker API",
    description="Tamil Nadu Government accountability tracker",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stats.router, prefix="/api")
app.include_router(incidents.router, prefix="/api")
app.include_router(promises.router, prefix="/api")
app.include_router(members.router, prefix="/api")
app.include_router(ingest.router, prefix="/api")
app.include_router(baselines.router, prefix="/api")
app.include_router(citizen.router, prefix="/api")
app.include_router(dmk_archive.router, prefix="/api")
app.include_router(economic.router, prefix="/api")
app.include_router(defections.router, prefix="/api")
app.include_router(cron.router, prefix="/api")
app.include_router(propaganda.router, prefix="/api")
app.include_router(diagnostics.router, prefix="/api")
app.include_router(telegram.router, prefix="/api")
app.include_router(investments.router, prefix="/api")
app.include_router(power.router, prefix="/api")
app.include_router(factcheck.router, prefix="/api")
app.include_router(fact_checks.router, prefix="/api")
app.include_router(election.router, prefix="/api")
app.include_router(export.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "govt_day": settings.govt_day_number, "govt": settings.govt_name}
