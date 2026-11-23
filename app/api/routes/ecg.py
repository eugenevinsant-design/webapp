"""
HTTP-роуты для работы с ЭКГ-сигналами.

Эндпоинты:
- GET  /api/ecg/            — список доступных пакетов (.hea + .mat).
- GET  /api/ecg/{id}        — метаданные одного пакета.
- GET  /api/ecg/{id}/data   — отсчёты для отрисовки графика.
- POST /api/ecg/reload      — принудительное пересканирование папки.

Примечание: анализ сигнала (ML + LLM) выполняется через /api/chat
(команда \\choose_pkg <pkg>), а не через отдельные task-эндпоинты.
Поэтому исторические /analyze, /status, /results, /history здесь
намеренно отсутствуют — это был мёртвый дублирующий код.
"""

import logging
from typing import List

from fastapi import APIRouter, HTTPException

from app.core.ecg_loader import ecg_loader
from app.models import ECGSignal

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/", response_model=List[ECGSignal])
async def get_signals() -> List[ECGSignal]:
    """Получить список всех доступных сигналов."""
    signals = ecg_loader.scan_signals()
    logger.info(f"Отправлено {len(signals)} сигналов")
    return signals


@router.post("/reload")
async def reload_signals():
    """Принудительно пересканировать папку с сигналами."""
    signals = ecg_loader.scan_signals(force=True)
    return {"status": "ok", "count": len(signals)}


@router.get("/{signal_id}")
async def get_signal(signal_id: int):
    """Получить метаданные сигнала по ID."""
    for signal in ecg_loader.scan_signals():
        if signal["id"] == signal_id:
            return signal
    raise HTTPException(status_code=404, detail="Сигнал не найден")


@router.get("/{signal_id}/data")
async def get_signal_data(signal_id: int):
    """Получить данные сигнала для отрисовки графика (первый канал)."""
    data = ecg_loader.get_signal_data(signal_id)
    if not data:
        raise HTTPException(status_code=404, detail="Данные сигнала не найдены")
    return data
