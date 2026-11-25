"""
Роуты аутентификации.

Поток входа на платформу (ProductVesrsion0.3):
1. POST /api/auth/platform-access: проверка токена доступа к платформе
   (таблица platform_tokens в БД).
2. POST /api/auth/register: логин + токен платформы -> личный api_token.
3. POST /api/auth/login: вход по паре логин + личный токен.
- GET /api/auth/me: проверка Bearer-токена (возвращает данные пользователя).
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.auth import (
    PlatformAccessRequest,
    PlatformAccessResponse,
    RegisterRequest,
    RegisterResponse,
    LoginRequest,
    UserResponse,
)
from app.services.auth_service import (
    register_user,
    verify_platform_token,
    authenticate_user,
)
from app.api.deps import get_current_user
from app.models_db import User

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/platform-access", response_model=PlatformAccessResponse)
async def platform_access(
    request: PlatformAccessRequest,
    db: AsyncSession = Depends(get_db),
) -> PlatformAccessResponse:
    """Шаг 1: проверить токен доступа к платформе (по БД)."""
    ok = await verify_platform_token(db, request.platform_token)
    if not ok:
        raise HTTPException(status_code=403, detail="Неверный токен доступа к платформе")
    return PlatformAccessResponse(ok=True)


@router.post("/register", response_model=RegisterResponse)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """
    Шаг 2: регистрация (логин + токен платформы) -> личный api_token.

    Без валидного токена платформы регистрация запрещена (403).
    Если ник уже занят — вернет существующего пользователя и его токен.
    """
    if not await verify_platform_token(db, request.platform_token):
        raise HTTPException(status_code=403, detail="Неверный токен доступа к платформе")
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


@router.post("/login", response_model=UserResponse)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Шаг 3: вход по паре логин + личный токен (оба должны совпасть)."""
    user = await authenticate_user(db, request.username, request.token)
    if not user:
        raise HTTPException(status_code=401, detail="Неверный логин или токен")
    return UserResponse(user_id=user.id, username=user.username)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Проверить токен и вернуть данные пользователя."""
    return UserResponse(user_id=current_user.id, username=current_user.username)
