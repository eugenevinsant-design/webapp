"""
Сервис аутентификации.

Реализует:
- Регистрацию пользователя (создание + генерация токена).
- Поиск пользователя по токену (для авторизации).
- Генерацию безопасного токена.
"""

import secrets
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models_db import User

logger = logging.getLogger(__name__)


def generate_token() -> str:
    """Сгенерировать безопасный токен (32 байта = 64 символа hex)."""
    return secrets.token_hex(32)


async def register_user(db: AsyncSession, username: str) -> User:
    """
    Зарегистрировать нового пользователя.

    Если пользователь с таким ником уже существует — возвращает его
    (и его существующий токен).
    """
    # Проверяем, есть ли уже такой пользователь
    result = await db.execute(select(User).where(User.username == username))
    existing = result.scalar_one_or_none()
    if existing:
        logger.info(f"Пользователь {username} уже существует")
        return existing

    # Создаем нового пользователя с токеном
    token = generate_token()
    user = User(username=username, api_token=token)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info(f"✅ Зарегистрирован новый пользователь: {username}")
    return user


async def get_user_by_token(db: AsyncSession, token: str) -> Optional[User]:
    """Найти пользователя по токену (для авторизации)."""
    result = await db.execute(select(User).where(User.api_token == token))
    return result.scalar_one_or_none()
