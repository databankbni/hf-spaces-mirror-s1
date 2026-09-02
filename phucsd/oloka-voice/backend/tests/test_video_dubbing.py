import os
import pytest
import io
import json

os.environ["APP_ENV"] = "testing"
os.environ["WORKER_MODE"] = "mock"
os.environ["DATABASE_URL"] = "sqlite:///./test_video_db.sqlite"
os.environ["WORKER_TOKEN"] = "test_secret_token"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from app.main import app
from app.database import Base, get_db, engine
from app.models import VideoDubbingJob

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    try:
        if os.path.exists("test_video_db.sqlite"):
            os.remove("test_video_db.sqlite")
    except Exception:
        pass

def test_video_dubbing_flow():
    # 1. Register a test user and login
    reg_res = client.post("/v1/auth/register", json={
        "username": "dub_user",
        "password": "password_123",
        "email": "dub_user@example.com"
    })
    assert reg_res.status_code == 201
    otp_code = reg_res.json()["debug_code"]
    
    verify_res = client.post("/v1/auth/verify-email", json={
        "username": "dub_user",
        "code": otp_code
    })
    assert verify_res.status_code == 200

    login_res = client.post("/v1/auth/login", json={
        "username": "dub_user",
        "password": "password_123"
    })
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    user_headers = {"Authorization": f"Bearer {token}"}

    # 2. Submit a video dubbing job (mock file upload)
    # Generate a dummy small video file or mock audio file
    dummy_video = io.BytesIO(b"RIFF\x24\x08\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80\x3e\x00\x00\x00\x7d\x00\x00\x02\x00\x10\x00data\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00")
    files = {"file": ("test.mp4", dummy_video, "video/mp4")}
    data_payload = {"target_language": "English"}

    response = client.post("/v1/video-dubbing", files=files, data=data_payload, headers=user_headers)
    assert response.status_code == 200
    data = response.json()
    job_id = data["id"]
    assert job_id.startswith("vd_")
    assert data["status"] in ["queued", "downloading", "separating_audio", "transcribing", "translating", "awaiting_review"]

    # 3. Wait for background task to finish processing up to "awaiting_review"
    import time
    max_retries = 10
    finished_preparation = False
    for _ in range(max_retries):
        status_res = client.get(f"/v1/video-dubbing/jobs/{job_id}", headers=user_headers)
        assert status_res.status_code == 200
        status_data = status_res.json()
        if status_data["status"] == "awaiting_review":
            finished_preparation = True
            assert len(status_data["original_subtitles"]) > 0
            assert len(status_data["translated_subtitles"]) > 0
            break
        time.sleep(1.0)
    
    assert finished_preparation, f"Failed to reach awaiting_review state. Status: {status_data['status']}"

    # 4. Try updating the translated subtitles
    edited_subs = status_data["translated_subtitles"]
    edited_subs[0]["text"] = "Hello, this is a test segment text."
    
    update_res = client.put(
        f"/v1/video-dubbing/jobs/{job_id}/subtitles",
        headers=user_headers,
        json={
            "translated_subtitles": edited_subs
        }
    )
    assert update_res.status_code == 200
    assert update_res.json()["status"] == "success"

    # 5. Finalize the job
    finalize_res = client.post(f"/v1/video-dubbing/jobs/{job_id}/finalize", headers=user_headers)
    assert finalize_res.status_code == 200
    
    # 6. Wait for finalization completion
    finished_finalization = False
    for _ in range(max_retries):
        status_res = client.get(f"/v1/video-dubbing/jobs/{job_id}", headers=user_headers)
        assert status_res.status_code == 200
        status_data = status_res.json()
        if status_data["status"] == "completed":
            finished_finalization = True
            assert status_data["output_video_url"] is not None
            break
        time.sleep(1.0)

    assert finished_finalization, f"Failed to reach completed state. Status: {status_data['status']}"

    # 7. Try downloading output media files
    video_res = client.get(f"/v1/video-dubbing/jobs/{job_id}/video", headers=user_headers)
    assert video_res.status_code == 200
    
    vocals_res = client.get(f"/v1/video-dubbing/jobs/{job_id}/vocals", headers=user_headers)
    assert vocals_res.status_code == 200
    
    bgm_res = client.get(f"/v1/video-dubbing/jobs/{job_id}/bgm", headers=user_headers)
    assert bgm_res.status_code == 200
    
    output_res = client.get(f"/v1/video-dubbing/jobs/{job_id}/output", headers=user_headers)
    assert output_res.status_code == 200
