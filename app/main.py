from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import logging
import os

from app.api.routes import ecg, upload

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ECG Analyzer API",
    description="API для анализа ЭКГ сигналов (.hea + .mat)",   # ← .dat → .mat
    version="2.0.0"
)

# CORS — только если фронт ходит с другого origin
# Если фронт отдаётся с того же сервера — можно убрать целиком
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,     # ← либо False, либо конкретный список origins
    allow_methods=["*"],
    allow_headers=["*"],
)

# Роуты API
app.include_router(ecg.router, prefix="/api/ecg", tags=["ECG"])
app.include_router(upload.router, prefix="/api/upload", tags=["Upload"])

# Служебные эндпоинты — ДО монтирования статики
@app.get("/health")
async def health():
    return {"status": "healthy"}

# Статика — В САМОМ КОНЦЕ, монтируется на "/"
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
    logger.info(f"🌐 Frontend смонтирован: {frontend_path}")
else:
    logger.warning(f"⚠️ Папка frontend не найдена: {frontend_path}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)