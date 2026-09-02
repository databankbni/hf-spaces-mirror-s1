import os
import time
import asyncio
import signal
import glob
import shutil
import sqlite3
import ssl
import socket



from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import settings
from app.database import engine, Base
from app.services.audio_service import AudioService
from app.services.mock_worker import MockWorker

# Import all routers
from app.routers import health, voice_samples, voice_design, tts, jobs, internal_worker, auth, admin, audio, compat, asr, video_dubbing
from app.routers import settings as settings_router

# Auto-shutdown state
last_request_time = time.time()

async def auto_shutdown_monitor():
    global last_request_time
    print("[AutoShutdown] Idle monitor started. Server will shut down if inactive for 5 minutes (300s).")
    while True:
        await asyncio.sleep(10)
        elapsed = time.time() - last_request_time
        if elapsed > 300:  # 5 minutes
            # Double check if there are any active jobs in the database
            from app.database import SessionLocal
            from app.models import TTSJob
            db = SessionLocal()
            try:
                active_job = db.query(TTSJob).filter(
                    TTSJob.status.in_(["starting_worker", "booting_kaggle", "queued_kaggle", "running", "exporting_wav"])
                ).first()
                if active_job:
                    # Reset timer if there is an active job, so we don't shut down while working!
                    last_request_time = time.time()
                    print(f"[AutoShutdown] Active job {active_job.id} is running. Delaying shutdown.")
                    continue
            except Exception as e:
                print(f"[AutoShutdown] Error checking active jobs: {e}")
            finally:
                db.close()
                
            print(f"[AutoShutdown] Server has been idle for {int(elapsed)} seconds. Shutting down process...")
            os.kill(os.getpid(), signal.SIGTERM)
            break

