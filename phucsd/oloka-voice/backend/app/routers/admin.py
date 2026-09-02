from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta

import time
from app.database import get_db
from app.models import User, ApiUsageLog, TTSJob, ApiKey, SystemSetting, LLMProfile
from app.schemas import LLMProfileResponse, LLMProfileCreateRequest, LLMProfileUpdateRequest, TestLLMProfileResponse
from app.utils.auth import get_current_user, get_password_hash
from app.utils.ids import generate_id
from app.config import settings

router = APIRouter(prefix="/v1/admin", tags=["Admin Portal"])

def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền truy cập trang quản trị."
        )
    return current_user

@router.get("/debug-db")
def debug_db(db: Session = Depends(get_db), current_user: User = Depends(get_admin_user)):
    import os, sqlite3
    db_info = {
        "db_url": settings.DATABASE_URL,
        "storage_dir": settings.STORAGE_DIR,
        "tables": {}
    }
    
    try:
        from app.models import User, VoiceSample, ApiKey, TTSJob, SystemSetting
        db_info["tables"]["users"] = [
            {"id": u.id, "username": u.username, "email": u.email, "is_admin": u.is_admin, "created_at": str(u.created_at)}
            for u in db.query(User).all()
        ]
        db_info["tables"]["voice_samples"] = [
            {"id": v.id, "name": v.name, "user_id": v.user_id, "is_public": v.is_public, "status": v.status, "created_at": str(v.created_at)}
            for v in db.query(VoiceSample).all()
        ]
        db_info["tables"]["api_keys"] = [
            {"id": k.id, "name": k.name, "user_id": k.user_id, "created_at": str(k.created_at)}
            for k in db.query(ApiKey).all()
        ]
        db_info["tables"]["tts_jobs"] = [
            {"id": j.id, "job_type": j.job_type, "status": j.status, "user_id": j.user_id, "text": j.text[:30] if j.text else "", "created_at": str(j.created_at)}
            for j in db.query(TTSJob).order_by(TTSJob.created_at.desc()).limit(20).all()
        ]
        
        # Check files in storage_dir
        storage_files = []
        if os.path.exists(settings.STORAGE_DIR):
            for root, dirs, files in os.walk(settings.STORAGE_DIR):
                for f in files:
                    rel_p = os.path.relpath(os.path.join(root, f), settings.STORAGE_DIR)
                    storage_files.append(rel_p)
        db_info["storage_files"] = storage_files[:30]

        # Check files in db directory
        db_dir = "/data/db" if os.path.exists("/data/db") else "./storage"
        db_dir_files = []
        if os.path.exists(db_dir):
            for f in os.listdir(db_dir):
                fp = os.path.join(db_dir, f)
                db_dir_files.append({"file": f, "size": os.path.getsize(fp)})
        db_info["db_dir_files"] = db_dir_files
    except Exception as e:
        db_info["error"] = str(e)
        
    return db_info

