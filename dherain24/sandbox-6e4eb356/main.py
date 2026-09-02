import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.core.config import settings
from app.db.session import init_db, active_session_maker
from app.db.models import Merchant, Customer, RecoveryCase, RecoveryAction
from app.api.v1.router import api_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rri_backend")

async def seed_default_cases():
    try:
        async with active_session_maker() as db:
            m = await db.get(Merchant, "merch_default")
            if not m:
                m = Merchant(id="merch_default", name="Razorpay Test Merchant", email="ops@razorpay-merchant.com")
                db.add(m)
                await db.flush()

            customers_data = [
                ("cust_rahul_sharma", "Rahul Sharma", "rahul.s@techcorp.in", 310, 0.92),
                ("cust_priya_patel", "Priya Patel", "priya.p@designstudio.co", 140, 0.85),
                ("cust_anand_ent", "Acme Technologies Ltd", "finance@acmecorp.com", 720, 0.98),
                ("cust_neha_kapoor", "Neha Kapoor", "neha.k@gmail.com", 8, 0.10),
            ]
            for cid, name, email, tenure, rate in customers_data:
                c = await db.get(Customer, cid)
                if not c:
                    c = Customer(id=cid, merchant_id=m.id, name=name, email=email, tenure_days=tenure, historical_success_rate=rate)
                    db.add(c)
            await db.flush()

            cases_data = [
                ("RR-PRESET-1", "cust_rahul_sharma", "payment_failed", "pay_ncpi_u19_demo", 35000.0, "Insufficient balance (NPCI_U19)", "BAD_REQUEST_PAYMENT_DECLINED_BY_BANK: NPCI_DECLINE_U19", "DECISION_READY", 80, "delayed_retry", 23800.0, {"delay_hours": 36, "rationale": "Waiting 36 hours for month-end payroll credit captures salary window with 68% expected yield."}),
                ("RR-PRESET-2", "cust_priya_patel", "subscription_payment_failed", "sub_card_exp_demo", 12500.0, "Card Expired", "BAD_REQUEST_CARD_EXPIRED: ISSUER_CODE_54", "DECISION_READY", 75, "payment_link", 9500.0, {"target_channel": "whatsapp", "rationale": "Generating secure Razorpay payment link enables instant card instrument update."}),
                ("RR-PRESET-3", "cust_anand_ent", "payment_failed", "pay_limit_exceeded_demo", 185000.0, "Transaction Limit Exceeded", "BAD_REQUEST_TRANSACTION_LIMIT_EXCEEDED: NPCI_U30", "ESCALATED", 95, "escalate_human", 157250.0, {"rationale": "High-ticket amount exceeds ₹1,00,000 threshold. Policy gate triggers human desk confirmation."}),
                ("RR-PRESET-4", "cust_neha_kapoor", "subscription_payment_failed", "sub_mandate_revoked_demo", 8500.0, "Mandate Revoked by Customer", "BAD_REQUEST_MANDATE_REVOKED: ISSUER_CODE_14", "NO_ACTION", 20, "no_action", 0.0, {"rationale": "Customer explicitly cancelled recurring mandate. Retries violate NPCI rules. Strategic NO_ACTION preserves brand reputation."}),
            ]
            for cid, cust_id, stype, sid, amt, reason, decline, status, prio, act_type, exp_rec, params in cases_data:
                existing = await db.get(RecoveryCase, cid)
                if not existing:
                    rc = RecoveryCase(id=cid, merchant_id=m.id, customer_id=cust_id, source_type=stype, source_id=sid, amount_at_risk=amt, currency="INR", failure_reason=reason, raw_decline_code=decline, status=status, priority=prio)
                    db.add(rc)
                    await db.flush()
                    act = RecoveryAction(id=f"act_{cid}", case_id=rc.id, action_type=act_type, parameters=params, expected_recovery=exp_rec, policy_status="APPROVED" if status != "ESCALATED" else "APPROVAL_REQUIRED", approval_required=amt >= 100000, execution_status="READY")
                    db.add(act)
            await db.commit()
            logger.info("Auto-seeded flagship recovery cases successfully.")
    except Exception as e:
        logger.warning(f"Auto-seed completed or skipped: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing RRI Revenue Recovery Intelligence backend...")
    try:
        await init_db()
        await seed_default_cases()
        logger.info("Database initialized and ready.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
    yield
    logger.info("Shutting down RRI backend.")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Autonomous Bounded Revenue Recovery Decision Engine for Razorpay merchants.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for Lovable and Vercel frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/healthz", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "service": "rri-backend",
        "version": settings.VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": "connected",
        "port": settings.PORT,
    }

@app.get("/", tags=["System"])
async def root():
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "operational",
        "docs": "/docs",
        "health": "/healthz",
    }

# Mount API v1
app.include_router(api_router, prefix=settings.API_V1_STR)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=False)
