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
from typing import AsyncGenerator, Dict, Tuple
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
import logging

from app.config import settings

logger = logging.getLogger(__name__)

# Базовый класс для моделей (используется в models_db.py)
Base = declarative_base()


def _normalize_db_url(url: str) -> Tuple[str, Dict]:
    """Привести DATABASE_URL к виду, понятному SQLAlchemy+asyncpg.

    Облачные Postgres (Neon/Supabase/Vercel Postgres) отдают строки вида
    postgresql://...?sslmode=require — без драйвера и с libpq-параметром
    sslmode, который asyncpg как kwarg не принимает. Поэтому:
    - postgres:// / postgresql:// -> postgresql+asyncpg://
    - sslmode/ssl (не disable) выносим в connect_args={"ssl": True}

    SQLite-строки возвращаются как есть (urlunparse ломает ':///...').
    """
    connect_args: Dict = {}
    if url.startswith("sqlite"):
        return url, connect_args
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]

    parts = urlparse(url)
    qs = dict(parse_qsl(parts.query))
    sslmode = qs.pop("sslmode", None) or qs.pop("ssl", None)
    # channel_binding — libpq-параметр (в строках Neon), asyncpg.connect
    # его не принимает: TypeError: unexpected keyword argument.
    # SCRAM-аутентификация и так идёт поверх ssl=True, поэтому просто
    # выбрасываем параметр.
    qs.pop("channel_binding", None)
    if sslmode is None and not qs:
        return url, connect_args  # запрос-строку не трогали — возвращаем как есть
    if sslmode and sslmode.lower() not in ("disable", "false", "0"):
        connect_args["ssl"] = True
    url = urlunparse(parts._replace(query=urlencode(qs)))
    return url, connect_args


_db_url, _connect_args = _normalize_db_url(settings.DATABASE_URL)

# Async-движок с пулом соединений
# echo=False — не логировать каждый SQL-запрос (в prod включим при необходимости)
#
# SQLite (локальная разработка/тесты) не поддерживает pool_size/max_overflow —
# там используется NullPool/StaticPool. Для PostgreSQL параметры пула валидны.
_is_sqlite = _db_url.startswith("sqlite")
_engine_kwargs = {
    "echo": False,
    "pool_pre_ping": True,  # проверять соединение перед использованием (отказоустойчивость)
}
if _connect_args:
    _engine_kwargs["connect_args"] = _connect_args

if settings.is_serverless:
    # Serverless (Vercel): функции эфемерны, держать пул соединений нельзя —
    # каждое обращение открывает и закрывает своё соединение (NullPool).
    from sqlalchemy.pool import NullPool
    _engine_kwargs["poolclass"] = NullPool
    logger.info("Serverless-режим: пул соединений БД = NullPool")
elif not _is_sqlite:
    _engine_kwargs.update(
        pool_size=settings.POOL_SIZE,
        max_overflow=settings.MAX_OVERFLOW,
        pool_recycle=3600,  # пересоздавать соединения раз в час (избегать таймаутов)
    )

engine = create_async_engine(_db_url, **_engine_kwargs)

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


# Целевой порядок колонок prompt_states (ProductVesrsion0.3)
_PROMPT_STATES_COLUMN_ORDER = [
    "id", "user_id", "session_id", "question", "current_raw_pkg_path",
    "fs", "grade", "context", "description", "updated_at",
]


