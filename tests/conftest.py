"""
Настройка тестового окружения.

Этот файл:
1. Подменяет DATABASE_URL на SQLite (in-memory) для тестов.
2. Создает тестовую БД перед тестами и удаляет после.
3. Предоставляет TestClient для запросов к API.
"""

import asyncio
import pytest
import pytest_asyncio
from typing import AsyncGenerator

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.main import app
from app.database import Base, get_db
from app import models_db  # noqa: F401 (регистрация моделей)

# Используем SQLite in-memory для тестов (быстро, не требует PostgreSQL)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Создать тестовый движок SQLite и таблицы."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Предоставить тестовую сессию БД."""
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """
    Предоставить TestClient с подмененной БД и авторизацией.

    Регистрирует тестового пользователя и подставляет его Bearer-токен
    во все запросы через default headers (ТЗ: chat-эндпоинты требуют auth).
    """
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Регистрируем пользователя и получаем токен
        reg = await ac.post("/api/auth/register", json={"username": "testuser"})
        assert reg.status_code == 200, reg.text
        token = reg.json()["api_token"]
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def anon_client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """TestClient без авторизации (для проверки 401)."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
