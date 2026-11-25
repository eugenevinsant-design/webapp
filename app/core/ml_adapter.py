"""
Адаптер ML: вход модели -> структурированная аннотация.

Точка подключения torch-модели: реализуйте analyze_with_torch(inp) по
контракту signal_analyzer.analyze_signal и включите ML_BACKEND=torch
в .env. Остальной стек менять не нужно.

Контракт выхода analyze_signal (заморожен):
    {
        "model": str,
        "statistics": dict,
        "anomalies": [{"type", "severity", "description"}],
        "annotation_json": {...структурированная аннотация...},
    }

Текст ответа ВСЕГДА пишет LLM (app/core/llm_client.py) на основе
annotation_json — локального fallback-рендера нет.
"""

import logging
from typing import Any, Dict

from app.config import settings
from app.core.ml_input import build_ml_input
from app.core.signal_analyzer import analyze_signal as _deterministic_analyze

logger = logging.getLogger(__name__)


def analyze_with_torch(inp: Dict[str, Any]) -> Dict[str, Any]:
    """
    ТОЧКА ПОДКЛЮЧЕНИЯ РЕАЛЬНОЙ МОДЕЛИ.

    Ожидаемый контракт (совпадает с signal_analyzer.analyze_signal):
        {"model": str, "statistics": {...}, "anomalies": [...]}

    Когда будут веса:
        1. import torch as th
        2. x = th.from_numpy(inp["signal"])[None]  # [1, C, N]
        3. out = model(x, fs=inp["fs"])            # выход с полем prediction
        4. С map классов -> anomalies/statistics (см. MultiBCECriterion)
    """
    raise NotImplementedError(
        "Torch-модель не подключена: реализуйте analyze_with_torch в "
        "app/core/ml_adapter.py и положите веса в проект. "
        "Либо верните ML_BACKEND=deterministic в .env."
    )


def analyze_signal(raw, fs: float) -> Dict[str, Any]:
    """
    Полный конвейер фазы A: сырой сигнал -> структурированные факты.

    Не бросает исключений наружу, кроме критических (плохой вход):
    ошибки детерминированного бэка логируются и превращаются в аннотацию
    с флагом low_quality, чтобы сессия не падала.

    Текст для пользователя здесь НЕ формируется — это делает LLM
    по annotation_json (см. llm_client.generate_annotation_text).
    """
    backend = settings.ML_BACKEND.lower().strip()
    if backend == "torch":
        result = analyze_with_torch(build_ml_input(raw, fs))
    else:
        if backend != "deterministic":
            logger.warning(f"Неизвестный ML_BACKEND={backend}, использую deterministic")
        result = _deterministic_analyze(raw, fs)

    annotation = {
        "model": result.get("model", "deterministic"),
        "statistics": result.get("statistics", {}),
        "anomalies": result.get("anomalies", []),
    }
    return {
        **result,
        "annotation_json": annotation,
    }
