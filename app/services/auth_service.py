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

from app.models_db import User, PlatformToken

logger = logging.getLogger(__name__)


def generate_token() -> str:
    """Сгенерировать безопасный токен (32 байта = 64 символа hex)."""
    return secrets.token_hex(32)


async def verify_platform_token(db: AsyncSession, token: str) -> bool:
    """Проверить токен доступа к платформе по таблице platform_tokens.

    Токены хранятся в БД: активный (is_active=1) -> доступ разрешён.
    Отозванный токен (is_active=0) не проходит.
    """
    if not token:
        return False
    result = await db.execute(
        select(PlatformToken).where(
            PlatformToken.token == token,
            PlatformToken.is_active == 1,
        )
    )
    return result.scalar_one_or_none() is not None


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


async def authenticate_user(db: AsyncSession, username: str, token: str) -> Optional[User]:
    """Вход на платформу: проверить ПАРУ логин + личный токен.

    Токен сам по себе не даёт входа — он должен принадлежать именно
    этому логину (защита от перебора/подмены чужого токена).
    """
    result = await db.execute(
        select(User).where(
            User.username == username,
            User.api_token == token,
        )
    )
    return result.scalar_one_or_none()
