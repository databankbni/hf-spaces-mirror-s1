from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.admin import get_admin_by_email, update_admin_login
from app.database import get_db
from app.schemas.admin import Token, TokenRefresh
from app.security import verify_password, create_token_pair, verify_token


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=Token)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Authenticate admin and return JWT tokens using OAuth2 password flow."""
    admin = await get_admin_by_email(db, email=form_data.username)
    
    if not admin or not verify_password(form_data.password, admin.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin account is deactivated",
        )
    
    await update_admin_login(db, admin=admin)
    return create_token_pair(subject=admin.email)


@router.post("/refresh", response_model=Token)
async def refresh_token(
    refresh_data: TokenRefresh,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Generate new access token using a valid refresh token."""
    token_data = verify_token(refresh_data.refresh_token, token_type="refresh")
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    
    admin = await get_admin_by_email(db, email=token_data.sub)
    if not admin or not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin not found or inactive",
        )
    
    return create_token_pair(subject=admin.email)


@router.post("/logout")
async def logout():
    """Logout the current admin (client-side token deletion)."""
    return {"message": "Successfully logged out"}
