import os
import pytest
from fastapi.testclient import TestClient

os.environ["APP_ENV"] = "testing"
os.environ["WORKER_MODE"] = "mock"
os.environ["DATABASE_URL"] = "sqlite:///./test_admin_db.sqlite"
os.environ["WORKER_TOKEN"] = "test_secret_token"

from app.main import app
from app.database import Base, engine

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    # Seed admin user manually for testing
    from app.database import SessionLocal
    from app.models import User
    from app.utils.auth import get_password_hash
    import secrets
    db = SessionLocal()
    hashed_pwd = get_password_hash("admin_password_2026")
    api_key = f"ovg_live_{secrets.token_hex(24)}"
    admin_user = User(
        id="usr_admin_test_123",
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
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    try:
        if os.path.exists("test_admin_db.sqlite"):
            os.remove("test_admin_db.sqlite")
    except Exception:
        pass

def test_admin_seeding_and_access():
    # 1. Login as default seeded admin
    login_res = client.post("/v1/auth/login", json={
        "username": "phucsd@gmail.com",
        "password": "admin_password_2026"
    })
    assert login_res.status_code == 200
    admin_token = login_res.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Verify admin profile
    me_res = client.get("/v1/auth/me", headers=admin_headers)
    assert me_res.status_code == 200
    assert me_res.json()["is_admin"] is True
    assert me_res.json()["is_verified"] is True

    # 2. Register a normal user and login
    reg_res = client.post("/v1/auth/register", json={
        "username": "normal_guy",
        "password": "password_123",
        "email": "normal@example.com"
    })
    assert reg_res.status_code == 201
    otp_code = reg_res.json()["debug_code"]

    # Verify normal user
    verify_res = client.post("/v1/auth/verify-email", json={
        "username": "normal_guy",
        "code": otp_code
    })
    assert verify_res.status_code == 200

    login_guy = client.post("/v1/auth/login", json={
        "username": "normal_guy",
        "password": "password_123"
    })
    guy_token = login_guy.json()["access_token"]
    guy_headers = {"Authorization": f"Bearer {guy_token}"}

    # 3. Test normal user blocked from admin endpoints -> 403
    stats_res = client.get("/v1/admin/stats", headers=guy_headers)
    assert stats_res.status_code == 403

    users_res = client.get("/v1/admin/users", headers=guy_headers)
    assert users_res.status_code == 403

    # 4. Test admin can access stats -> 200
    stats_res = client.get("/v1/admin/stats", headers=admin_headers)
    assert stats_res.status_code == 200
    stats = stats_res.json()
    assert stats["total_users"] >= 2  # admin + normal_guy
    assert stats["verified_users"] >= 2

    # 5. Test admin can list users -> 200
    users_res = client.get("/v1/admin/users", headers=admin_headers)
    assert users_res.status_code == 200
    users = users_res.json()
    assert len(users) >= 2
    normal_user_obj = next(u for u in users if u["username"] == "normal_guy")
    assert normal_user_obj["is_admin"] is False

    # 6. Test middleware logging
    # Fire a generic api call that is loggable
    client.get("/v1/jobs", headers=guy_headers)

    # Check admin logs to see if that request got recorded
    logs_res = client.get("/v1/admin/logs", headers=admin_headers)
    assert logs_res.status_code == 200
    logs = logs_res.json()
    assert len(logs) > 0
    # There should be a log record for /v1/jobs with normal_guy's username
    jobs_log = next((l for l in logs if l["endpoint"] == "/v1/jobs"), None)
    assert jobs_log is not None
    assert jobs_log["username"] == "normal_guy"
    assert jobs_log["method"] == "GET"

    # 7. Test admin update user
    update_res = client.put(f"/v1/admin/users/{normal_user_obj['id']}", json={
        "is_admin": True
    }, headers=admin_headers)
    assert update_res.status_code == 200
    assert update_res.json()["is_admin"] is True

    # 8. Test admin delete user
    del_res = client.delete(f"/v1/admin/users/{normal_user_obj['id']}", headers=admin_headers)
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "success"

    # Verify user is deleted
    users_res = client.get("/v1/admin/users", headers=admin_headers)
    assert not any(u["username"] == "normal_guy" for u in users_res.json())

def test_admin_advanced_features():
    # Login as admin
    login_res = client.post("/v1/auth/login", json={
        "username": "phucsd@gmail.com",
        "password": "admin_password_2026"
    })
    admin_token = login_res.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Admin creates a user directly
    create_res = client.post("/v1/admin/users", json={
        "username": "direct_user",
        "email": "direct@example.com",
        "password": "password_direct",
        "is_verified": True,
        "is_approved": True,
        "is_admin": False
    }, headers=admin_headers)
    assert create_res.status_code == 201
    direct_user = create_res.json()
    assert direct_user["username"] == "direct_user"
    assert direct_user["email"] == "direct@example.com"
    assert direct_user["is_verified"] is True
    assert direct_user["is_approved"] is True

    # Login as created user
    login_direct = client.post("/v1/auth/login", json={
        "username": "direct_user",
        "password": "password_direct"
    })
    assert login_direct.status_code == 200
    direct_token = login_direct.json()["access_token"]
    direct_headers = {"Authorization": f"Bearer {direct_token}"}

    # 2. Admin updates created user (blocks approval and changes password)
    update_res = client.put(f"/v1/admin/users/{direct_user['id']}", json={
        "is_approved": False,
        "password": "new_password_direct"
    }, headers=admin_headers)
    assert update_res.status_code == 200
    assert update_res.json()["is_approved"] is False

    # Try logging in as blocked user -> 403 Forbidden
    login_direct_fail = client.post("/v1/auth/login", json={
        "username": "direct_user",
        "password": "new_password_direct"
    })
    assert login_direct_fail.status_code == 403
    assert "chưa được duyệt" in login_direct_fail.json()["detail"]

    # Try API key call or token verification for blocked user -> 403
    me_res_fail = client.get("/v1/auth/me", headers=direct_headers)
    assert me_res_fail.status_code == 403

    # Re-approve user
    client.put(f"/v1/admin/users/{direct_user['id']}", json={"is_approved": True}, headers=admin_headers)

    # 3. API Key Management for direct_user
    # Admin gets user keys (empty at first)
    keys_res = client.get(f"/v1/admin/users/{direct_user['id']}/apikeys", headers=admin_headers)
    assert keys_res.status_code == 200
    assert len(keys_res.json()) == 0

    # Admin creates an API Key for user
    create_key_res = client.post(f"/v1/admin/users/{direct_user['id']}/apikeys", json={
        "name": "Prod Server Key"
    }, headers=admin_headers)
    assert create_key_res.status_code == 201
    key_obj = create_key_res.json()
    assert key_obj["name"] == "Prod Server Key"
    assert "ovg_live_" in key_obj["key"]

    # Retrieve again
    keys_res = client.get(f"/v1/admin/users/{direct_user['id']}/apikeys", headers=admin_headers)
    assert len(keys_res.json()) == 1

    # Call an endpoint using the generated API Key
    api_key_headers = {"Authorization": f"Bearer {key_obj['key']}"}
    jobs_res = client.get("/v1/jobs", headers=api_key_headers)
    assert jobs_res.status_code == 200

    # Admin revokes the key
    del_key_res = client.delete(f"/v1/admin/apikeys/{key_obj['id']}", headers=admin_headers)
    assert del_key_res.status_code == 200

    # Verification fails now
    jobs_res_fail = client.get("/v1/jobs", headers=api_key_headers)
    assert jobs_res_fail.status_code == 401

    # 4. Global System Settings CRUD
    settings_res = client.get("/v1/admin/settings", headers=admin_headers)
    assert settings_res.status_code == 200
    orig_settings = settings_res.json()
    assert orig_settings["worker_mode"] == "mock"
    assert orig_settings["require_admin_approval"] is False

    # Update system settings
    update_settings_res = client.post("/v1/admin/settings", json={
        "worker_mode": "kaggle",
        "require_admin_approval": True,
        "smtp_host": "smtp.test-server.com",
        "smtp_port": 1025
    }, headers=admin_headers)
    assert update_settings_res.status_code == 200

    # Verify updated settings
    settings_res = client.get("/v1/admin/settings", headers=admin_headers)
    new_settings = settings_res.json()
    assert new_settings["worker_mode"] == "kaggle"
    assert new_settings["require_admin_approval"] is True
    assert new_settings["smtp_host"] == "smtp.test-server.com"
    assert new_settings["smtp_port"] == 1025

def test_google_oauth_and_approval():
    # 1. Test Google OAuth login for phucsd@gmail.com (automatically admin & approved)
    res_phuc = client.post("/v1/auth/oauth/mock", json={
        "email": "phucsd@gmail.com",
        "username": "phucsd",
        "oauth_provider": "google",
        "oauth_id": "google_test_phucsd_123"
    })
    assert res_phuc.status_code == 200
    token_phuc = res_phuc.json()["access_token"]
    headers_phuc = {"Authorization": f"Bearer {token_phuc}"}

    me_phuc = client.get("/v1/auth/me", headers=headers_phuc)
    assert me_phuc.status_code == 200
    assert me_phuc.json()["is_admin"] is True

    # Enable require_admin_approval
    client.post("/v1/admin/settings", json={"require_admin_approval": True}, headers=headers_phuc)

    # 2. Test new user signup via Google OAuth when require_admin_approval = True -> 403 Forbidden
    res_new_user = client.post("/v1/auth/oauth/mock", json={
        "email": "pending_user@gmail.com",
        "username": "pending_user",
        "oauth_provider": "google",
        "oauth_id": "google_test_pending_456"
    })
    assert res_new_user.status_code == 403
    assert "chưa được duyệt" in res_new_user.json()["detail"]

    # 3. Non-Google OAuth provider rejected -> 400 Bad Request
    res_github = client.post("/v1/auth/oauth/mock", json={
        "email": "hacker@github.com",
        "username": "hacker",
        "oauth_provider": "github",
        "oauth_id": "github_123"
    })
    assert res_github.status_code == 400
    assert "chỉ hỗ trợ đăng nhập qua tài khoản Google" in res_github.json()["detail"]
