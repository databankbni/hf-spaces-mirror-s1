from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status, Query, Header
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User, ApiKey

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login", auto_error=False)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=settings.JWT_EXPIRATION_HOURS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

def get_current_user(token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Không thể xác thực thông tin đăng nhập.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
        
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
        
    if not user.is_approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản của bạn chưa được duyệt hoặc đã bị khóa bởi Admin."
        )
        
    return user

def get_user_or_api_key(
    token: Optional[str] = Depends(oauth2_scheme),
    token_query: Optional[str] = Query(None, alias="token"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    x_ov_api_key: Optional[str] = Header(None, alias="X-OV-API-Key"),
    db: Session = Depends(get_db)
) -> User:
    """
    Authenticates either via JWT Token (Authorization: Bearer <JWT>)
    OR via User Static API Key (Authorization: Bearer <API_KEY>) from ApiKey table.
    Allows query parameter fallback for browsers (?token=...)
    Also supports custom headers X-API-Key / X-OV-API-Key.
    """
    auth_token = x_api_key or x_ov_api_key or token or token_query
    if auth_token and auth_token.startswith("Bearer "):
        auth_token = auth_token.split(" ", 1)[1]
    
    if not auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Yêu cầu xác thực tài khoản hoặc API Key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    # 1. Try treating token as a JWT token
    try:
        payload = jwt.decode(auth_token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        username: str = payload.get("sub")
        if username is not None:
            user = db.query(User).filter(User.username == username).first()
            if user:
                if not user.is_approved:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Tài khoản của bạn chưa được duyệt hoặc đã bị khóa bởi Admin."
                    )
                return user
    except JWTError:
        pass

    # 2. Try treating token as a key from ApiKey table
    api_key_obj = db.query(ApiKey).filter(ApiKey.key == auth_token).first()
    if api_key_obj:
        api_key_obj.last_used_at = datetime.utcnow()
        db.commit()
        user = db.query(User).filter(User.id == api_key_obj.user_id).first()
        if user:
            if not user.is_approved:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Tài khoản của bạn chưa được duyệt hoặc đã bị khóa bởi Admin."
                )
            return user

    # 3. Fallback to old User.api_key for backward compatibility
    user = db.query(User).filter(User.api_key == auth_token).first()
    if user:
        if not user.is_approved:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tài khoản của bạn chưa được duyệt hoặc đã bị khóa bởi Admin."
            )
        return user
        
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Mã Token xác thực hoặc API Key không hợp lệ.",
        headers={"WWW-Authenticate": "Bearer"},
    )
