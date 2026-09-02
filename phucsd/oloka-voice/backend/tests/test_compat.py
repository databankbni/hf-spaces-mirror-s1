import os
import pytest
import time
import base64
import zipfile
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

os.environ["APP_ENV"] = "testing"
os.environ["WORKER_MODE"] = "mock"
os.environ["DATABASE_URL"] = "sqlite:///./test_compat_db.sqlite"
os.environ["WORKER_TOKEN"] = "test_secret_token"

from app.main import app
from app.database import Base, get_db, engine, SessionLocal
from app.models import User, VoiceSample, ApiKey

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    existing_user = db.query(User).filter(User.username == "test_compat_user").first()
    if not existing_user:
        from app.utils.auth import get_password_hash
        hashed_pwd = get_password_hash("password_123")
        user = User(
            id="usr_test_compat",
            username="test_compat_user",
            email="compat@test.local",
            hashed_password=hashed_pwd,
            is_verified=True,
            is_approved=True,
            api_key="api_key_compat_old"
        )
        db.add(user)
        db.commit()
    else:
        user = existing_user
        
    existing_key = db.query(ApiKey).filter(ApiKey.key == "api_key_compat_new").first()
    if not existing_key:
        api_key_obj = ApiKey(
            id="key_compat_new",
            user_id=user.id,
            name="test_key",
            key="api_key_compat_new"
        )
        db.add(api_key_obj)
        db.commit()
    db.close()
    
    yield
    
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    try:
        if os.path.exists("test_compat_db.sqlite"):
            os.remove("test_compat_db.sqlite")
    except Exception:
        pass

def test_single_inference_auto_voice():
    headers = {"Authorization": "Bearer api_key_compat_new"}
    # Call compatibility single inference (synced)
    response = client.post("/v1/tts/inference", json={
        "text": "This is a single inference test.",
        "speed": 1.5
    }, headers=headers)
    
    # Since MockWorker is running, it will eventually complete the job.
    # Note that single_inference endpoint waits for 90s, and MockWorker takes ~6s to complete a job.
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert len(response.content) > 0


def test_single_inference_with_alignment():
    headers = {"Authorization": "Bearer api_key_compat_new"}
    response = client.post("/v1/tts/inference", json={
        "text": "This is a single inference test.",
        "speed": 1.5,
        "with_alignment": True
    }, headers=headers)
    
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    
    data = response.json()
    assert data["status"] == "completed"
    assert "audioUrl" in data
    assert "duration" in data
    assert isinstance(data["duration"], (int, float))
    assert "alignment" in data
    assert isinstance(data["alignment"], list)
    assert len(data["alignment"]) > 0
    for item in data["alignment"]:
        assert "word" in item
        assert "start" in item
        assert "end" in item


def test_batch_inference_json_array():
    headers = {"Authorization": "Bearer api_key_compat_new"}
    response = client.post("/v1/tts/batch", json=[
        {"id": "clip_01", "text": "Batch task number one.", "speed": 1.0},
        {"id": "clip_02", "text": "Batch task number two.", "instruct": "male, deep voice"}
    ], headers=headers)
    
    assert response.status_code == 200
    data = response.json()
    assert "batch_id" in data
    assert len(data["job_ids"]) == 2
    
    batch_id = data["batch_id"]
    
    # Manually complete the jobs to avoid waiting for background thread
    db = SessionLocal()
    from app.services.audio_service import AudioService
    from app.services.mock_worker import MockWorker
    from app.services.job_service import JobService
    from app.config import settings
    AudioService.ensure_directories()
    for j_id in data["job_ids"]:
        out_path = os.path.abspath(os.path.join(settings.outputs_dir, f"{j_id}.wav"))
        MockWorker._generate_sine_wav(out_path)
        JobService.complete_job_output(db, j_id, out_path)
    db.close()
    
    # Poll batch status until completed
    status_res = client.get(f"/v1/tts/batch/{batch_id}", headers=headers)
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["status"] == "completed"
    assert status_data["progress"] == 100
    
    # Download zip file
    zip_res = client.get(f"/v1/tts/batch/{batch_id}/zip", headers=headers)
    assert zip_res.status_code == 200
    assert zip_res.headers["content-type"] == "application/zip"
    
    # Verify contents of zip
    zip_filename = "temp_test_batch.zip"
    with open(zip_filename, "wb") as f:
        f.write(zip_res.content)
        
    try:
        with zipfile.ZipFile(zip_filename, 'r') as zf:
            namelist = zf.namelist()
            assert "clip_01.wav" in namelist
            assert "clip_02.wav" in namelist
    finally:
        if os.path.exists(zip_filename):
            os.remove(zip_filename)