def _ensure_prompt_state_columns(sync_conn) -> None:
    """Лёгкая миграция prompt_states: новые колонки + целевой порядок.

    create_all не меняет уже существующие таблицы, поэтому для dev.db,
    созданной до ProductVesrsion0.3:
    1. Добавляем недостающие колонки (ALTER TABLE ADD COLUMN).
    2. Если порядок колонок отличается от целевого (id, user_id,
       session_id, ..., context, description, updated_at) — пересоздаём
       таблицу с копированием данных (SQLite не умеет переупорядочивать
       колонки иначе). Данные (id строк) сохраняются.
    """
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "prompt_states" not in insp.get_table_names():
        return

    cols = [c["name"] for c in insp.get_columns("prompt_states")]
    if "description" not in cols:
        sync_conn.execute(text("ALTER TABLE prompt_states ADD COLUMN description TEXT"))
        cols.append("description")
        logger.info("Миграция: добавлена колонка prompt_states.description")
    if "user_id" not in cols:
        sync_conn.execute(
            text("ALTER TABLE prompt_states ADD COLUMN user_id INTEGER REFERENCES users(id)")
        )
        cols.append("user_id")
        logger.info("Миграция: добавлена колонка prompt_states.user_id")

    # Порядок уже целевой — ничего пересоздавать не надо
    if cols == _PROMPT_STATES_COLUMN_ORDER:
        return

    # Пересоздаём таблицу с целевым порядком (SQLite и PostgreSQL не умеют
    # переупорядочивать колонки иначе). Данные (id строк) сохраняются.
    dialect = sync_conn.dialect.name
    if dialect == "postgresql":
        id_col = "id SERIAL PRIMARY KEY"
        fs_col = "fs DOUBLE PRECISION"
        ts_col = "updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL"
    else:  # sqlite
        id_col = "id INTEGER NOT NULL PRIMARY KEY"
        fs_col = "fs FLOAT"
        ts_col = "updated_at DATETIME NOT NULL"

    logger.info("Миграция: пересоздаю prompt_states с целевым порядком колонок (%s)...", dialect)
    sync_conn.execute(text(f"""
        CREATE TABLE prompt_states_new (
            {id_col},
            user_id INTEGER REFERENCES users(id),
            session_id INTEGER NOT NULL UNIQUE REFERENCES sessions(id),
            question TEXT,
            current_raw_pkg_path VARCHAR(500),
            {fs_col},
            grade INTEGER,
            context TEXT,
            description TEXT,
            {ts_col}
        )
    """))
    sync_conn.execute(text("""
        INSERT INTO prompt_states_new
            (id, user_id, session_id, question, current_raw_pkg_path,
             fs, grade, context, description, updated_at)
        SELECT id, user_id, session_id, question, current_raw_pkg_path,
               fs, grade, context, description, updated_at
        FROM prompt_states
    """))
    sync_conn.execute(text("DROP TABLE prompt_states"))
    sync_conn.execute(text("ALTER TABLE prompt_states_new RENAME TO prompt_states"))
    # Индексы (старые упали вместе с таблицей)
    sync_conn.execute(text(
        "CREATE UNIQUE INDEX ix_prompt_states_session_id ON prompt_states (session_id)"
    ))
    sync_conn.execute(text(
        "CREATE INDEX ix_prompt_states_user_id ON prompt_states (user_id)"
    ))
    if dialect == "postgresql":
        # Синхронизируем sequence после вставки строк с явными id
        sync_conn.execute(text(
            "SELECT setval(pg_get_serial_sequence('prompt_states','id'), "
            "COALESCE((SELECT MAX(id) FROM prompt_states), 1))"
        ))
    logger.info("Миграция: prompt_states пересоздана, порядок колонок обновлён")


def _seed_platform_token(sync_conn) -> None:
    """Посеять токен доступа к платформе из настроек.

    Токены платформы живут в БД (platform_tokens) — их можно добавлять
    и отзывать без рестарта. PLATFORM_ACCESS_TOKEN из .env добавляется,
    если его там ещё нет (идемпотентно: перезапуск не дублирует).
    """
    from sqlalchemy import text

    exists = sync_conn.execute(
        text("SELECT COUNT(*) FROM platform_tokens WHERE token = :t"),
        {"t": settings.PLATFORM_ACCESS_TOKEN},
    ).scalar()
    if exists:
        return
    sync_conn.execute(
        text("INSERT INTO platform_tokens (token, label, is_active, created_at) "
             "VALUES (:token, :label, 1, CURRENT_TIMESTAMP)"),
        {"token": settings.PLATFORM_ACCESS_TOKEN, "label": "bootstrap (.env)"},
    )
    logger.info("Миграция: токен платформы из PLATFORM_ACCESS_TOKEN записан в БД")


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
        await conn.run_sync(_seed_platform_token)
    logger.info(" Таблицы БД созданы/проверены")


async def close_db() -> None:
    """Закрыть пул соединений при остановке приложения."""
    await engine.dispose()
    logger.info(" Пул соединений с БД закрыт")
