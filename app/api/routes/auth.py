"""
Роуты аутентификации.

- POST /api/auth/register: регистрация (возвращает токен).
- GET /api/auth/me: проверка токена (возвращает данные пользователя).
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.auth import RegisterRequest, RegisterResponse, UserResponse
from app.services.auth_service import register_user
from app.api.deps import get_current_user
from app.models_db import User

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/register", response_model=RegisterResponse)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """
    Зарегистрировать нового пользователя.

    Если ник уже занят — вернет существующий токен.
    """
    try:
        user = await register_user(db, request.username)
        return RegisterResponse(
            user_id=user.id,
            username=user.username,
            api_token=user.api_token,
        )
    except Exception as e:
        logger.error(f"Ошибка регистрации: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка регистрации: {e}")


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Проверить токен и вернуть данные пользователя."""
    return UserResponse(user_id=current_user.id, username=current_user.username)
