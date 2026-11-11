"""
Единый модуль настроек приложения.

Все настройки читаются из переменных окружения (.env) через pydantic-settings.
Это позволяет:
- Не хардкодить пароли и пути в коде.
- Легко интегрировать сервис в другой репозиторий (достаточно передать свой .env).
- Валидировать типы (например, POOL_SIZE должен быть числом).

Использование:
    from app.config import settings
    print(settings.DATABASE_URL)
    print(settings.SIGNALS_DIR)
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from typing import List, Literal


class Settings(BaseSettings):
    """
    Настройки приложения.

    Все поля читаются из .env (или переменных окружения).
    Значения по умолчанию подобраны так, чтобы не сломать текущую
    работу ecg_loader (SIGNALS_DIR = './data/signals').
    """

    # Режим работы: dev (с --reload) или prod (без --reload)
    APP_ENV: Literal["dev", "prod"] = "dev"

    # Подключение к PostgreSQL (asyncpg)
    # Пример: postgresql+asyncpg://ecg_user:ecg_password@localhost:5432/ecg_analyzer
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://ecg_user:ecg_password@localhost:5432/ecg_analyzer",
        description="Строка подключения к PostgreSQL (asyncpg)"
    )

    # Путь к папке с ЭКГ-файлами (.hea + .mat)
    # Дефолт совпадает с текущим значением в ecg_loader.py, чтобы не сломать работу
    SIGNALS_DIR: str = Field(
        default="./data/signals",
        description="Путь к папке с ЭКГ-файлами"
    )

    # CORS: список origin'ов, которым разрешено обращаться к API
    # В .env указывается через запятую: "http://localhost:3000,http://localhost:8080"
    ALLOWED_ORIGINS: str = Field(
        default="*",
        description="Список origin'ов для CORS (через запятую)"
    )

    # Пул соединений с БД (для 40 одновременных пользователей)
    POOL_SIZE: int = Field(
        default=10,
        description="Размер пула соединений с БД"
    )
    MAX_OVERFLOW: int = Field(
        default=20,
        description="Максимальное количество дополнительных соединений"
    )

    # Секретный ключ (для будущей аутентификации, пока не используется)
    SECRET_KEY: str = Field(
        default="change-me-in-production",
        description="Секретный ключ для подписи токенов (JWT) в будущем"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # игнорировать лишние переменные в .env
    )

    @field_validator("ALLOWED_ORIGINS")
    @classmethod
    def parse_origins(cls, v: str) -> str:
        """Оставляем строку как есть, парсинг в список — в свойстве ниже."""
        return v

    @property
    def allowed_origins_list(self) -> List[str]:
        """
        Возвращает список origin'ов для CORSMiddleware.
        Если ALLOWED_ORIGINS = "*", возвращает ["*"] (разрешить все).
        Иначе разбивает строку по запятой и убирает пробелы.
        """
        if self.ALLOWED_ORIGINS.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]


# Глобальный объект настроек (импортируется во всех модулях)
settings = Settings()