@router.post("/restore-corrupt-db")
def restore_corrupt_db(db: Session = Depends(get_db), current_user: User = Depends(get_admin_user)):
    import os, glob, shutil, sqlite3
    db_path = settings.DATABASE_URL
    if db_path.startswith("sqlite:///"):
        db_path = db_path[10:]
    elif db_path.startswith("sqlite://"):
        db_path = db_path[9:]
    elif db_path.startswith("sqlite:"):
        db_path = db_path[7:]
    if "?" in db_path:
        db_path = db_path.split("?")[0]
        
    db_dir = os.path.dirname(db_path) or "."
    base_name = os.path.basename(db_path)
    
    # Find all backup files that are main db files (not -wal or -shm)
    backup_files = [
        f for f in glob.glob(os.path.join(db_dir, f"{base_name}.corrupt_*"))
        if not f.endswith("-wal") and not f.endswith("-shm") and "-wal." not in f and "-shm." not in f
    ]
    
    if not backup_files:
        return {"status": "error", "message": "No main backup files found."}
        
    tables_to_restore = [
        "users", "api_keys", "voice_samples", "llm_profiles",
        "system_settings", "user_settings", "voice_design_previews", "tts_jobs", "worker_sessions", "api_usage_logs"
    ]
    
    summary = {}
    
    target_conn = sqlite3.connect(db_path, timeout=30)
    target_cursor = target_conn.cursor()
    
    for backup_file in backup_files:
        backup_summary = {}
        tmp_db = "/tmp/temp_restore.db"
        tmp_wal = "/tmp/temp_restore.db-wal"
        tmp_shm = "/tmp/temp_restore.db-shm"
        
        # Clean up old temp files
        for f in [tmp_db, tmp_wal, tmp_shm]:
            if os.path.exists(f):
                try: os.remove(f)
                except: pass
                
        try:
            # Copy main DB file
            shutil.copy2(backup_file, tmp_db)
            
            # Look for matching WAL and SHM files in db_dir
            for f in os.listdir(db_dir):
                if "-wal" in f:
                    shutil.copy2(os.path.join(db_dir, f), tmp_wal)
                elif "-shm" in f:
                    shutil.copy2(os.path.join(db_dir, f), tmp_shm)
                    
            source_conn = sqlite3.connect(tmp_db, timeout=10)
            source_cursor = source_conn.cursor()
            
            for table in tables_to_restore:
                try:
                    source_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
                    if not source_cursor.fetchone():
                        continue
                        
                    target_cursor.execute(f"PRAGMA table_info({table})")
                    target_cols = [row[1] for row in target_cursor.fetchall()]
                    if not target_cols:
                        continue
                        
                    source_cursor.execute(f"PRAGMA table_info({table})")
                    source_cols = [row[1] for row in source_cursor.fetchall()]
                    
                    common_cols = [c for c in source_cols if c in target_cols]
                    if not common_cols:
                        continue
                        
                    col_names = ", ".join(common_cols)
                    placeholders = ", ".join(["?"] * len(common_cols))
                    
                    source_cursor.execute(f"SELECT {col_names} FROM {table}")
                    rows = source_cursor.fetchall()
                    
                    if rows:
                        insert_sql = f"INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})"
                        restored_count = 0
                        for row in rows:
                            try:
                                target_cursor.execute(insert_sql, row)
                                restored_count += 1
                            except Exception:
                                pass
                        target_conn.commit()
                        backup_summary[table] = f"Restored {restored_count}/{len(rows)} rows"
                except Exception as t_err:
                    backup_summary[table] = f"Error: {t_err}"
                    
            source_conn.close()
        except Exception as f_err:
            backup_summary["file_error"] = str(f_err)
            
        summary[os.path.basename(backup_file)] = backup_summary
        
    # Re-align ownership of legacy user_id usr_ca3dd83a51d3 to admin user_id usr_62f1747adb99
    try:
        admin_user = db.query(User).filter(User.username == "admin").first()
        if admin_user:
            admin_id = admin_user.id
            target_cursor.execute("UPDATE voice_samples SET user_id = ? WHERE user_id = 'usr_ca3dd83a51d3'", (admin_id,))
            target_cursor.execute("UPDATE api_keys SET user_id = ? WHERE user_id = 'usr_ca3dd83a51d3'", (admin_id,))
            target_cursor.execute("UPDATE tts_jobs SET user_id = ? WHERE user_id = 'usr_ca3dd83a51d3'", (admin_id,))
            target_cursor.execute("UPDATE user_settings SET user_id = ? WHERE user_id = 'usr_ca3dd83a51d3'", (admin_id,))
            target_conn.commit()
            summary["ownership_realignment"] = f"Re-aligned legacy user data to admin ID {admin_id}"
    except Exception as re_err:
        summary["ownership_realignment_error"] = str(re_err)
        
    target_conn.close()
    return {"status": "ok", "summary": summary}

@router.post("/align-all-data-to-admin")
def align_all_data_to_admin(db: Session = Depends(get_db), current_user: User = Depends(get_admin_user)):
    from sqlalchemy import text
    admin_id = current_user.id
    
    # 1. Update user_id for all voice_samples, api_keys, tts_jobs, user_settings to current admin_id
    r1 = db.execute(text("UPDATE voice_samples SET user_id = :aid"), {"aid": admin_id})
    r2 = db.execute(text("UPDATE api_keys SET user_id = :aid"), {"aid": admin_id})
    r3 = db.execute(text("UPDATE tts_jobs SET user_id = :aid"), {"aid": admin_id})
    r4 = db.execute(text("UPDATE user_settings SET user_id = :aid"), {"aid": admin_id})
    db.commit()
    
    from app.models import VoiceSample, ApiKey, TTSJob
    return {
        "status": "ok",
        "admin_id": admin_id,
        "counts": {
            "voice_samples": db.query(VoiceSample).count(),
            "api_keys": db.query(ApiKey).count(),
            "tts_jobs": db.query(TTSJob).count(),
        }
    }

