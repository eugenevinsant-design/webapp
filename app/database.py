"""
Подключение к PostgreSQL (async) через SQLAlchemy.

Этот модуль отвечает за:
- Создание async-движка (create_async_engine) с пулом соединений.
- Фабрику сессий (async_sessionmaker).
- Dependency get_db() для FastAPI (открывает/закрывает сессию на запрос).
- Инициализацию таблиц (init_db) — временно, позже заменим на Alembic.

Пул соединений настроен на 40 одновременных пользователей:
- pool_size=10 (постоянные соединения)
- max_overflow=20 (дополнительные при пиковой нагрузке)
Итого: до 30 соединений, PostgreSQL по умолчанию держит 100.
"""

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base
from typing import AsyncGenerator
import logging

from app.config import settings

logger = logging.getLogger(__name__)

# Базовый класс для моделей (используется в models_db.py)
Base = declarative_base()

# Async-движок с пулом соединений
# echo=False — не логировать каждый SQL-запрос (в prod включим при необходимости)
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=settings.POOL_SIZE,
    max_overflow=settings.MAX_OVERFLOW,
    pool_pre_ping=True,  # проверять соединение перед использованием (отказоустойчивость)
    pool_recycle=3600,   # пересоздавать соединения раз в час (избегать таймаутов)
)

# Фабрика сессий
# expire_on_commit=False — чтобы после commit() объекты оставались доступны
# (иначе SQLAlchemy попытается перезагрузить их, что в async может упасть)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency для получения сессии БД.

    Использование в роуте:
        @router.post("/chat")
        async def chat(db: AsyncSession = Depends(get_db)):
            ...

    Сессия автоматически закрывается после завершения запроса.
    При ошибке — откатывается (rollback).
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Создать все таблицы в БД (если их нет).

    ВАЖНО: Это временное решение для разработки. В production
    используем Alembic-миграции (см. README_INTEGRATION.md).
    """
    # Импортируем модели, чтобы они зарегистрировались в Base.metadata
    from app import models_db  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info(" Таблицы БД созданы/проверены")


async def close_db() -> None:
    """Закрыть пул соединений при остановке приложения."""
    await engine.dispose()
    logger.info(" Пул соединений с БД закрыт")
