import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ["APP_ENV"] = "testing"
os.environ["WORKER_MODE"] = "mock"
os.environ["DATABASE_URL"] = "sqlite:///./test_auth_db.sqlite"
os.environ["WORKER_TOKEN"] = "test_secret_token"

from app.main import app
from app.database import Base, engine, get_db

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    try:
        if os.path.exists("test_auth_db.sqlite"):
            os.remove("test_auth_db.sqlite")
    except Exception:
        pass

def test_auth_flow():
    # 1. Register a user
    response = client.post("/v1/auth/register", json={
        "username": "auth_test_user",
        "password": "strong_password_123",
        "email": "auth_test_user@example.com"
    })
    assert response.status_code == 201
    res_data = response.json()
    assert res_data["status"] == "success"
    assert "debug_code" in res_data
    otp_code = res_data["debug_code"]

    # 2. Register same user -> should fail (400)
    response = client.post("/v1/auth/register", json={
        "username": "auth_test_user",
        "password": "strong_password_123",
        "email": "auth_test_user@example.com"
    })
    assert response.status_code == 400

    # 3. Login before verifying -> should fail with 403 (unverified)
    response = client.post("/v1/auth/login", json={
        "username": "auth_test_user",
        "password": "strong_password_123"
    })
    assert response.status_code == 403

    # 4. Verify email with wrong code -> should fail (400)
    response = client.post("/v1/auth/verify-email", json={
        "username": "auth_test_user",
        "code": "111111"
    })
    assert response.status_code == 400

    # 5. Verify email with correct code -> should succeed (200)
    response = client.post("/v1/auth/verify-email", json={
        "username": "auth_test_user",
        "code": otp_code
    })
    assert response.status_code == 200

    # 6. Login successfully after verification
    response = client.post("/v1/auth/login", json={
        "username": "auth_test_user",
        "password": "strong_password_123"
    })
    assert response.status_code == 200
    token_data = response.json()
    assert "access_token" in token_data
    token = token_data["access_token"]

    # 7. Get current profile
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/v1/auth/me", headers=headers)
    assert response.status_code == 200
    user_data = response.json()
    assert user_data["username"] == "auth_test_user"
    assert user_data["is_verified"] is True
    assert user_data["is_admin"] is False
    assert user_data["has_api_key"] is True
    initial_api_key = user_data["api_key"]
    assert initial_api_key is not None

    # 8. Generate new API key
    response = client.post("/v1/auth/apikey", headers=headers)
    assert response.status_code == 200
    new_key_data = response.json()
    assert new_key_data["status"] == "success"
    new_api_key = new_key_data["api_key"]
    assert new_api_key != initial_api_key

    # 9. Test mock OAuth register/login
    response = client.post("/v1/auth/oauth/mock", json={
        "email": "oauth_user@example.com",
        "username": "oauth_user",
        "oauth_provider": "google",
        "oauth_id": "google_12345"
    })
    assert response.status_code == 200
    oauth_token = response.json()["access_token"]
    
    oauth_headers = {"Authorization": f"Bearer {oauth_token}"}
    response = client.get("/v1/auth/me", headers=oauth_headers)
    assert response.status_code == 200
    oauth_user_data = response.json()
    assert oauth_user_data["username"] == "oauth_user"
    assert oauth_user_data["email"] == "oauth_user@example.com"
    assert oauth_user_data["is_verified"] is True  # OAuth is pre-verified
