from datetime import datetime, timedelta, timezone
from typing import Optional, Union
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from app.config import settings

# Password hashing configuration
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=settings.password_hash_rounds,
)


class TokenData(BaseModel):
    """JWT token payload data."""
    sub: str  # Subject (admin email or ID)
    exp: datetime
    type: str  # "access" or "refresh"
    jti: Optional[str] = None  # JWT ID for token invalidation


class TokenPair(BaseModel):
    """JWT access and refresh token pair."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # Seconds until access token expires


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify if plain password matches the hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Generate a secure hash of the password."""
    return pwd_context.hash(password)


def create_access_token(
    subject: Union[str, int],
    expires_delta: Optional[timedelta] = None,
    additional_claims: Optional[dict] = None,
) -> str:
    """Generate a JWT access token with the given subject and claims."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    
    to_encode = {
        "sub": str(subject),
        "exp": expire,
        "type": "access",
        "iat": datetime.now(timezone.utc),
        **(additional_claims or {}),
    }
    
    return jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(
    subject: Union[str, int],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Generate a JWT refresh token with a unique ID for invalidation."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=settings.jwt_refresh_token_expire_days)
    )
    
    import uuid
    to_encode = {
        "sub": str(subject),
        "exp": expire,
        "type": "refresh",
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid.uuid4()),  # Unique ID for token invalidation
    }
    
    return jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_token_pair(subject: Union[str, int]) -> TokenPair:
    """Create a new access/refresh token pair for the subject."""
    return TokenPair(
        access_token=create_access_token(subject),
        refresh_token=create_refresh_token(subject),
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


def decode_token(token: str) -> Optional[TokenData]:
    """Decode and validate a JWT token, returning its data if valid."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        
        return TokenData(
            sub=payload.get("sub"),
            exp=datetime.fromtimestamp(payload.get("exp"), tz=timezone.utc),
            type=payload.get("type", "access"),
            jti=payload.get("jti"),
        )
    except JWTError:
        return None


def verify_token(token: str, token_type: str = "access") -> Optional[TokenData]:
    """Verify token validity and check if it matches the expected type."""
    token_data = decode_token(token)
    if not token_data:
        return None
        
    if token_data.type != token_type:
        return None
        
    if datetime.now(timezone.utc) > token_data.exp:
        return None
        
    return token_data


def generate_invite_token(email: str, expires_hours: int = 48) -> str:
    """Generate a time-limited invite token for admin registration."""
    to_encode = {
        "sub": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=expires_hours),
        "type": "invite",
        "iat": datetime.now(timezone.utc),
    }
    
    return jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def verify_invite_token(token: str) -> Optional[str]:
    """Verify an invite token and return the associated email if valid."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        
        if payload.get("type") != "invite":
            return None
            
        return payload.get("sub")
        
    except JWTError:
        return None
