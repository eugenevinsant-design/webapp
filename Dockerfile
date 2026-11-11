# Dockerfile для FastAPI-бэкенда ECG Analyzer
# Образ: Python 3.11-slim (легкий, без лишних пакетов)
# Запуск: uvicorn app.main:app

FROM python:3.11-slim AS base

# Метаданные образа
LABEL maintainer="Asdergh" \
      org.opencontainers.image.source="https://github.com/Asdergh/EcgMetaNarrator" \
      org.opencontainers.image.description="ECG Analyzer API (FastAPI + PostgreSQL)"

# Переменные окружения
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Рабочая директория
WORKDIR /app

# Системные зависимости
# - libpq-dev: для asyncpg (PostgreSQL)
# - gcc: для сборки некоторых пакетов (если понадобится)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Сначала копируем только requirements.txt (кэш слоев Docker)
COPY requirements.txt .

# Устанавливаем Python-зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY app/ ./app/

# Копируем Alembic (конфиг + миграции) для управления схемой БД
COPY alembic.ini .
COPY alembic/ ./alembic/

# Копируем фронтенд (HTML, CSS, JS, картинки)
COPY frontend/ ./frontend/

# Копируем тесты (для запуска в CI/CD)
COPY tests/ ./tests/

# Копируем frontend (если он нужен для статики; в Варианте 3 UI отдельный,
# но оставляем на случай, если понадобится отдавать статику)
# COPY frontend/ ./frontend/

# Создаем папку для данных (ЭКГ-файлы)
RUN mkdir -p /app/data/signals

# Порт, на котором работает FastAPI
EXPOSE 8000

# Healthcheck (для Docker/K8s)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Запуск приложения
# --host 0.0.0.0 — чтобы был доступен извне контейнера
# --port 8000 — порт FastAPI
# Без --reload (prod-режим); для dev используем docker-compose с volume и --reload
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
