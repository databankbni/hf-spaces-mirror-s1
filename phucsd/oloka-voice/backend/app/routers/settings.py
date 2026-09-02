from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.models import User, UserSetting, SystemSetting
from app.config import settings
from app.utils.auth import get_current_user

router = APIRouter(prefix="/v1/settings", tags=["Settings"])

class SettingsResponse(BaseModel):
  kaggle_username: str
  kaggle_key_configured: bool
  kaggle_kernel_ref: str
  kaggle_kernel_slug: str
  kaggle_kernel_title: str
  kaggle_accelerator: str
  kaggle_timeout_seconds: int
  kaggle_worker_dir: str
  worker_mode: str
  ui_layout: str

class SettingsUpdateRequest(BaseModel):
  kaggle_username: Optional[str] = None
  kaggle_key: Optional[str] = None
  kaggle_kernel_ref: Optional[str] = None
  kaggle_kernel_slug: Optional[str] = None
  kaggle_kernel_title: Optional[str] = None
  kaggle_accelerator: Optional[str] = None
  kaggle_timeout_seconds: Optional[int] = None
  kaggle_worker_dir: Optional[str] = None

@router.get("", response_model=SettingsResponse)
def get_system_settings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Retrieves current user's settings, masking the Kaggle key for security."""
    # Load defaults
    username = settings.KAGGLE_USERNAME
    key_configured = bool(settings.KAGGLE_KEY)
    kernel_ref = settings.KAGGLE_KERNEL_REF
    kernel_slug = settings.KAGGLE_KERNEL_SLUG
    kernel_title = settings.KAGGLE_KERNEL_TITLE
    accelerator = settings.KAGGLE_ACCELERATOR
    timeout_seconds = settings.KAGGLE_TIMEOUT_SECONDS
    worker_dir = settings.KAGGLE_WORKER_DIR

    # Load User Setting overrides from DB
    def get_setting(key: str, default_val):
        entry = db.query(UserSetting).filter(UserSetting.user_id == current_user.id, UserSetting.key == key).first()
        if entry and entry.value.strip():
            return entry.value.strip()
        return default_val

    username = get_setting("kaggle_username", username)
    db_key = get_setting("kaggle_key", "")
    if db_key:
        key_configured = True
    kernel_ref = get_setting("kaggle_kernel_ref", kernel_ref)
    kernel_slug = get_setting("kaggle_kernel_slug", kernel_slug)
    kernel_title = get_setting("kaggle_kernel_title", kernel_title)
    accelerator = get_setting("kaggle_accelerator", accelerator)
    
    timeout_str = get_setting("kaggle_timeout_seconds", str(timeout_seconds))
    try:
        timeout_seconds = int(timeout_str)
    except ValueError:
        pass
        
    worker_dir = get_setting("kaggle_worker_dir", worker_dir)
    
    ui_layout_entry = db.query(SystemSetting).filter(SystemSetting.key == "ui_layout").first()
    ui_layout = ui_layout_entry.value.strip() if ui_layout_entry and ui_layout_entry.value.strip() else "modern"

    return SettingsResponse(
        kaggle_username=username,
        kaggle_key_configured=key_configured,
        kaggle_kernel_ref=kernel_ref,
        kaggle_kernel_slug=kernel_slug,
        kaggle_kernel_title=kernel_title,
        kaggle_accelerator=accelerator,
        kaggle_timeout_seconds=timeout_seconds,
        kaggle_worker_dir=worker_dir,
        worker_mode=settings.WORKER_MODE,
        ui_layout=ui_layout
    )

@router.post("", response_model=dict)
def update_system_settings(payload: SettingsUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Saves updated Kaggle settings in the database for the user."""
    from app.utils.ids import generate_id
    def save_setting(key: str, val: Optional[str]):
        if val is None:
            return
        entry = db.query(UserSetting).filter(UserSetting.user_id == current_user.id, UserSetting.key == key).first()
        if not entry:
            entry = UserSetting(id=generate_id("us"), user_id=current_user.id, key=key, value=str(val))
            db.add(entry)
        else:
            entry.value = str(val)

    try:
        save_setting("kaggle_username", payload.kaggle_username)
        save_setting("kaggle_key", payload.kaggle_key)
        save_setting("kaggle_kernel_ref", payload.kaggle_kernel_ref)
        save_setting("kaggle_kernel_slug", payload.kaggle_kernel_slug)
        save_setting("kaggle_kernel_title", payload.kaggle_kernel_title)
        save_setting("kaggle_accelerator", payload.kaggle_accelerator)
        save_setting("kaggle_timeout_seconds", payload.kaggle_timeout_seconds)
        save_setting("kaggle_worker_dir", payload.kaggle_worker_dir)
        db.commit()
        return {"status": "success", "message": "Cập nhật cấu hình thành công."}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi ghi cấu hình: {e}"
        )

@router.post("/test-kaggle", response_model=dict)
def test_kaggle_connection(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Tests the connection to Kaggle API using the saved credentials for the user."""
    import os
    import sys
    import subprocess
    from app.services.kaggle_orchestrator import KaggleOrchestrator
    
    username, key, _, _ = KaggleOrchestrator.get_credentials(db, current_user.id)
    
    if not username or not key:
        return {
            "success": False,
            "message": "Cấu hình Kaggle Username hoặc API Key đang để trống."
        }
        
    env = os.environ.copy()
    env["KAGGLE_USERNAME"] = username
    env["KAGGLE_KEY"] = key
    env["PYTHONUTF8"] = "1"
    
    # Run using sys.executable -c entrypoint to prevent Windows PATH lookup errors and module errors
    cmd = [sys.executable, "-c", "from kaggle.cli import main; main()", "kernels", "list", "--mine", "--page-size", "1"]
    
    try:
        res = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            shell=False
        )
        stdout, stderr = res.communicate()
        
        if res.returncode == 0:
            return {
                "success": True,
                "message": "Kết nối thành công tới Kaggle API!"
            }
        else:
            err_msg = stderr.strip() or stdout.strip() or "Kaggle CLI returned non-zero code."
            return {
                "success": False,
                "message": f"Kết nối thất bại: {err_msg}"
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Lỗi hệ thống khi gọi Kaggle CLI: {e}"
        }