@router.post("/run-sqlite-recover")
def run_sqlite_recover(db: Session = Depends(get_db), current_user: User = Depends(get_admin_user)):
    import os, glob, subprocess, sqlite3
    db_path = settings.DATABASE_URL
    if db_path.startswith("sqlite:///"):
        db_path = db_path[10:]
    elif db_path.startswith("sqlite://"):
        db_path = db_path[9:]
    elif db_path.startswith("sqlite:"):
        db_path = db_path[7:]
    if "?" in db_path:
        db_path = db_path.split("?")[0]
        
    db_dir = os.path.dirname(db_path) or "."
    base_name = os.path.basename(db_path)
    
    backup_files = sorted(
        [f for f in glob.glob(os.path.join(db_dir, f"{base_name}.corrupt_*")) if os.path.isfile(f) and os.path.getsize(f) > 100000],
        key=os.path.getsize,
        reverse=True
    )
    
    if not backup_files:
        return {"status": "error", "message": "No large backup files found."}
        
    target_backup = backup_files[0]
    
    cmd = f'sqlite3 "{target_backup}" ".recover"'
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    if not res.stdout or "INSERT INTO" not in res.stdout:
        return {"status": "error", "message": f"sqlite3 recover failed or no output. Stderr: {res.stderr}"}
        
    sql_lines = res.stdout.splitlines()
    modified_sql = []
    for line in sql_lines:
        if line.startswith("INSERT INTO "):
            line = line.replace("INSERT INTO ", "INSERT OR REPLACE INTO ", 1)
        modified_sql.append(line)
        
    clean_sql = "\n".join(modified_sql)
    
    target_conn = sqlite3.connect(db_path, timeout=30)
    target_cursor = target_conn.cursor()
    target_cursor.executescript(clean_sql)
    target_conn.commit()
    target_conn.close()
    
    from app.models import User, VoiceSample, ApiKey, TTSJob
    recovered_counts = {
        "users": db.query(User).count(),
        "voice_samples": db.query(VoiceSample).count(),
        "api_keys": db.query(ApiKey).count(),
        "tts_jobs": db.query(TTSJob).count(),
    }
    
    return {
        "status": "ok",
        "target_backup": os.path.basename(target_backup),
        "backup_size": os.path.getsize(target_backup),
        "recovered": recovered_counts
    }

class UserAdminResponse(BaseModel):
    id: str
    username: str
    email: Optional[str]
    is_verified: bool
    is_approved: bool
    is_admin: bool
    oauth_provider: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

class UserCreateRequest(BaseModel):
    username: str
    email: str
    password: str
    is_verified: Optional[bool] = False
    is_approved: Optional[bool] = True
    is_admin: Optional[bool] = False

class UserUpdateRequest(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    is_verified: Optional[bool] = None
    is_approved: Optional[bool] = None
    is_admin: Optional[bool] = None

class AdminApiKeyResponse(BaseModel):
    id: str
    user_id: str
    name: str
    key: str
    created_at: datetime
    last_used_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class AdminApiKeyCreateRequest(BaseModel):
    name: str

class SystemSettingsResponse(BaseModel):
    worker_mode: str
    allow_registration: bool
    require_admin_approval: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from: str
    kaggle_username: str
    kaggle_key: str
    kaggle_kernel_ref: str
    kaggle_kernel_slug: str
    kaggle_kernel_title: str
    kaggle_accelerator: str
    kaggle_timeout_seconds: int
    kaggle_idle_timeout_seconds: int
    kaggle_worker_dir: str
    ui_layout: str
    hf_token: str
    llm_provider: str
    llm_api_key: str
    llm_model: str
    llm_custom_endpoint: str
    llm_thinking_effort: str

class SystemSettingsUpdateRequest(BaseModel):
    worker_mode: Optional[str] = None
    allow_registration: Optional[bool] = None
    require_admin_approval: Optional[bool] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    kaggle_username: Optional[str] = None
    kaggle_key: Optional[str] = None
    kaggle_kernel_ref: Optional[str] = None
    kaggle_kernel_slug: Optional[str] = None
    kaggle_kernel_title: Optional[str] = None
    kaggle_accelerator: Optional[str] = None
    kaggle_timeout_seconds: Optional[int] = None
    kaggle_idle_timeout_seconds: Optional[int] = None
    kaggle_worker_dir: Optional[str] = None
    ui_layout: Optional[str] = None
    hf_token: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    llm_custom_endpoint: Optional[str] = None
    llm_thinking_effort: Optional[str] = None

class AdminStatsResponse(BaseModel):
    total_users: int
    verified_users: int
    active_jobs: int
    completed_jobs: int
    failed_jobs: int
    total_api_calls: int

class ApiLogResponse(BaseModel):
    id: str
    user_id: Optional[str]
    username: Optional[str]
    endpoint: str
    method: str
    status_code: int
    ip_address: Optional[str]
    duration_ms: float
    created_at: datetime

@router.get("/users", response_model=List[UserAdminResponse])
def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100)
):
    """Lists all users in the system (Admin only)."""
    users = db.query(User).order_by(User.created_at.desc()).offset(skip).limit(limit).all()
    return users

