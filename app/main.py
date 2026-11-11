from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import logging
import os

from app.api.routes import ecg, chat, auth
from app.config import settings
from app.database import init_db, close_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управление жизненным циклом приложения.

    При старте: создаем таблицы в БД (если их нет) — это выполняет
    требование ТЗ «сохранять prompt в БД».
    При остановке: закрываем пул соединений (отказоустойчивость).
    """
    logger.info(" Запуск приложения: инициализация БД...")
    await init_db()
    logger.info(" Приложение готово к работе")
    yield
    logger.info(" Остановка приложения: закрытие пула соединений...")
    await close_db()


app = FastAPI(
    title="ECG Analyzer API",
    description="API для анализа ЭКГ сигналов (.hea + .dat)",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS (настраивается через .env: ALLOWED_ORIGINS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Роуты
app.include_router(ecg.router, prefix="/api/ecg", tags=["ECG"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])

# Статика
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)