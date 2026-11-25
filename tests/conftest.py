"""
Настройка тестового окружения.

Этот файл:
1. Подменяет DATABASE_URL на SQLite (in-memory) для тестов.
2. Создает тестовую БД перед тестами и удаляет после.
3. Предоставляет TestClient для запросов к API.
4. Настраивает асинхронный db_writer на тестовую БД и чистит
   pending_store между тестами (ProductVesrsion0.3).

ВАЖНО про in-memory SQLite: каждое новое соединение пула получает СВОЮ
пустую in-memory БД. Чтобы db_writer (фоновые сессии) видел ту же БД,
что и тестовая сессия, используем StaticPool — одно общее соединение.
"""

import pytest
import pytest_asyncio
from typing import AsyncGenerator

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app import models_db  # noqa: F401 (регистрация моделей)
from app.services.db_writer import db_writer
from app.services.pending_store import pending_store

# Используем SQLite in-memory для тестов (быстро, не требует PostgreSQL)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Создать тестовый движок SQLite и таблицы (StaticPool = одна общая БД)."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
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


@pytest_asyncio.fixture(autouse=True)
async def writer_lifecycle(engine):
    """Для каждого теста: чистый pending_store + запущенный db_writer,
    направленный в ТЕСТОВУЮ БД (а не в dev.db из settings)."""
    pending_store.clear()
    db_writer.session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    db_writer.dead_letters.clear()
    await db_writer.start()
    yield
    # Drain: все поставленные в очередь записи должны долететь в БД
    await db_writer.stop()
    db_writer.session_factory = None
    pending_store.clear()


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