def run_startup_data_recovery():
    import os, glob, shutil, sqlite3
    db_path = settings.DATABASE_URL
    if db_path.startswith("sqlite:///"): db_path = db_path[10:]
    elif db_path.startswith("sqlite://"): db_path = db_path[9:]
    elif db_path.startswith("sqlite:"): db_path = db_path[7:]
    if "?" in db_path: db_path = db_path.split("?")[0]
    
    db_dir = os.path.dirname(db_path) or "."
    base_name = os.path.basename(db_path)
    
    if not os.path.exists(db_dir): return
    
    try:
        target_conn = sqlite3.connect(db_path, timeout=30)
        target_cursor = target_conn.cursor()
        
        # Migrate any legacy admin account or seed phucsd@gmail.com
        target_cursor.execute("SELECT id FROM users WHERE username = 'admin' OR email = 'admin@omnivoice.local'")
        legacy_row = target_cursor.fetchone()
        if legacy_row:
            target_cursor.execute(
                "UPDATE users SET username = 'phucsd@gmail.com', email = 'phucsd@gmail.com', is_admin = 1, is_approved = 1, is_verified = 1 WHERE id = ?",
                (legacy_row[0],)
            )
            target_conn.commit()
            admin_id = legacy_row[0]
            print(f"[Admin Transfer] Migrated legacy admin account to phucsd@gmail.com (ID: {admin_id})")
        else:
            target_cursor.execute("SELECT id FROM users WHERE email = 'phucsd@gmail.com' OR username = 'phucsd@gmail.com'")
            phuc_row = target_cursor.fetchone()
            if not phuc_row:
                from app.utils.auth import get_password_hash
                admin_id = "usr_62f1747adb99"
                admin_pass = os.environ.get("ADMIN_PASSWORD", "admin_password_2026")
                pass_hash = get_password_hash(admin_pass)
                target_cursor.execute(
                    "INSERT OR IGNORE INTO users (id, username, email, hashed_password, is_verified, is_approved, is_admin) VALUES (?, ?, ?, ?, 1, 1, 1)",
                    (admin_id, "phucsd@gmail.com", "phucsd@gmail.com", pass_hash)
                )
                target_conn.commit()
            else:
                admin_id = phuc_row[0]

        target_cursor.execute("SELECT COUNT(*) FROM voice_samples")
        vs_count = target_cursor.fetchone()[0]
        
        # Clean up any leftover recursive .restored or lock backup files
        for f in glob.glob(os.path.join(db_dir, f"{base_name}.corrupt_*")):
            if f.count(".restored") > 0 or f.endswith("-shm") or f.endswith("-wal") or "-shm." in f or "-wal." in f:
                try: os.remove(f)
                except: pass

        if vs_count < 6:
            print(f"[Startup Recovery] Current voice_samples count is {vs_count}. Scanning backup files for data salvage...")
            backup_files = [
                f for f in glob.glob(os.path.join(db_dir, f"{base_name}.corrupt_*"))
                if not f.endswith("-wal") and not f.endswith("-shm") and "-wal." not in f and "-shm." not in f and ".restored" not in f
            ]
            
            tables_to_restore = [
                "users", "api_keys", "voice_samples", "llm_profiles",
                "system_settings", "user_settings", "voice_design_previews", "tts_jobs", "worker_sessions", "api_usage_logs"
            ]
            
            for backup_file in backup_files:
                tmp_db = "/tmp/temp_startup_restore.db"
                tmp_wal = "/tmp/temp_startup_restore.db-wal"
                tmp_shm = "/tmp/temp_startup_restore.db-shm"
                
                for f in [tmp_db, tmp_wal, tmp_shm]:
                    if os.path.exists(f):
                        try: os.remove(f)
                        except: pass
                        
                try:
                    shutil.copy2(backup_file, tmp_db)
                    for f in os.listdir(db_dir):
                        if "-wal" in f: shutil.copy2(os.path.join(db_dir, f), tmp_wal)
                        elif "-shm" in f: shutil.copy2(os.path.join(db_dir, f), tmp_shm)
                            
                    source_conn = sqlite3.connect(tmp_db, timeout=10)
                    source_cursor = source_conn.cursor()
                    
                    for table in tables_to_restore:
                        try:
                            source_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
                            if not source_cursor.fetchone(): continue
                                
                            target_cursor.execute(f"PRAGMA table_info({table})")
                            target_cols = [row[1] for row in target_cursor.fetchall()]
                            if not target_cols: continue
                                
                            source_cursor.execute(f"PRAGMA table_info({table})")
                            source_cols = [row[1] for row in source_cursor.fetchall()]
                            
                            common_cols = [c for c in source_cols if c in target_cols]
                            if not common_cols: continue
                                
                            col_names = ", ".join(common_cols)
                            placeholders = ", ".join(["?"] * len(common_cols))
                            
                            source_cursor.execute(f"SELECT {col_names} FROM {table}")
                            rows = source_cursor.fetchall()
                            
                            if rows:
                                insert_sql = f"INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})"
                                for row in rows:
                                    try: target_cursor.execute(insert_sql, row)
                                    except: pass
                                target_conn.commit()
                                print(f"[Startup Recovery] Restored {len(rows)} records into '{table}' from {os.path.basename(backup_file)}")
                        except Exception as t_err:
                            print(f"[Startup Recovery Error] Table {table}: {t_err}")
                    source_conn.close()
                except Exception as f_err:
                    print(f"[Startup Recovery Error] File {backup_file}: {f_err}")

        target_conn.close()
    except Exception as ex:
        print(f"[Startup Recovery Fatal Error] {ex}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Reset last request time on startup to avoid immediate shutdown after slow container starts
    global last_request_time
    last_request_time = time.time()

    # Startup actions (triggered rebuild)
    print("[Main] Initializing OmniVoice On-Demand Gateway...")
    AudioService.ensure_directories()
    
    # Initialize DB tables
    print("[Main] Initializing SQLite database tables...")
    Base.metadata.create_all(bind=engine)
    
    # Run automatic database recovery and ownership alignment
    run_startup_data_recovery()

    # Run SQLite migration for any added columns
    from app.database import migrate_database
    migrate_database(settings.DATABASE_URL)
    
    # Seed default admin account phucsd@gmail.com
    print("[Main] Seeding default admin account (phucsd@gmail.com) if not present...")
    from app.database import SessionLocal
    from app.models import User
    from app.utils.auth import get_password_hash
    from sqlalchemy import text
    import secrets
    db = SessionLocal()
    try:
        # Migrate legacy admin if exists safely without UNIQUE constraint error
        legacy_admin = db.query(User).filter((User.username == "admin") | (User.email == "admin@omnivoice.local")).first()
        existing_phucsd = db.query(User).filter((User.email == "phucsd@gmail.com") | (User.username == "phucsd@gmail.com")).first()
        
        if legacy_admin:
            if existing_phucsd and existing_phucsd.id != legacy_admin.id:
                try:
                    db.execute(text("UPDATE voice_samples SET user_id = :new_id WHERE user_id = :old_id"), {"new_id": existing_phucsd.id, "old_id": legacy_admin.id})
                    db.execute(text("UPDATE api_keys SET user_id = :new_id WHERE user_id = :old_id"), {"new_id": existing_phucsd.id, "old_id": legacy_admin.id})
                    db.execute(text("UPDATE tts_jobs SET user_id = :new_id WHERE user_id = :old_id"), {"new_id": existing_phucsd.id, "old_id": legacy_admin.id})
                    db.delete(legacy_admin)
                    existing_phucsd.is_admin = True
                    existing_phucsd.is_approved = True
                    existing_phucsd.is_verified = True
                    db.commit()
                    print("[Admin Transfer] Merged legacy admin into existing phucsd@gmail.com account")
                except Exception as merge_err:
                    db.rollback()
                    print(f"[Admin Transfer Error] Merge failed: {merge_err}")
            else:
                legacy_admin.username = "phucsd@gmail.com"
                legacy_admin.email = "phucsd@gmail.com"
                legacy_admin.is_admin = True
                legacy_admin.is_approved = True
                legacy_admin.is_verified = True
                db.commit()
                print("[Admin Transfer] Transferred legacy admin account to phucsd@gmail.com")

        admin_user = db.query(User).filter((User.email == "phucsd@gmail.com") | (User.username == "phucsd@gmail.com")).first()
        if not admin_user:
            from app.utils.ids import generate_id
            admin_pass = os.environ.get("ADMIN_PASSWORD", "admin_password_2026")
            hashed_pwd = get_password_hash(admin_pass)
            api_key = f"ovg_live_{secrets.token_hex(24)}"
            admin_user = User(
                id=generate_id("usr"),
                username="phucsd@gmail.com",
                email="phucsd@gmail.com",
                hashed_password=hashed_pwd,
                is_verified=True,
                is_admin=True,
                is_approved=True,
                api_key=api_key
            )
            db.add(admin_user)
            db.commit()
        else:
            if not admin_user.is_verified or not admin_user.is_approved or not admin_user.is_admin:
                admin_user.is_verified = True
                admin_user.is_approved = True
                admin_user.is_admin = True
                db.commit()
        # Seed default LLM Profile if none exist
        from app.models import LLMProfile, SystemSetting
        if db.query(LLMProfile).count() == 0:
            def get_setting_val(k, default):
                s = db.query(SystemSetting).filter(SystemSetting.key == k).first()
                return s.value if s else default
            
            p_provider = get_setting_val("llm_provider", settings.LLM_PROVIDER)
            p_key = get_setting_val("llm_api_key", settings.LLM_API_KEY)
            p_model = get_setting_val("llm_model", settings.LLM_MODEL)
            p_ep = get_setting_val("llm_custom_endpoint", settings.LLM_CUSTOM_ENDPOINT)
            p_eff = get_setting_val("llm_thinking_effort", settings.LLM_THINKING_EFFORT)
            
            default_profile = LLMProfile(
                id="llm_default_gemini",
                name="Default Gemini Flash Profile",
                provider=p_provider or "gemini",
                api_key=p_key or "",
                model=p_model or "gemini-2.5-flash",
                custom_endpoint=p_ep or "",
                thinking_effort=p_eff or "none",
                is_active=True
            )
            db.add(default_profile)
            db.commit()
            print("[Main] Default LLM Profile seeded and activated.")
    except Exception as e:
        print(f"[Main ERROR] Failed to seed default admin or LLM profile: {e}")
    finally:
        db.close()
        
    # Start mock background worker if configured
    if settings.WORKER_MODE == "mock":
        print("[Main] Running in MOCK worker mode. Initializing MockWorker background thread...")
        MockWorker.start()
    else:
        print(f"[Main] Running in KAGGLE worker mode. Initializing KaggleOrchestrator queue runner...")
        from app.services.kaggle_orchestrator import KaggleOrchestrator
        KaggleOrchestrator.start_queue_runner()
        
    # Start auto-shutdown idle monitor (disabled by default, enabled only if ENABLE_AUTO_SHUTDOWN=true)
    # This prevents the server from shutting down unexpectedly during local development or VM hosting.
    shutdown_task = None
    if os.environ.get("ENABLE_AUTO_SHUTDOWN") == "true":
        shutdown_task = asyncio.create_task(auto_shutdown_monitor())
        print("[Main] Auto-shutdown monitor started.")
    else:
        print("[Main] Auto-shutdown monitor disabled.")
        
    yield
    
    # Shutdown actions
    print("[Main] Shutting down background tasks...")
    if shutdown_task:
        shutdown_task.cancel()
        try:
            await shutdown_task
        except asyncio.CancelledError:
            pass

    if settings.WORKER_MODE == "mock":
        print("[Main] Shutting down MockWorker background thread...")
        MockWorker.stop()
    else:
        print("[Main] Shutting down KaggleOrchestrator queue runner...")
        from app.services.kaggle_orchestrator import KaggleOrchestrator
        KaggleOrchestrator.stop_queue_runner()
    print("[Main] Gateway shutdown complete.")


app = FastAPI(
    title="OmniVoice On-Demand Gateway",
    description="Gateway managing job queues, audio storage, and polling orchestrations for OmniVoice GPU Workers.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex="https://.*\\.pages\\.dev",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

@app.middleware("http")
async def log_api_usage(request: Request, call_next):
    path = request.url.path
    
    # Exclude high-frequency polling and worker endpoints from DB logging
    is_polling = (
        path.startswith("/v1/internal/worker")
        or path.startswith("/v1/auth/me")
        or (request.method == "GET" and (
            (path.startswith("/v1/tts/jobs/") and len(path) > 13)
            or (path.startswith("/v1/voice-design/previews/") and len(path) > 26)
            or (path.startswith("/v1/jobs/") and len(path) > 9)
        ))
        or (request.method == "POST" and path == "/v1/jobs/batch")
    )
    
    is_loggable = (
        request.method != "OPTIONS"
        and not is_polling
        and not path.startswith("/health")
        and not path.startswith("/docs")
        and not path.startswith("/redoc")
        and not path.endswith("openapi.json")
        and not path.endswith("favicon.ico")
    )
    
    if not is_loggable:
        return await call_next(request)
        
    start_time = time.time()
    response = await call_next(request)
    duration_ms = (time.time() - start_time) * 1000
    
    # Try resolving user from X-API-Key, X-OV-API-Key or Authorization header token
    user_id = None
    token = None
    x_key = request.headers.get("x-api-key") or request.headers.get("x-ov-api-key")
    if x_key:
        token = x_key.split(" ", 1)[1] if x_key.startswith("Bearer ") else x_key
    else:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            
    if token:
        from app.database import SessionLocal
        from app.models import User, ApiKey
        from jose import jwt
        db = SessionLocal()
        try:
            # 1. Try new ApiKey table
            api_key_obj = db.query(ApiKey).filter(ApiKey.key == token).first()
            if api_key_obj:
                user_id = api_key_obj.user_id
            else:
                # Fallback to old User.api_key
                user = db.query(User).filter(User.api_key == token).first()
                if user:
                    user_id = user.id
                else:
                    # 2. Try JWT
                    try:
                        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
                        username = payload.get("sub")
                        if username:
                            user = db.query(User).filter(User.username == username).first()
                            if user:
                                user_id = user.id
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Middleware API Logger] Database error: {e}")
        finally:
            db.close()
            
    # Save log entry
    from app.database import SessionLocal
    from app.models import ApiUsageLog
    from app.utils.ids import generate_id
    db = SessionLocal()
    try:
        log_entry = ApiUsageLog(
            id=generate_id("log"),
            user_id=user_id,
            endpoint=path,
            method=request.method,
            status_code=response.status_code,
            ip_address=request.client.host if request.client else None,
            duration_ms=duration_ms
        )
        db.add(log_entry)
        db.commit()
    except Exception as e:
        print(f"[Middleware API Logger] Failed to save log: {e}")
    finally:
        db.close()
        
    return response

@app.middleware("http")
async def update_last_request_time(request: Request, call_next):
    global last_request_time
    path = request.url.path
    # Ignore OPTIONS requests, health checks, documentation pages, and icons
    if (
        request.method != "OPTIONS"
        and not path.startswith("/health")
        and not path.startswith("/docs")
        and not path.startswith("/redoc")
        and not path.endswith("openapi.json")
        and not path.endswith("favicon.ico")
    ):
        last_request_time = time.time()
        print(f"[AutoShutdown] Request to {path} updated last activity time.")
    return await call_next(request)

# Register routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(voice_samples.router)
from app.routers.voice_samples import public_library_router
app.include_router(public_library_router)
app.include_router(voice_design.router)
app.include_router(tts.router)
app.include_router(asr.router)
app.include_router(video_dubbing.router)
app.include_router(jobs.router)
app.include_router(internal_worker.router)
app.include_router(settings_router.router)
app.include_router(audio.router)
app.include_router(compat.router)

# Mount ElevenLabs compatibility router
from app.routers.compat import elevenlabs_compat_router
app.include_router(elevenlabs_compat_router)

# Serve built frontend static bundle if present (after all API routers are registered)
from fastapi.staticfiles import StaticFiles

frontend_dist_candidates = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend/dist")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../frontend/dist")),
    os.path.abspath("../frontend/dist"),
]
frontend_dist = next((p for p in frontend_dist_candidates if os.path.exists(p) and os.path.exists(os.path.join(p, "index.html"))), None)

if frontend_dist:
    print(f"[Main] Mounting frontend static bundle from {frontend_dist}")
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:
    @app.get("/")
    def read_root():
        return {
            "status": "online",
            "app": "OmniVoice On-Demand Gateway",
            "version": "1.0.0",
            "docs_url": "/docs"
        }

