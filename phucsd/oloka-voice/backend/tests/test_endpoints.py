import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ["APP_ENV"] = "testing"
os.environ["WORKER_MODE"] = "mock"
os.environ["DATABASE_URL"] = "sqlite:///./test_db.sqlite"
os.environ["WORKER_TOKEN"] = "test_secret_token"


from app.main import app
from app.database import Base, get_db, engine
from app.services.job_service import JobService

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    # Create tables
    Base.metadata.create_all(bind=engine)
    yield
    # Cleanup
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    try:
        if os.path.exists("test_db.sqlite"):
            os.remove("test_db.sqlite")
    except Exception:
        pass



def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "OmniVoice" in data["app"]

def test_internal_worker_security():
    # Test register without token -> 401 or 403
    response = client.post("/v1/internal/workers/register", json={
        "worker_id": "test_worker",
        "status": "ready"
    })
    assert response.status_code == 403 or response.status_code == 401

    # Test register with invalid token -> 401
    headers = {"Authorization": "Bearer bad_token"}
    response = client.post("/v1/internal/workers/register", json={
        "worker_id": "test_worker",
        "status": "ready"
    }, headers=headers)
    assert response.status_code == 401

    # Test register with valid token -> 200
    headers = {"Authorization": "Bearer test_secret_token"}
    response = client.post("/v1/internal/workers/register", json={
        "worker_id": "test_worker",
        "status": "ready"
    }, headers=headers)
    assert response.status_code == 200

def test_vietnamese_mapping_instructs():
    # Test feminie mappings
    mapping = JobService.map_vietnamese_request_to_instruct("Giọng nữ trẻ, trầm ấm tự nhiên")
    assert "female" in mapping
    assert "young adult" in mapping
    assert "low pitch" in mapping

    # Test masculine mappings
    mapping = JobService.map_vietnamese_request_to_instruct("Giọng nam cao, nhẹ nhàng")
    assert "male" in mapping
    assert "high pitch" in mapping
    assert "whisper" in mapping

