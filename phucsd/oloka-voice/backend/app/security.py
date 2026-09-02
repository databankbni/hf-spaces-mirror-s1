from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from datetime import datetime
from app.config import settings
from app.database import get_db
from app.models import User, ApiKey

security_scheme = HTTPBearer()

def verify_worker_token(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: Session = Depends(get_db)
):
    """Verifies that the provided Bearer token matches the configured WORKER_TOKEN OR a user's API Key."""
    token = credentials.credentials
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing worker token.",
        )
        
    # 1. Check if system worker token
    if settings.WORKER_TOKEN and token == settings.WORKER_TOKEN:
        return token

    # 2. Check if valid User API key
    user = db.query(User).filter(User.api_key == token).first()
    if user:
        return token

    # 3. Check if valid ApiKey record
    api_key_obj = db.query(ApiKey).filter(ApiKey.key == token).first()
    if api_key_obj:
        return token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid worker token.",
    )

