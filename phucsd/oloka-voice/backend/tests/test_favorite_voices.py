import os
import pytest
import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

os.environ["APP_ENV"] = "testing"
os.environ["WORKER_MODE"] = "mock"
os.environ["DATABASE_URL"] = "sqlite:///./test_fav_db.sqlite"

from app.main import app
from app.database import Base, engine, SessionLocal
from app.models import User, TTSJob, VoiceSample
from app.utils.auth import create_access_token
from app.utils.ids import generate_id

client = TestClient(app)
DUMMY_WAV_PATH = "test_dummy_source.wav"

@pytest.fixture(scope="module", autouse=True)
def setup_db_and_files():
    # 1. Setup tables
    Base.metadata.create_all(bind=engine)
    
    # 2. Create a dummy WAV file (10 seconds long at 16000Hz)
    sr = 16000
    data = np.sin(2 * np.pi * 440 * np.arange(sr * 10) / sr)  # 10s of 440Hz sine wave
    sf.write(DUMMY_WAV_PATH, data, sr, format='WAV', subtype='PCM_16')
    
    yield
    
    # 3. Cleanup
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    
    for p in ["test_fav_db.sqlite", DUMMY_WAV_PATH]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

def test_save_favorite_voice_flow():
    # Create session
    db = SessionLocal()
    
    # 1. Create two test users (User A and User B)
    user_a_id = generate_id("usr")
    user_a = User(
        id=user_a_id,
        username="usera",
        hashed_password="hashedpasswordA",
        is_verified=True,
        is_approved=True
    )
    
    user_b_id = generate_id("usr")
    user_b = User(
        id=user_b_id,
        username="userb",
        hashed_password="hashedpasswordB",
        is_verified=True,
        is_approved=True
    )
    
    db.add(user_a)
    db.add(user_b)
    db.commit()
    
    # 2. Create completed job for User A
    job_id = generate_id("job")
    job = TTSJob(
        id=job_id,
        user_id=user_a_id,
        job_type="auto_voice",
        status="completed",
        text="Đây là văn bản thử nghiệm dài hơn mười lăm từ để kiểm tra tính năng gợi ý văn bản tham khảo.",
        output_audio_path=DUMMY_WAV_PATH
    )
    db.add(job)
    db.commit()
    
    # 3. Log in as User A and User B (generate JWT tokens)
    token_a = create_access_token({"sub": "usera"})
    token_b = create_access_token({"sub": "userb"})
    
    # 4. Save voice as PRIVATE for User A
    headers_a = {"Authorization": f"Bearer {token_a}"}
    payload_private = {
        "job_id": job_id,
        "name": "Giọng riêng tư của A",
        "is_public": False,
        "ref_text": "Đây là văn bản thử nghiệm"
    }
    
    response = client.post("/v1/voice-samples/save-favorite", json=payload_private, headers=headers_a)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    vs_private_id = data["voice_sample_id"]
    
    # Verify file is trimmed to 8 seconds
    vs_rec = db.query(VoiceSample).filter(VoiceSample.id == vs_private_id).first()
    assert vs_rec is not None
    assert vs_rec.name == "Giọng riêng tư của A"
    assert vs_rec.is_public is False
    assert os.path.exists(vs_rec.file_path)
    
    # Read the saved file and check length (max 8 seconds * samplerate)
    data_trimmed, sr_trimmed = sf.read(vs_rec.file_path)
    assert sr_trimmed == 16000
    assert len(data_trimmed) == 8 * 16000 # Exactly 8 seconds
    
    # 5. List voice samples as User A (should see their private sample)
    response = client.get("/v1/voice-samples", headers=headers_a)
    assert response.status_code == 200
    samples_a = response.json()
    assert len(samples_a) == 1
    assert samples_a[0]["id"] == vs_private_id
    
    # 6. List voice samples as User B (should NOT see User A's private sample)
    headers_b = {"Authorization": f"Bearer {token_b}"}
    response = client.get("/v1/voice-samples", headers=headers_b)
    assert response.status_code == 200
    samples_b = response.json()
    assert len(samples_b) == 0
    
    # 7. Save another voice as PUBLIC for User A
    job_id2 = generate_id("job")
    job2 = TTSJob(
        id=job_id2,
        user_id=user_a_id,
        job_type="auto_voice",
        status="completed",
        text="Văn bản công khai",
        output_audio_path=DUMMY_WAV_PATH
    )
    db.add(job2)
    db.commit()
    
    payload_public = {
        "job_id": job_id2,
        "name": "Giọng công khai của A",
        "is_public": True,
        "ref_text": "Văn bản công khai"
    }
    response = client.post("/v1/voice-samples/save-favorite", json=payload_public, headers=headers_a)
    assert response.status_code == 200
    vs_public_id = response.json()["voice_sample_id"]
    
    # 8. List voice samples as User B (should now see User A's public sample)
    response = client.get("/v1/voice-samples", headers=headers_b)
    assert response.status_code == 200
    samples_b = response.json()
    assert len(samples_b) == 1
    assert samples_b[0]["id"] == vs_public_id
    assert samples_b[0]["name"] == "Giọng công khai của A"
    assert samples_b[0]["is_public"] is True

    # Cleanup local trimmed files
    db_samples = db.query(VoiceSample).all()
    for s in db_samples:
        if os.path.exists(s.file_path):
            os.remove(s.file_path)
            
    db.close()