def test_kaggle_notebook_builder(tmp_path):
    from app.services.kaggle_notebook_builder import KaggleNotebookBuilder
    import json
    
    # Setup temp worker dir
    worker_dir = str(tmp_path / "kaggle_worker")
    
    # Test ensure_worker_dir
    abs_path = KaggleNotebookBuilder.ensure_worker_dir(worker_dir)
    assert os.path.exists(abs_path)
    
    # Test generate_metadata
    metadata_path = KaggleNotebookBuilder.generate_metadata(abs_path, "username", "slug", "title")
    assert os.path.exists(metadata_path)
    with open(metadata_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["id"] == "username/slug"
    assert data["title"] == "title"
    assert data["code_file"] == "omnivoice_worker.py"
    
    # Test generate_requirements
    req_path = KaggleNotebookBuilder.generate_requirements(abs_path)
    assert os.path.exists(req_path)
    with open(req_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "omnivoice" in content
    
    # Test generate_worker_code
    worker_path = KaggleNotebookBuilder.generate_worker_code(abs_path)
    assert os.path.exists(worker_path)
    with open(worker_path, "r", encoding="utf-8") as f:
        code = f.read()
    assert "ensure_dependencies()" in code

def test_tts_job_with_custom_speed_and_steps():
    reg_res = client.post("/v1/auth/register", json={
        "username": "test_user_123",
        "password": "password_123",
        "email": "test_user_123@example.com"
    })
    assert reg_res.status_code == 201
    otp_code = reg_res.json()["debug_code"]
    
    verify_res = client.post("/v1/auth/verify-email", json={
        "username": "test_user_123",
        "code": otp_code
    })
    assert verify_res.status_code == 200

    # Login to get JWT token
    login_res = client.post("/v1/auth/login", json={
        "username": "test_user_123",
        "password": "password_123"
    })
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    user_headers = {"Authorization": f"Bearer {token}"}

    # 1. Create a job with custom speed, steps, and new parameters using the JWT token
    response = client.post("/v1/tts/jobs", json={
        "mode": "auto_voice",
        "text": "Kiểm thử tham số tốc độ và độ chính xác",
        "speed": 1.2,
        "num_step": 25,
        "denoise": False,
        "guidance_scale": 3.5,
        "t_shift": 0.15,
        "position_temperature": 4.0,
        "class_temperature": 0.5,
        "layer_penalty_factor": 3.0,
        "duration": 5.5,
        "preprocess_prompt": False,
        "postprocess_output": False,
        "audio_chunk_duration": 10.0,
        "audio_chunk_threshold": 20.0
    }, headers=user_headers)
    assert response.status_code == 200
    data = response.json()
    job_id = data["job_id"]
    assert job_id is not None
 
    # 2. Register worker using worker token
    worker_headers = {"Authorization": "Bearer test_secret_token"}
    reg_response = client.post("/v1/internal/workers/register", json={
        "worker_id": "test_worker_1",
        "status": "ready"
    }, headers=worker_headers)
    assert reg_response.status_code == 200
 
    # 3. Pull next job and verify that all custom parameters are assigned to payload
    job_response = client.get("/v1/internal/jobs/next?worker_id=test_worker_1", headers=worker_headers)
    assert job_response.status_code == 200
    job_data = job_response.json()
    assert job_data["job"] is not None
    assert job_data["job"]["job_id"] == job_id
    assert job_data["job"]["speed"] == 1.2
    assert job_data["job"]["num_step"] == 25
    assert job_data["job"]["denoise"] is False
    assert job_data["job"]["guidance_scale"] == 3.5
    assert job_data["job"]["t_shift"] == 0.15
    assert job_data["job"]["position_temperature"] == 4.0
    assert job_data["job"]["class_temperature"] == 0.5
    assert job_data["job"]["layer_penalty_factor"] == 3.0
    assert job_data["job"]["duration"] == 5.5
    assert job_data["job"]["preprocess_prompt"] is False
    assert job_data["job"]["postprocess_output"] is False
    assert job_data["job"]["audio_chunk_duration"] == 10.0
    assert job_data["job"]["audio_chunk_threshold"] == 20.0

def test_openai_compatible_audio_endpoints():
    # 1. Login to get JWT token
    login_res = client.post("/v1/auth/login", json={
        "username": "test_user_123",
        "password": "password_123"
    })
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    user_headers = {"Authorization": f"Bearer {token}"}

    # 2. Get list of voices
    voices_res = client.get("/v1/audio/voices", headers=user_headers)
    assert voices_res.status_code == 200
    voices_data = voices_res.json()
    assert "voices" in voices_data
    assert len(voices_data["voices"]) > 0

    # 3. Request speech synthesis (synchronous)
    speech_res = client.post("/v1/audio/speech", json={
        "model": "omnivoice",
        "input": "Xin chào thế giới OpenAI",
        "voice": "female, young adult, american accent",
        "response_format": "mp3",
        "speed": 1.1
    }, headers=user_headers)
    print("SPEECH RESPONSE STATUS:", speech_res.status_code)
    print("SPEECH RESPONSE CONTENT:", speech_res.text)
    assert speech_res.status_code == 200
    assert speech_res.headers["content-type"] == "audio/mpeg"
    assert len(speech_res.content) > 0


def test_openai_compatible_speech_with_alignment():
    # 1. Login to get JWT token
    login_res = client.post("/v1/auth/login", json={
        "username": "test_user_123",
        "password": "password_123"
    })
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    user_headers = {"Authorization": f"Bearer {token}"}

    # 2. Request speech synthesis with alignment
    speech_res = client.post("/v1/audio/speech", json={
        "model": "omnivoice",
        "input": "Đây là cà phê Trung Nguyên",
        "voice": "female, young adult, american accent",
        "with_alignment": True
    }, headers=user_headers)
    assert speech_res.status_code == 200
    assert "application/json" in speech_res.headers["content-type"]
    
    data = speech_res.json()
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


def test_batch_jobs_status():
    # 1. Login to get JWT token
    login_res = client.post("/v1/auth/login", json={
        "username": "test_user_123",
        "password": "password_123"
    })
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    user_headers = {"Authorization": f"Bearer {token}"}

    # 2. Create job 1
    res1 = client.post("/v1/tts/jobs", json={
        "mode": "auto_voice",
        "text": "Job thứ nhất cho batch test"
    }, headers=user_headers)
    assert res1.status_code == 200
    job1_id = res1.json()["job_id"]

    # 3. Create job 2
    res2 = client.post("/v1/tts/jobs", json={
        "mode": "auto_voice",
        "text": "Job thứ hai cho batch test"
    }, headers=user_headers)
    assert res2.status_code == 200
    job2_id = res2.json()["job_id"]

    # 4. Request batch status for job1_id and job2_id
    batch_res = client.post("/v1/jobs/batch", json={
        "job_ids": [job1_id, job2_id]
    }, headers=user_headers)
    assert batch_res.status_code == 200
    batch_data = batch_res.json()
    assert job1_id in batch_data
    assert job2_id in batch_data
    assert batch_data[job1_id]["status"] in ["queued", "starting_worker", "running", "completed"]
    assert batch_data[job2_id]["status"] in ["queued", "starting_worker", "running", "completed"]

    # 5. Request batch status with one invalid and one valid ID
    batch_res_mixed = client.post("/v1/jobs/batch", json={
        "job_ids": [job1_id, "non_existent_job_id"]
    }, headers=user_headers)
    assert batch_res_mixed.status_code == 200
    batch_data_mixed = batch_res_mixed.json()
    assert job1_id in batch_data_mixed
    assert "non_existent_job_id" not in batch_data_mixed

    # 6. Request batch status with empty list
    batch_res_empty = client.post("/v1/jobs/batch", json={
        "job_ids": []
    }, headers=user_headers)
    assert batch_res_empty.status_code == 200
    assert batch_res_empty.json() == {}


def test_custom_headers_authentication():
    # 1. Login to get JWT token
    login_res = client.post("/v1/auth/login", json={
        "username": "test_user_123",
        "password": "password_123"
    })
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    # 2. Test authenticating via X-API-Key header (without Bearer prefix)
    res_x_api_key = client.get("/v1/jobs", headers={"X-API-Key": token})
    assert res_x_api_key.status_code == 200

    # 3. Test authenticating via X-OV-API-Key header (with Bearer prefix)
    res_x_ov_api_key = client.get("/v1/jobs", headers={"X-OV-API-Key": f"Bearer {token}"})
    assert res_x_ov_api_key.status_code == 200

    # 4. Test priority: X-API-Key with valid token, while Authorization header contains dummy HF token
    res_priority = client.get("/v1/jobs", headers={
        "Authorization": "Bearer hf_dummy_token_value_here",
        "X-API-Key": token
    })
    assert res_priority.status_code == 200




