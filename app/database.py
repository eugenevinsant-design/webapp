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
#
# SQLite (локальная разработка/тесты) не поддерживает pool_size/max_overflow —
# там используется NullPool/StaticPool. Для PostgreSQL параметры пула валидны.
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")
_engine_kwargs = {
    "echo": False,
    "pool_pre_ping": True,  # проверять соединение перед использованием (отказоустойчивость)
}
if not _is_sqlite:
    _engine_kwargs.update(
        pool_size=settings.POOL_SIZE,
        max_overflow=settings.MAX_OVERFLOW,
        pool_recycle=3600,  # пересоздавать соединения раз в час (избегать таймаутов)
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

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


def _ensure_prompt_state_columns(sync_conn) -> None:
    """Лёгкая миграция: добавить новые колонки prompt_states в существующую БД.

    create_all не меняет уже существующие таблицы, поэтому для dev.db,
    созданной до ProductVesrsion0.3, добавляем колонки вручную.
    ALTER TABLE ADD COLUMN идемпотентен через проверку inspect().
    """
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "prompt_states" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("prompt_states")}
    if "description" not in cols:
        sync_conn.execute(text("ALTER TABLE prompt_states ADD COLUMN description TEXT"))
        logger.info("Миграция: добавлена колонка prompt_states.description")
    if "user_id" not in cols:
        sync_conn.execute(
            text("ALTER TABLE prompt_states ADD COLUMN user_id INTEGER REFERENCES users(id)")
        )
        logger.info("Миграция: добавлена колонка prompt_states.user_id")


async def init_db() -> None:
    """
    Создать все таблицы в БД (если их нет) + дотащить новые колонки
    в уже существующих таблицах (лёгкая миграция без Alembic).

    ВАЖНО: Это временное решение для разработки. В production
    используем Alembic-миграции (см. README_INTEGRATION.md).
    """
    # Импортируем модели, чтобы они зарегистрировались в Base.metadata
    from app import models_db  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_prompt_state_columns)
    logger.info(" Таблицы БД созданы/проверены")


async def close_db() -> None:
    """Закрыть пул соединений при остановке приложения."""
    await engine.dispose()
    logger.info(" Пул соединений с БД закрыт")