def test_public_voice_library_and_editing():
    db = SessionLocal()
    
    # 1. Create a user
    user_c_id = generate_id("usr")
    user_c = User(
        id=user_c_id,
        username="userc",
        hashed_password="hashedpasswordC",
        is_verified=True,
        is_approved=True
    )
    db.add(user_c)
    db.commit()
    
    # Create another user to test edit permissions
    user_d_id = generate_id("usr")
    user_d = User(
        id=user_d_id,
        username="userd",
        hashed_password="hashedpasswordD",
        is_verified=True,
        is_approved=True
    )
    db.add(user_d)
    db.commit()
    
    # Token
    token_c = create_access_token({"sub": "userc"})
    token_d = create_access_token({"sub": "userd"})
    headers_c = {"Authorization": f"Bearer {token_c}"}
    headers_d = {"Authorization": f"Bearer {token_d}"}
    
    # 2. Add public voice sample 1 (Miền Nam, Trẻ)
    job_id = generate_id("job")
    job = TTSJob(
        id=job_id,
        user_id=user_c_id,
        job_type="auto_voice",
        status="completed",
        text="Công khai Miền Nam",
        output_audio_path=DUMMY_WAV_PATH
    )
    db.add(job)
    db.commit()
    
    payload_1 = {
        "job_id": job_id,
        "name": "Giọng Nam Bộ Trẻ",
        "is_public": True,
        "ref_text": "Chào bạn",
        "tags": ["Miền Nam", "Trẻ"]
    }
    resp1 = client.post("/v1/voice-samples/save-favorite", json=payload_1, headers=headers_c)
    assert resp1.status_code == 200
    vs1_id = resp1.json()["voice_sample_id"]
    
    # 3. Add public voice sample 2 (Miền Bắc)
    job_id_2 = generate_id("job")
    job_2 = TTSJob(
        id=job_id_2,
        user_id=user_c_id,
        job_type="auto_voice",
        status="completed",
        text="Công khai Miền Bắc",
        output_audio_path=DUMMY_WAV_PATH
    )
    db.add(job_2)
    db.commit()
    
    payload_2 = {
        "job_id": job_id_2,
        "name": "Giọng Bắc Bộ Kể Chuyện",
        "is_public": True,
        "ref_text": "Kính chào quý vị",
        "tags": ["Miền Bắc", "Kể chuyện"]
    }
    resp2 = client.post("/v1/voice-samples/save-favorite", json=payload_2, headers=headers_c)
    assert resp2.status_code == 200
    vs2_id = resp2.json()["voice_sample_id"]
    
    # 4. Access public voice library endpoint without auth
    resp = client.get("/v1/voice-library")
    assert resp.status_code == 200
    items = resp.json()
    # Should contain at least our 2 newly created public voices
    ids = [item["id"] for item in items]
    assert vs1_id in ids
    assert vs2_id in ids
    
    # Check that preview_url and tags are populated
    vs1_item = next(item for item in items if item["id"] == vs1_id)
    assert vs1_item["name"] == "Giọng Nam Bộ Trẻ"
    assert "Miền Nam" in vs1_item["tags"]
    assert "Trẻ" in vs1_item["tags"]
    assert vs1_item["preview_url"] == f"/v1/voice-samples/{vs1_id}/audio"
    
    # 5. Filter by tag
    resp = client.get("/v1/voice-library?tag=Miền Nam")
    assert resp.status_code == 200
    items_filtered = resp.json()
    ids_filtered = [item["id"] for item in items_filtered]
    assert vs1_id in ids_filtered
    assert vs2_id not in ids_filtered
    
    # 6. Filter by search query
    resp = client.get("/v1/voice-library?search=Bắc")
    assert resp.status_code == 200
    items_searched = resp.json()
    ids_searched = [item["id"] for item in items_searched]
    assert vs2_id in ids_searched
    assert vs1_id not in ids_searched
    
    # 7. Edit voice sample details
    update_payload = {
        "name": "Giọng Nam Bộ Trẻ Cập Nhật",
        "tags": ["Miền Nam", "Trẻ", "Quảng cáo"],
        "ref_text": "Chào bạn hiền",
        "is_public": False
    }
    resp = client.put(f"/v1/voice-samples/{vs1_id}", json=update_payload, headers=headers_c)
    assert resp.status_code == 200
    updated_data = resp.json()
    assert updated_data["name"] == "Giọng Nam Bộ Trẻ Cập Nhật"
    assert "Quảng cáo" in updated_data["tags"]
    assert updated_data["ref_text"] == "Chào bạn hiền"
    assert updated_data["is_public"] is False
    
    # Verify it is no longer in the public library
    resp = client.get("/v1/voice-library")
    assert resp.status_code == 200
    items_public = resp.json()
    public_ids = [item["id"] for item in items_public]
    assert vs1_id not in public_ids
    
    # 8. Attempt edit by another user (User D)
    resp = client.put(f"/v1/voice-samples/{vs2_id}", json={"name": "Hacker Edit"}, headers=headers_d)
    assert resp.status_code == 404 # Endpoint returns 404 if not found or unauthorized
    
    # Cleanup files
    db_samples = db.query(VoiceSample).all()
    for s in db_samples:
        if os.path.exists(s.file_path):
            try:
                os.remove(s.file_path)
            except Exception:
                pass
                
    db.close()
