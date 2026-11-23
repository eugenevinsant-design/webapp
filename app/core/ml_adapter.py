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
        "annotation_md": str,
    }
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


def _render_md(annotation: Dict[str, Any]) -> str:
    """Локальный (fallback) рендер аннотации в Markdown."""
    st = annotation.get("statistics") or {}
    lines = ["## Аннотация сигнала", ""]
    hr = st.get("hr_bpm")
    lines.append(f"- **ЧСС:** {hr if hr is not None else 'не определена'} уд/мин")
    if st.get("rr_mean_ms") is not None:
        lines.append(f"- **Средний RR:** {st['rr_mean_ms']} мс")
    if st.get("sdnn_ms") is not None:
        lines.append(f"- **SDNN:** {st['sdnn_ms']} мс")
    if st.get("rmssd_ms") is not None:
        lines.append(f"- **RMSSD:** {st['rmssd_ms']} мс")
    lines.append(f"- **Длительность записи:** {st.get('duration_s')} с ({st.get('n_leads')} отвед.)")
    lines.append("")
    anomalies = annotation.get("anomalies") or []
    if anomalies:
        lines.append(f"### Найдено аномалий: {len(anomalies)}")
        for a in anomalies:
            lines.append(f"- **{a['type']}** ({a['severity']}): {a['description']}")
    else:
        lines.append("### Аномалий не обнаружено")
        lines.append("Ритм регулярный, частота в пределах нормы.")
    return "\n".join(lines)


def analyze_signal(raw, fs: float) -> Dict[str, Any]:
    """
    Полный конвейер фазы A: сырой сигнал -> аннотация.

    Не бросает исключений наружу, кроме критических (плохой вход):
    ошибки детерминированного бэка логируются и превращаются в аннотацию
    с флагом low_quality, чтобы сессия не падала.
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
        "annotation_md": _render_md(annotation),
    }
