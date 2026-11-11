"""
Настройка окружения Alembic для async PostgreSQL.

Этот файл:
1. Читает DATABASE_URL из app.config.settings (а не из alembic.ini).
2. Использует async-движок (asyncpg).
3. Импортирует Base.metadata из models_db, чтобы Alembic видел модели.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Импортируем настройки и Base из нашего приложения
from app.config import settings
from app.database import Base
from app import models_db  # noqa: F401 (чтобы модели зарегистрировались в Base.metadata)

# Конфигурация Alembic
config = context.config

# Переопределяем sqlalchemy.url из настроек приложения
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Настройка логирования
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Метаданные для автогенерации миграций
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Запуск миграций в offline-режиме (без подключения к БД)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Синхронная часть запуска миграций (вызывается из async)."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Запуск миграций в async-режиме."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Запуск миграций в online-режиме (с подключением к БД)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
