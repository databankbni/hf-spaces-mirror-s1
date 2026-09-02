import os
import pytest
import io

os.environ["APP_ENV"] = "testing"
os.environ["WORKER_MODE"] = "mock"
os.environ["DATABASE_URL"] = "sqlite:///./test_db.sqlite"
os.environ["WORKER_TOKEN"] = "test_secret_token"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from app.main import app
from app.database import Base, get_db, engine

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    try:
        if os.path.exists("test_db.sqlite"):
            os.remove("test_db.sqlite")
    except Exception:
        pass

def test_asr_flow():
    # 1. Register a test user and login
    reg_res = client.post("/v1/auth/register", json={
        "username": "asr_user",
        "password": "password_123",
        "email": "asr_user@example.com"
    })
    assert reg_res.status_code == 201
    otp_code = reg_res.json()["debug_code"]
    
    verify_res = client.post("/v1/auth/verify-email", json={
        "username": "asr_user",
        "code": otp_code
    })
    assert verify_res.status_code == 200

    login_res = client.post("/v1/auth/login", json={
        "username": "asr_user",
        "password": "password_123"
    })
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    user_headers = {"Authorization": f"Bearer {token}"}

    # 2. Submit an ASR job
    dummy_wav = io.BytesIO(b"RIFF\x24\x08\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80\x3e\x00\x00\x00\x7d\x00\x00\x02\x00\x10\x00data\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00")
    files = {"file": ("test.wav", dummy_wav, "audio/wav")}
    
    response = client.post("/v1/asr", files=files, headers=user_headers)
    assert response.status_code == 200
    data = response.json()
    job_id = data["job_id"]
    assert job_id is not None
    assert data["status"] == "queued"

    # 3. Pull next ASR job as a worker
    worker_headers = {"Authorization": "Bearer test_secret_token"}
    job_response = client.get("/v1/internal/jobs/next?worker_id=test_worker_asr", headers=worker_headers)
    assert job_response.status_code == 200
    job_data = job_response.json()
    assert job_data["job"] is not None
    assert job_data["job"]["job_id"] == job_id

    # 4. Fetch the audio file of the job
    audio_response = client.get(f"/v1/asr/jobs/{job_id}/audio", headers=user_headers)
    assert audio_response.status_code == 200
    assert len(audio_response.content) > 0

    # Also test query parameter token retrieval for audio download
    audio_param_response = client.get(f"/v1/asr/jobs/{job_id}/audio?token={token}")
    assert audio_param_response.status_code == 200

    # 5. Submit job result from worker
    result_data = {
        "text": "Hello, world",
        "alignment": [{"text": "Hello", "timestamp": [0.1, 0.5]}, {"text": "world", "timestamp": [0.6, 1.0]}],
        "duration": 1.2
    }
    result_response = client.post(f"/v1/internal/jobs/{job_id}/asr", json=result_data, headers=worker_headers)
    assert result_response.status_code == 200

    # 6. Verify job status
    status_response = client.get(f"/v1/jobs/{job_id}", headers=user_headers)
    assert status_response.status_code == 200
    status_data = status_response.json()
    assert status_data["status"] == "completed"
    assert status_data["text"] == "Hello, world"
    assert len(status_data["alignment"]) == 2
    assert status_data["params"]["duration"] == 1.2
