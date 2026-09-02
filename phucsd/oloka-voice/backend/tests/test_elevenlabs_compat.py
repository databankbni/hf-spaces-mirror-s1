import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

os.environ["APP_ENV"] = "testing"
os.environ["WORKER_MODE"] = "mock"
os.environ["DATABASE_URL"] = "sqlite:///./test_el_compat_db.sqlite"

from app.main import app
from app.database import Base, get_db, engine, SessionLocal
from app.models import User, VoiceSample, ApiKey

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    # Force clean DB on startup
    if os.path.exists("test_el_compat_db.sqlite"):
        try:
            os.remove("test_el_compat_db.sqlite")
        except Exception:
            pass

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    # 1. Create two test users
    from app.utils.auth import get_password_hash
    hashed_pwd = get_password_hash("password_123")
    
    user1 = db.query(User).filter(User.id == "usr_el_test_1").first()
    if not user1:
        user1 = User(
            id="usr_el_test_1",
            username="el_test_user_1",
            email="el1@test.local",
            hashed_password=hashed_pwd,
            is_verified=True,
            is_approved=True,
            api_key="api_key_el_1"
        )
        db.add(user1)
        
    user2 = db.query(User).filter(User.id == "usr_el_test_2").first()
    if not user2:
        user2 = User(
            id="usr_el_test_2",
            username="el_test_user_2",
            email="el2@test.local",
            hashed_password=hashed_pwd,
            is_verified=True,
            is_approved=True,
            api_key="api_key_el_2"
        )
        db.add(user2)
        
    db.commit()
    
    # Create fake WAV file on disk for previews
    dummy_wav_path = "test_dummy_el.wav"
    with open(dummy_wav_path, "wb") as f:
        f.write(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x22\x56\x00\x00\x44\xac\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00")
        
    # 2. Create voice samples
    # Public voice
    vs_public = db.query(VoiceSample).filter(VoiceSample.id == "vsp_el_public").first()
    if not vs_public:
        vs_public = VoiceSample(
            id="vsp_el_public",
            user_id="usr_el_test_1",
            name="Public Voice",
            source_type="uploaded",
            file_path=dummy_wav_path,
            is_public=True,
            tags="vietnamese, male, young"
        )
        db.add(vs_public)
        
    # User 1 Private voice
    vs_private_1 = db.query(VoiceSample).filter(VoiceSample.id == "vsp_el_private_1").first()
    if not vs_private_1:
        vs_private_1 = VoiceSample(
            id="vsp_el_private_1",
            user_id="usr_el_test_1",
            name="Private Voice 1",
            source_type="uploaded",
            file_path=dummy_wav_path,
            is_public=False,
            tags="vietnamese, female, middle_aged"
        )
        db.add(vs_private_1)
        
    # User 2 Private voice
    vs_private_2 = db.query(VoiceSample).filter(VoiceSample.id == "vsp_el_private_2").first()
    if not vs_private_2:
        vs_private_2 = VoiceSample(
            id="vsp_el_private_2",
            user_id="usr_el_test_2",
            name="Private Voice 2",
            source_type="uploaded",
            file_path=dummy_wav_path,
            is_public=False,
            tags="vietnamese, male, young"
        )
        db.add(vs_private_2)
        
    db.commit()
    db.close()
    
    yield
    
    # Cleanup DB
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    
    # Cleanup files
    if os.path.exists("test_el_compat_db.sqlite"):
        try:
            os.remove("test_el_compat_db.sqlite")
        except Exception:
            pass
    if os.path.exists(dummy_wav_path):
        try:
            os.remove(dummy_wav_path)
        except Exception:
            pass

def test_list_voices_compat():
    # Calling without auth header should fail with 401
    res = client.get("/v1/voices")
    assert res.status_code == 401

    # Calling with User 1 auth header
    res = client.get("/v1/voices", headers={"Authorization": "Bearer api_key_el_1"})
    assert res.status_code == 200
    data = res.json()
    assert "voices" in data
    
    voices = data["voices"]
    voice_ids = [v["voice_id"] for v in voices]
    
    # Should see User 1's own private voice and public voice, but NOT User 2's private voice
    assert "vsp_el_public" in voice_ids
    assert "vsp_el_private_1" in voice_ids
    assert "vsp_el_private_2" not in voice_ids
    
    # Check schema fields
    v_pub = next(v for v in voices if v["voice_id"] == "vsp_el_public")
    assert v_pub["name"] == "Public Voice"
    assert v_pub["category"] == "public"
    assert v_pub["labels"]["gender"] == "male"
    assert v_pub["labels"]["age"] == "young"
    assert "preview_url" in v_pub

def test_get_voice_compat():
    # Try fetching public voice details
    res = client.get("/v1/voices/vsp_el_public", headers={"Authorization": "Bearer api_key_el_1"})
    assert res.status_code == 200
    assert res.json()["name"] == "Public Voice"
    
    # Try fetching User 1 private voice details
    res = client.get("/v1/voices/vsp_el_private_1", headers={"Authorization": "Bearer api_key_el_1"})
    assert res.status_code == 200
    assert res.json()["name"] == "Private Voice 1"
    
    # Try fetching User 2 private voice details (should fail with 403)
    res = client.get("/v1/voices/vsp_el_private_2", headers={"Authorization": "Bearer api_key_el_1"})
    assert res.status_code == 403

def test_voice_previews():
    # Public voice preview should be accessible without auth
    res = client.get("/v1/voices/vsp_el_public/previews")
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/wav"

    # Private voice preview without auth should return 401
    res = client.get("/v1/voices/vsp_el_private_1/previews")
    assert res.status_code == 401

    # Private voice preview with header auth should succeed
    res = client.get("/v1/voices/vsp_el_private_1/previews", headers={"Authorization": "Bearer api_key_el_1"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/wav"

    # Private voice preview with query token parameter should succeed
    res = client.get("/v1/voices/vsp_el_private_1/previews?token=api_key_el_1")
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/wav"

    # Private voice preview with wrong token should fail
    res = client.get("/v1/voices/vsp_el_private_1/previews?token=wrong_token")
    assert res.status_code == 401

    # Private voice preview from another user's voice should return 403
    res = client.get("/v1/voices/vsp_el_private_2/previews?token=api_key_el_1")
    assert res.status_code == 403
