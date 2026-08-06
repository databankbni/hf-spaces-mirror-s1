from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, validator
from utils.auth_utils import (
    create_user, authenticate_user,
    create_access_token, decode_token,
)

router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)


# ── Schemas ───────────────────────────────────────────────────────────────────
class AuthRequest(BaseModel):
    username: str
    password: str

    @validator("username")
    def username_valid(cls, v):
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        if len(v) > 30:
            raise ValueError("Username too long (max 30 characters)")
        return v

    @validator("password")
    def password_valid(cls, v):
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


# ── Dependency ────────────────────────────────────────────────────────────────
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


# ── Routes ────────────────────────────────────────────────────────────────────
@router.post("/auth/register", response_model=TokenResponse)
async def register(body: AuthRequest):
    try:
        user = create_user(body.username, body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    token = create_access_token({"sub": user["username"], "id": user["id"]})
    return TokenResponse(access_token=token, username=user["username"])


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: AuthRequest):
    user = authenticate_user(body.username, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token({"sub": user["username"], "id": user["id"]})
    return TokenResponse(access_token=token, username=user["username"])


@router.get("/auth/me")
async def me(current_user: dict = Depends(get_current_user)):
    return {"username": current_user.get("sub"), "id": current_user.get("id")}
