"""
Зависимости FastAPI (аутентификация).
"""

from fastapi import Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.database import get_db
from app.models_db import User
from app.services.auth_service import get_user_by_token


async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Получить текущего пользователя по токену из заголовка Authorization.

    Ожидаемый формат: Authorization: Bearer <token>
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Требуется авторизация (Bearer token)")

    token = authorization.replace("Bearer ", "").strip()
    user = await get_user_by_token(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="Неверный токен")

    return user