@router.post("/users", response_model=UserAdminResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Allows Admin to create a user account directly."""
    # Check uniqueness
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Tên tài khoản đã tồn tại.")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Địa chỉ email đã được đăng ký.")

    from app.utils.ids import generate_id
    import secrets

    hashed_pwd = get_password_hash(payload.password)
    user_id = generate_id("usr")
    api_key = f"ovg_live_{secrets.token_hex(24)}"

    new_user = User(
        id=user_id,
        username=payload.username,
        email=payload.email,
        hashed_password=hashed_pwd,
        is_verified=payload.is_verified if payload.is_verified is not None else False,
        is_approved=payload.is_approved if payload.is_approved is not None else True,
        is_admin=payload.is_admin if payload.is_admin is not None else False,
        api_key=api_key
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@router.put("/users/{user_id}", response_model=UserAdminResponse)
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Updates user status (verification state, approval, password, admin role). Cannot demote yourself."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng.")
        
    if payload.username is not None:
        # Check uniqueness
        dup = db.query(User).filter(User.username == payload.username, User.id != user_id).first()
        if dup:
            raise HTTPException(status_code=400, detail="Tên tài khoản đã tồn tại.")
        user.username = payload.username
        
    if payload.email is not None:
        # Check uniqueness
        dup = db.query(User).filter(User.email == payload.email, User.id != user_id).first()
        if dup:
            raise HTTPException(status_code=400, detail="Địa chỉ email đã tồn tại.")
        user.email = payload.email

    if payload.password is not None and payload.password.strip():
        user.hashed_password = get_password_hash(payload.password)

    if payload.is_verified is not None:
        user.is_verified = payload.is_verified
        
    if payload.is_approved is not None:
        user.is_approved = payload.is_approved
        
    if payload.is_admin is not None:
        if user.id == admin.id and payload.is_admin is False:
            raise HTTPException(status_code=400, detail="Bạn không thể tự bỏ quyền admin của chính mình.")
        user.is_admin = payload.is_admin
        
    db.commit()
    db.refresh(user)
    return user

@router.delete("/users/{user_id}", response_model=dict)
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Deletes a user account from the system (Admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng.")
        
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Bạn không thể tự xóa tài khoản của chính mình.")
        
    db.delete(user)
    db.commit()
    return {"status": "success", "message": "Xóa người dùng thành công."}

# User API Key Management for Admin
@router.get("/users/{user_id}/apikeys", response_model=List[AdminApiKeyResponse])
def list_user_apikeys_admin(
    user_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Lists all API Keys for a specific user (Admin only)."""
    keys = db.query(ApiKey).filter(ApiKey.user_id == user_id).order_by(ApiKey.created_at.desc()).all()
    return keys

@router.post("/users/{user_id}/apikeys", response_model=AdminApiKeyResponse, status_code=status.HTTP_201_CREATED)
def create_user_apikey_admin(
    user_id: str,
    payload: AdminApiKeyCreateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Generates a named API Key for a specific user (Admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng.")

    from app.utils.ids import generate_id
    import secrets

    new_key = f"ovg_live_{secrets.token_hex(24)}"
    key_entry = ApiKey(
        id=generate_id("ak"),
        user_id=user_id,
        name=payload.name,
        key=new_key
    )
    db.add(key_entry)
    db.commit()
    db.refresh(key_entry)
    return key_entry

@router.delete("/apikeys/{key_id}", response_model=dict)
def delete_apikey_admin(
    key_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Admin revokes any API Key."""
    key_entry = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key_entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy Khóa API.")
    db.delete(key_entry)
    db.commit()
    return {"status": "success", "message": "Thu hồi khóa API thành công."}

# Global System Settings
@router.get("/settings", response_model=SystemSettingsResponse)
def get_system_settings_admin(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Retrieves all global system settings (Admin only)."""
    def get_setting(key: str, default_val):
        entry = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if entry and entry.value.strip():
            return entry.value.strip()
        return default_val

    worker_mode = get_setting("worker_mode", settings.WORKER_MODE)
    
    allow_reg_str = get_setting("allow_registration", "true" if settings.ALLOW_REGISTRATION else "false")
    allow_registration = allow_reg_str.lower() == "true"

    req_approval_str = get_setting("require_admin_approval", "false")
    require_admin_approval = req_approval_str.lower() == "true"
    
    smtp_host = get_setting("smtp_host", settings.SMTP_HOST)
    
    smtp_port_str = get_setting("smtp_port", str(settings.SMTP_PORT))
    try:
        smtp_port = int(smtp_port_str)
    except ValueError:
        smtp_port = settings.SMTP_PORT
        
    smtp_username = get_setting("smtp_username", settings.SMTP_USERNAME)
    smtp_password = get_setting("smtp_password", settings.SMTP_PASSWORD)
    smtp_from = get_setting("smtp_from", settings.SMTP_FROM)
    
    kaggle_username = get_setting("kaggle_username", settings.KAGGLE_USERNAME)
    kaggle_key = get_setting("kaggle_key", settings.KAGGLE_KEY)
    kaggle_kernel_ref = get_setting("kaggle_kernel_ref", settings.KAGGLE_KERNEL_REF)
    kaggle_kernel_slug = get_setting("kaggle_kernel_slug", settings.KAGGLE_KERNEL_SLUG)
    kaggle_kernel_title = get_setting("kaggle_kernel_title", settings.KAGGLE_KERNEL_TITLE)
    kaggle_accelerator = get_setting("kaggle_accelerator", settings.KAGGLE_ACCELERATOR)
    
    kaggle_timeout_str = get_setting("kaggle_timeout_seconds", str(settings.KAGGLE_TIMEOUT_SECONDS))
    try:
        kaggle_timeout_seconds = int(kaggle_timeout_str)
    except ValueError:
        kaggle_timeout_seconds = settings.KAGGLE_TIMEOUT_SECONDS
        
    kaggle_idle_timeout_str = get_setting("kaggle_idle_timeout_seconds", str(settings.WORKER_IDLE_TIMEOUT_SECONDS))
    try:
        kaggle_idle_timeout_seconds = int(kaggle_idle_timeout_str)
    except ValueError:
        kaggle_idle_timeout_seconds = settings.WORKER_IDLE_TIMEOUT_SECONDS

    kaggle_worker_dir = get_setting("kaggle_worker_dir", settings.KAGGLE_WORKER_DIR)
    ui_layout = get_setting("ui_layout", "modern")
    hf_token = get_setting("hf_token", settings.HF_TOKEN)
    llm_provider = get_setting("llm_provider", settings.LLM_PROVIDER)
    llm_api_key = get_setting("llm_api_key", settings.LLM_API_KEY)
    llm_model = get_setting("llm_model", settings.LLM_MODEL)
    llm_custom_endpoint = get_setting("llm_custom_endpoint", settings.LLM_CUSTOM_ENDPOINT)
    llm_thinking_effort = get_setting("llm_thinking_effort", settings.LLM_THINKING_EFFORT)

    return SystemSettingsResponse(
        worker_mode=worker_mode,
        allow_registration=allow_registration,
        require_admin_approval=require_admin_approval,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_username=smtp_username,
        smtp_password=smtp_password,
        smtp_from=smtp_from,
        kaggle_username=kaggle_username,
        kaggle_key=kaggle_key,
        kaggle_kernel_ref=kaggle_kernel_ref,
        kaggle_kernel_slug=kaggle_kernel_slug,
        kaggle_kernel_title=kaggle_kernel_title,
        kaggle_accelerator=kaggle_accelerator,
        kaggle_timeout_seconds=kaggle_timeout_seconds,
        kaggle_idle_timeout_seconds=kaggle_idle_timeout_seconds,
        kaggle_worker_dir=kaggle_worker_dir,
        ui_layout=ui_layout,
        hf_token=hf_token,
        llm_provider=llm_provider,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        llm_custom_endpoint=llm_custom_endpoint,
        llm_thinking_effort=llm_thinking_effort
    )

@router.post("/settings", response_model=dict)
def update_system_settings_admin(
    payload: SystemSettingsUpdateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Updates global system settings (Admin only)."""
    def save_setting(key: str, val):
        if val is None:
            return
        entry = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if not entry:
            entry = SystemSetting(key=key, value=str(val))
            db.add(entry)
        else:
            entry.value = str(val)

    try:
        if payload.worker_mode is not None:
            if payload.worker_mode not in ["mock", "kaggle"]:
                raise HTTPException(status_code=400, detail="worker_mode phải là 'mock' hoặc 'kaggle'.")
            save_setting("worker_mode", payload.worker_mode)
            
        if payload.ui_layout is not None:
            if payload.ui_layout not in ["classic", "modern"]:
                raise HTTPException(status_code=400, detail="ui_layout phải là 'classic' hoặc 'modern'.")
            save_setting("ui_layout", payload.ui_layout)

        if payload.allow_registration is not None:
            save_setting("allow_registration", "true" if payload.allow_registration else "false")
            
        if payload.require_admin_approval is not None:
            save_setting("require_admin_approval", "true" if payload.require_admin_approval else "false")
            
        if payload.smtp_host is not None:
            save_setting("smtp_host", payload.smtp_host)
        if payload.smtp_port is not None:
            save_setting("smtp_port", payload.smtp_port)
        if payload.smtp_username is not None:
            save_setting("smtp_username", payload.smtp_username)
        if payload.smtp_password is not None:
            save_setting("smtp_password", payload.smtp_password)
        if payload.smtp_from is not None:
            save_setting("smtp_from", payload.smtp_from)
            
        if payload.kaggle_username is not None:
            save_setting("kaggle_username", payload.kaggle_username)
        if payload.kaggle_key is not None:
            save_setting("kaggle_key", payload.kaggle_key)
        if payload.kaggle_kernel_ref is not None:
            save_setting("kaggle_kernel_ref", payload.kaggle_kernel_ref)
        if payload.kaggle_kernel_slug is not None:
            save_setting("kaggle_kernel_slug", payload.kaggle_kernel_slug)
        if payload.kaggle_kernel_title is not None:
            save_setting("kaggle_kernel_title", payload.kaggle_kernel_title)
        if payload.kaggle_accelerator is not None:
            save_setting("kaggle_accelerator", payload.kaggle_accelerator)
        if payload.kaggle_timeout_seconds is not None:
            save_setting("kaggle_timeout_seconds", payload.kaggle_timeout_seconds)
        if payload.kaggle_idle_timeout_seconds is not None:
            save_setting("kaggle_idle_timeout_seconds", payload.kaggle_idle_timeout_seconds)
        if payload.kaggle_worker_dir is not None:
            save_setting("kaggle_worker_dir", payload.kaggle_worker_dir)
        if payload.hf_token is not None:
            save_setting("hf_token", payload.hf_token)
        if payload.llm_provider is not None:
            save_setting("llm_provider", payload.llm_provider)
        if payload.llm_api_key is not None:
            save_setting("llm_api_key", payload.llm_api_key)
        if payload.llm_model is not None:
            save_setting("llm_model", payload.llm_model)
        if payload.llm_custom_endpoint is not None:
            save_setting("llm_custom_endpoint", payload.llm_custom_endpoint)
        if payload.llm_thinking_effort is not None:
            save_setting("llm_thinking_effort", payload.llm_thinking_effort)
        
        db.commit()
        return {"status": "success", "message": "Cập nhật cấu hình hệ thống thành công."}
    except Exception as e:
        db.rollback()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi ghi cấu hình hệ thống: {e}"
        )

class ScanModelsRequest(BaseModel):
    provider: Optional[str] = "gemini"
    api_key: Optional[str] = None
    custom_endpoint: Optional[str] = None

@router.post("/llm/scan-models", response_model=dict)
def scan_llm_models_admin(
    payload: ScanModelsRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Scans and fetches available LLM models from Gemini / OpenAI / Custom Endpoint."""
    provider = payload.provider or "gemini"
    
    def get_setting(key: str, default: str) -> str:
        entry = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        return entry.value if entry else default

    api_key = payload.api_key or get_setting("llm_api_key", settings.LLM_API_KEY)
    custom_endpoint = payload.custom_endpoint or get_setting("llm_custom_endpoint", settings.LLM_CUSTOM_ENDPOINT)

    import requests
    models_found = []

    try:
        if provider == "gemini":
            if not api_key:
                raise HTTPException(status_code=400, detail="Vui lòng nhập API Key để quét danh sách Gemini models.")
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            res = requests.get(url, timeout=15)
            res.raise_for_status()
            data = res.json()
            raw_models = data.get("models", [])
            for m in raw_models:
                name = m.get("name", "").replace("models/", "")
                methods = m.get("supportedGenerationMethods", [])
                if "generateContent" in methods:
                    models_found.append(name)
                    
        elif provider in ["openai", "custom"]:
            url = custom_endpoint if (provider == "custom" and custom_endpoint) else "https://api.openai.com/v1/models"
            if url.endswith("/chat/completions"):
                url = url.replace("/chat/completions", "/models")
            elif not url.endswith("/models"):
                url = url.rstrip("/") + "/models"

            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            
            res = requests.get(url, headers=headers, timeout=15)
            res.raise_for_status()
            data = res.json()
            raw_models = data.get("data", [])
            for m in raw_models:
                if isinstance(m, dict) and "id" in m:
                    models_found.append(m["id"])
                    
        return {"status": "success", "models": models_found, "count": len(models_found)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Lỗi khi quét danh sách Model: {str(e)}")

# Stats & Logs
@router.get("/stats", response_model=AdminStatsResponse)
def get_stats(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Aggregates system-wide usage statistics (Admin only)."""
    total_users = db.query(User).count()
    verified_users = db.query(User).filter(User.is_verified == True).count()
    
    active_jobs = db.query(TTSJob).filter(
        TTSJob.status.in_(["queued", "starting_worker", "booting_kaggle", "queued_kaggle", "running", "preparing_input", "generating_audio", "exporting_wav"])
    ).count()
    completed_jobs = db.query(TTSJob).filter(TTSJob.status == "completed").count()
    failed_jobs = db.query(TTSJob).filter(TTSJob.status == "failed").count()
    
    total_api_calls = db.query(ApiUsageLog).count()
    
    return AdminStatsResponse(
        total_users=total_users,
        verified_users=verified_users,
        active_jobs=active_jobs,
        completed_jobs=completed_jobs,
        failed_jobs=failed_jobs,
        total_api_calls=total_api_calls
    )

@router.get("/logs", response_model=List[ApiLogResponse])
def list_logs(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status_code: Optional[int] = Query(None)
):
    """Lists recent API usage logs with username resolution (Admin only)."""
    query = db.query(ApiUsageLog)
    
    if status_code is not None:
        query = query.filter(ApiUsageLog.status_code == status_code)
        
    logs = query.order_by(ApiUsageLog.created_at.desc()).offset(skip).limit(limit).all()
    
    # Batch resolve usernames to reduce SQL queries
    user_ids = {log.user_id for log in logs if log.user_id}
    users_map = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        users_map = {u.id: u.username for u in users}
        
    result = []
    for log in logs:
        result.append(
            ApiLogResponse(
                id=log.id,
                user_id=log.user_id,
                username=users_map.get(log.user_id) if log.user_id else "Anonymous",
                endpoint=log.endpoint,
                method=log.method,
                status_code=log.status_code,
                ip_address=log.ip_address,
                duration_ms=log.duration_ms,
                created_at=log.created_at
            )
        )
        
    return result


# --- LLM Profiles Management Endpoints ---

@router.get("/llm-profiles", response_model=List[LLMProfileResponse])
def list_llm_profiles(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """List all configured LLM Profiles."""
    return db.query(LLMProfile).order_by(LLMProfile.is_active.desc(), LLMProfile.created_at.desc()).all()

@router.post("/llm-profiles", response_model=LLMProfileResponse)
def create_llm_profile(
    payload: LLMProfileCreateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Create a new LLM Profile."""
    if payload.is_active:
        db.query(LLMProfile).update({LLMProfile.is_active: False})

    count = db.query(LLMProfile).count()
    is_act = payload.is_active or (count == 0)

    profile = LLMProfile(
        id=generate_id("llm"),
        name=payload.name,
        provider=payload.provider,
        api_key=payload.api_key or "",
        model=payload.model,
        custom_endpoint=payload.custom_endpoint or "",
        thinking_effort=payload.thinking_effort or "none",
        is_active=is_act
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile

@router.put("/llm-profiles/{profile_id}", response_model=LLMProfileResponse)
def update_llm_profile(
    profile_id: str,
    payload: LLMProfileUpdateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Update an existing LLM Profile."""
    profile = db.query(LLMProfile).filter(LLMProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Không tìm thấy LLM Profile.")

    if payload.is_active is True:
        db.query(LLMProfile).update({LLMProfile.is_active: False})

    if payload.name is not None:
        profile.name = payload.name
    if payload.provider is not None:
        profile.provider = payload.provider
    if payload.api_key is not None:
        profile.api_key = payload.api_key
    if payload.model is not None:
        profile.model = payload.model
    if payload.custom_endpoint is not None:
        profile.custom_endpoint = payload.custom_endpoint
    if payload.thinking_effort is not None:
        profile.thinking_effort = payload.thinking_effort
    if payload.is_active is not None:
        profile.is_active = payload.is_active

    db.commit()
    db.refresh(profile)
    return profile

@router.delete("/llm-profiles/{profile_id}", response_model=dict)
def delete_llm_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Delete an LLM Profile."""
    profile = db.query(LLMProfile).filter(LLMProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Không tìm thấy LLM Profile.")
    
    was_active = profile.is_active
    db.delete(profile)
    db.commit()

    if was_active:
        remaining = db.query(LLMProfile).first()
        if remaining:
            remaining.is_active = True
            db.commit()

    return {"status": "success", "message": "Xóa LLM Profile thành công."}

@router.post("/llm-profiles/{profile_id}/activate", response_model=LLMProfileResponse)
def activate_llm_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Set an LLM Profile as active for the entire system."""
    profile = db.query(LLMProfile).filter(LLMProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Không tìm thấy LLM Profile.")

    db.query(LLMProfile).update({LLMProfile.is_active: False})
    profile.is_active = True
    db.commit()
    db.refresh(profile)
    return profile

@router.post("/llm-profiles/{profile_id}/test", response_model=TestLLMProfileResponse)
def test_llm_profile_connection(
    profile_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Tests connection to a stored LLM Profile and persists test status to DB."""
    profile = db.query(LLMProfile).filter(LLMProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Không tìm thấy LLM Profile.")

    start_time = time.time()
    status_str = "failed"
    msg = ""
    latency = None

    import requests
    try:
        if profile.provider == "gemini":
            if not profile.api_key:
                raise ValueError("Chưa nhập Gemini API Key.")
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={profile.api_key}"
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            latency = round((time.time() - start_time) * 1000, 1)
            status_str = "success"
            msg = f"Kết nối Gemini thành công! Độ trễ: {latency} ms"
        else:
            base_url = profile.custom_endpoint.strip() if profile.custom_endpoint else "https://api.openai.com/v1"
            base_url = base_url.rstrip("/")
            if not base_url.endswith("/v1") and "/v1/" not in base_url:
                url = f"{base_url}/v1/models"
            else:
                url = f"{base_url}/models"
            headers = {}
            if profile.api_key:
                headers["Authorization"] = f"Bearer {profile.api_key}"
            res = requests.get(url, headers=headers, timeout=10)
            res.raise_for_status()
            latency = round((time.time() - start_time) * 1000, 1)
            status_str = "success"
            msg = f"Kết nối Provider {profile.provider.upper()} ({profile.model}) thành công! Độ trễ: {latency} ms"

    except Exception as e:
        status_str = "failed"
        msg = f"Lỗi kết nối: {str(e)}"
        latency = round((time.time() - start_time) * 1000, 1)

    profile.last_test_status = status_str
    profile.last_test_message = msg
    profile.last_tested_at = datetime.utcnow()
    db.commit()

    return TestLLMProfileResponse(
        status=status_str,
        message=msg,
        latency_ms=latency
    )

