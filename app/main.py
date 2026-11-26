from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import asyncio
import logging
import os

from app.api.routes import ecg, chat, auth
from app.config import settings
from app.database import init_db, close_db
from app.services.db_writer import db_writer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ленивая инициализация: на serverless (Vercel) lifespan не гарантирован,
# поэтому первый запрос сам догоняет init через middleware ниже.
_init_lock = asyncio.Lock()
_initialized = False


async def ensure_initialized() -> None:
    """Идемпотентная инициализация: таблицы БД + фоновый писатель."""
    global _initialized
    if _initialized:
        return
    async with _init_lock:
        if _initialized:
            return
        await init_db()
        if not settings.is_serverless:
            # Фоновый worker имеет смысл только в долгоживущем процессе;
            # на serverless запись синхронная (grade_service.write_now).
            await db_writer.start()
        _initialized = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управление жизненным циклом приложения.

    При старте: создаем таблицы в БД (если их нет) — это выполняет
    требование ТЗ «сохранять prompt в БД».
    При остановке: закрываем пул соединений (отказоустойчивость).
    """
    logger.info(" Запуск приложения: инициализация БД...")
    await ensure_initialized()
    logger.info(" Приложение готово к работе")
    yield
    logger.info(" Остановка приложения: drain очереди записи и закрытие пула...")
    await db_writer.stop()
    await close_db()


app = FastAPI(
    title="ECG Analyzer API",
    description="API для анализа ЭКГ сигналов (.hea + .dat)",
    version="0.3.0",
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

if settings.is_serverless:
    # На serverless lifespan может не вызваться — инициализируемся на
    # первом входящем запросе (идемпотентно, один раз на инстанс).
    @app.middleware("http")
    async def ensure_init_middleware(request: Request, call_next):
        await ensure_initialized()
        return await call_next(request)

# Роуты
app.include_router(ecg.router, prefix="/api/ecg", tags=["ECG"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])

# /health ДО монтирования статики: StaticFiles на "/" перехватывает все
# пути, поэтому health-роут должен быть зарегистрирован раньше,
# иначе HEALTHCHECK в Dockerfile всегда получает 404.
@app.get("/health")
async def health():
    return {"status": "healthy"}

# Статика (монтируется последней — перехватывает всё остальное)
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)