@router.post("/push-notebook", response_model=dict)
def push_notebook_to_kaggle(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Prepares and pushes the worker notebook to Kaggle for the user, returning the notebook web URL."""
    from app.services.kaggle_orchestrator import KaggleOrchestrator
    from app.services.kaggle_notebook_builder import KaggleNotebookBuilder
    import os
    import sys
    import subprocess
    
    if not KaggleOrchestrator.is_configured(db, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kaggle chưa được cấu hình. Vui lòng cập nhật cài đặt trước."
        )
        
    try:
        # Prepare files (worker.ipynb, kernel-metadata.json, requirements.txt)
        worker_dir = KaggleNotebookBuilder.prepare_all(db=db, user_id=current_user.id)
        username, key, kernel_ref, worker_dir_resolved = KaggleOrchestrator.get_credentials(db, current_user.id)
        
        # Resolve accelerator and timeout settings
        accelerator = settings.KAGGLE_ACCELERATOR
        timeout = settings.KAGGLE_TIMEOUT_SECONDS
        
        db_acc = db.query(UserSetting).filter(UserSetting.user_id == current_user.id, UserSetting.key == "kaggle_accelerator").first()
        db_timeout = db.query(UserSetting).filter(UserSetting.user_id == current_user.id, UserSetting.key == "kaggle_timeout_seconds").first()
        if db_acc and db_acc.value.strip():
            accelerator = db_acc.value.strip()
        if db_timeout and db_timeout.value.strip():
            try:
                timeout = int(db_timeout.value.strip())
            except ValueError:
                pass
                
        # Prepare the environment with credentials
        env = os.environ.copy()
        env["KAGGLE_USERNAME"] = username
        env["KAGGLE_KEY"] = key
        env["PYTHONUTF8"] = "1"

        # Map accelerator
        mapped_acc = "NvidiaTeslaT4"
        if accelerator:
            acc_lower = accelerator.lower()
            if "p100" in acc_lower:
                mapped_acc = "NvidiaTeslaP100"
            elif "t4" in acc_lower:
                mapped_acc = "NvidiaTeslaT4"
            else:
                mapped_acc = accelerator

        cmd = [sys.executable, "-c", "from kaggle.cli import main; main()", "kernels", "push", "-p", os.path.abspath(worker_dir_resolved), "--timeout", str(timeout), "--accelerator", mapped_acc]
        
        res = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            shell=False
        )
        stdout, stderr = res.communicate()
        
        if res.returncode == 0:
            notebook_url = f"https://www.kaggle.com/code/{kernel_ref}"
            return {
                "success": True,
                "message": "Đã đẩy notebook lên Kaggle thành công!",
                "url": notebook_url
            }
        else:
            err_msg = stderr.strip() or stdout.strip() or "Kaggle CLI returned non-zero code."
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Lỗi đẩy notebook: {err_msg}"
            )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi hệ thống khi đẩy notebook: {e}"
        )

@router.post("/push-dubbing-notebook", response_model=dict)
def push_dubbing_notebook_to_kaggle(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Prepares and pushes the dedicated DUBBING worker notebook to Kaggle."""
    from app.services.kaggle_orchestrator import KaggleOrchestrator
    from app.services.dubbing_notebook_builder import DubbingNotebookBuilder
    import os
    import sys
    import subprocess

    if not KaggleOrchestrator.is_configured(db, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kaggle chưa được cấu hình. Vui lòng cập nhật cài đặt trước."
        )

    try:
        worker_dir = DubbingNotebookBuilder.prepare_all(db=db, user_id=current_user.id)
        username, key, kernel_ref, worker_dir_resolved = KaggleOrchestrator.get_credentials(db, current_user.id)
        
        env = os.environ.copy()
        env["KAGGLE_USERNAME"] = username
        env["KAGGLE_KEY"] = key
        env["PYTHONUTF8"] = "1"

        dubbing_slug = f"{username}/omnivoice-dubbing-worker"
        cmd = [sys.executable, "-c", "from kaggle.cli import main; main()", "kernels", "push", "-p", os.path.abspath(worker_dir_resolved), "--timeout", "3600", "--accelerator", "NvidiaTeslaT4"]

        res = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            shell=False
        )
        stdout, stderr = res.communicate()

        if res.returncode == 0:
            return {
                "success": True,
                "message": "Đã đẩy Notebook Dubbing chuyên biệt lên Kaggle thành công!",
                "url": f"https://www.kaggle.com/code/{dubbing_slug}"
            }
        else:
            err_msg = stderr.strip() or stdout.strip() or "Kaggle CLI error"
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Lỗi đẩy Notebook Dubbing: {err_msg}"
            )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi hệ thống khi đẩy Notebook Dubbing: {e}"
        )

