from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import os

from routers import auth, shop, admin, discover, notifications, payment, seo, feedback
from utils.db import build_shop_index, flush_all
from routers.analytics import router as analytics_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ═══ STARTUP ═══
    print("[LIFESPAN] Building shop index...")
    build_shop_index()
    print("[LIFESPAN] Shop index ready.")

    yield  # App runs here

    # ═══ SHUTDOWN ═══
    print("[LIFESPAN] Flushing all data...")
    flush_all()
    print("[LIFESPAN] Shutdown complete.")

app = FastAPI(title="MyShub API", version="3.1.0", lifespan=lifespan)

# CORS — configure via env
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "https://myshub.site").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(shop.router, prefix="/shop", tags=["Shop"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(discover.router, prefix="/discover", tags=["Discover"])
app.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
app.include_router(payment.router, prefix="/payment", tags=["Payment"])
app.include_router(seo.router, prefix="", tags=["SEO"])
app.include_router(feedback.router, prefix="/feedback", tags=["Feedback"])  # NEW
app.include_router(analytics_router, tags=["Analytics"])

@app.get("/")
def root():
    return {"message": "MyShub API v3.1.0. All shubs live."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
