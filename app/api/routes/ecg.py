from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import List
import logging
import uuid
import asyncio
from datetime import datetime

from app.models import ECGSignal, AnalysisRequest, SignalStatus
from app.core.ecg_loader import ecg_loader
from app.core.ai_analyzer import ai_analyzer

logger = logging.getLogger(__name__)
router = APIRouter()

# Хранилище задач
tasks = {}


# ============================================================
# СПЕЦИФИЧНЫЕ МАРШРУТЫ — ДО /{signal_id}
# ============================================================

@router.get("/", response_model=List[ECGSignal])
async def get_signals():
    """Получить список всех сигналов"""
    signals = ecg_loader.scan_signals()
    logger.info(f"📊 Отправлено {len(signals)} сигналов")
    return signals


@router.post("/reload")
async def reload_signals():
    """Принудительно пересканировать папку"""
    signals = ecg_loader.scan_signals(force=True)
    return {"status": "ok", "count": len(signals)}


@router.get("/history")
async def get_history(limit: int = 50):
    """Получить историю анализов"""
    results = []
    for task_id, task in tasks.items():
        if task.get("status") == SignalStatus.COMPLETED:
            results.append({
                "task_id": task_id,
                "signal_id": task.get("signal_id"),
                "status": task.get("status"),
                "created_at": task.get("created_at"),
                "completed_at": task.get("completed_at"),
                "quality_score": task.get("quality_score"),
                "anomalies_count": len(task.get("anomalies", [])),
                "report_markdown": task.get("report_markdown", ""),
            })
    return sorted(results, key=lambda x: x.get("created_at", ""), reverse=True)[:limit]


@router.get("/status/{task_id}")
async def get_analysis_status(task_id: str):
    """Получить статус анализа"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return tasks[task_id]


@router.get("/results/{task_id}")
async def get_analysis_result(task_id: str):
    """Получить результат анализа"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return tasks[task_id]


@router.post("/analyze")
async def analyze_signal(request: AnalysisRequest, background_tasks: BackgroundTasks):
    """Запустить анализ сигнала"""
    task_id = str(uuid.uuid4())

    # Проверяем существует ли сигнал
    signals = ecg_loader.scan_signals()
    signal = None
    for s in signals:
        if s["id"] == request.signal_id:
            signal = s
            break

    if not signal:
        raise HTTPException(status_code=404, detail="Сигнал не найден")

    # Создаем задачу
    tasks[task_id] = {
        "task_id": task_id,
        "signal_id": request.signal_id,
        "status": SignalStatus.PENDING,
        "progress": 0,
        "created_at": datetime.now().isoformat(),
    }

    # Запускаем фоновую обработку
    background_tasks.add_task(process_analysis, task_id, signal, request.params)

    return {
        "task_id": task_id,
        "signal_id": request.signal_id,
        "status": SignalStatus.PENDING,
        "message": "Анализ запущен",
    }


# ============================================================
# ПАРАМЕТРИЗОВАННЫЕ МАРШРУТЫ — ПОСЛЕДНИМИ
# ============================================================

@router.get("/{signal_id}")
async def get_signal(signal_id: int):
    """Получить сигнал по ID"""
    signals = ecg_loader.scan_signals()
    for signal in signals:
        if signal["id"] == signal_id:
            return signal
    raise HTTPException(status_code=404, detail="Сигнал не найден")


@router.get("/{signal_id}/data")
async def get_signal_data(signal_id: int):
    """Получить данные сигнала для графика"""
    data = ecg_loader.get_signal_data(signal_id)
    if not data:
        raise HTTPException(status_code=404, detail="Данные сигнала не найдены")
    return data


# ============================================================
# ФОНОВАЯ ОБРАБОТКА
# ============================================================

async def process_analysis(task_id: str, signal: dict, params: dict):
    """Фоновая обработка анализа"""
    try:
        tasks[task_id]["status"] = SignalStatus.PROCESSING
        tasks[task_id]["progress"] = 10

        # Имитация прогресса
        for i in range(20, 101, 10):
            await asyncio.sleep(0.3)
            tasks[task_id]["progress"] = i

        # Запускаем анализ
        result = await ai_analyzer.analyze(signal["id"], signal, params)

        tasks[task_id].update({
            "status": SignalStatus.COMPLETED,
            "progress": 100,
            "report_markdown": result["report_markdown"],
            "anomalies": result["anomalies"],
            "statistics": result["statistics"],
            "quality_score": result["quality_score"],
            "model": result["model"],
            "timestamp": result["timestamp"],
            "completed_at": datetime.now().isoformat(),
        })

        logger.info(f"✅ Анализ {task_id} завершен")

    except Exception as e:
        logger.error(f"❌ Ошибка анализа {task_id}: {e}")
        tasks[task_id].update({
            "status": SignalStatus.FAILED,
            "error": str(e),
        })